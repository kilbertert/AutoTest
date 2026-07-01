# Pywinauto MCP Server — Windows 桌面自动化 MCP 服务器

## 文件概览

| 文件 | 路径 | 行数（约） | 作用 |
|------|------|-----------|------|
| 服务器入口 | `pywinauto-mcp-server/simple_server.py` | ~280 | MCP 服务器主程序 |
| 客户端 | `pywinauto-mcp-server/simple_client.py` | ~70 | MCP 客户端（测试用） |
| 驱动会话 | `pywinauto-mcp-server/driver_session.py` | ~50 | pywinauto 驱动会话管理 |
| LLM 对话 | `pywinauto-mcp-server/llm/chat.py` | ~120 | LLM 封装 |
| LLM 提示词 | `pywinauto-mcp-server/llm/prompt.py` | ~60 | 系统提示词 |
| 驱动工具 | `pywinauto-mcp-server/tools/pywinauto_driver_tool.py` | ~390 | Windows UI 核心工具 |
| 代码生成 | `pywinauto-mcp-server/tools/gen_code_tool.py` | ~70 | 代码生成工具 |
| 验证工具 | `pywinauto-mcp-server/tools/verify_tools.py` | ~155 | UI 验证工具 |
| 配置管理 | `pywinauto-mcp-server/utils/config_manager.py` | ~175 | 配置管理 |
| 元素工具 | `pywinauto-mcp-server/utils/element_util.py` | ~45 | UI 元素序列化 |
| 代码生成器 | `pywinauto-mcp-server/utils/gen_code.py` | ~195 | 测试代码生成 |
| 日志 | `pywinauto-mcp-server/utils/logger.py` | ~15 | 日志 |
| 响应格式 | `pywinauto-mcp-server/utils/response_format.py` | ~20 | 响应格式 |

---

## 一、与 appium-mcp-server 的架构对比

两个 MCP 服务器采用**几乎相同的架构模式**，但面向不同平台：

```
┌──────────────────────────────────────────────────────┐
│              相同的架构模式                            │
│                                                      │
│  simple_server.py (MCP stdio 服务器)                  │
│       │                                              │
│       ├── list_tools() → 注册工具                     │
│       └── call_tool()  → 工具路由                     │
│              │                                       │
│              ├── DriverSessionManager                │
│              ├── ConfigManager                       │
│              ├── Chat (LLM)                          │
│              └── CodeGenerator                       │
│                                                      │
│  不同点:                                              │
│  - appium: 多平台驱动 (Android/iOS/Mac)               │
│  - pywinauto: 单一 Windows 驱动                       │
│  - appium: Appium WebDriver API                      │
│  - pywinauto: UIA/MSAA 原生 API                      │
└──────────────────────────────────────────────────────┘
```

---

## 二、服务器入口（`simple_server.py`）

### 2.1 核心架构

```python
# 位置: pywinauto-mcp-server/simple_server.py

class App:
    def __init__(self):
        self.driver_session_manager = DriverSessionManager()
        self.config_manager = ConfigManager()
        self.chat = Chat()

    async def serve(self, endpoint: str):
        server = Server("pywinauto-mcp-server")
        
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                # 配置工具
                Tool(name="load_config", ...),
                Tool(name="get_configuration", ...),
                Tool(name="set_configuration", ...),
                
                # 驱动工具
                Tool(name="create_driver_session", ...),
                Tool(name="delete_driver_session", ...),
                Tool(name="pywinauto_driver_tool", ...),  # 核心工具
                
                # 验证工具
                Tool(name="verify_element", ...),
                Tool(name="verify_text", ...),
                Tool(name="verify_screenshot", ...),
                
                # 代码生成
                Tool(name="gen_code_tool", ...),
            ]
        
        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            # 工具路由
            ...
        
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, ...)
```

### 2.2 工具路由

与 appium 版本不同的是，pywinauto 的工具路由更加集中：

```python
# 位置: pywinauto-mcp-server/simple_server.py:~150-280
@server.call_tool()
async def call_tool(name: str, arguments: dict):
    tool_map = {
        "load_config": handle_load_config,
        "get_configuration": handle_get_configuration,
        "set_configuration": handle_set_configuration,
        "create_driver_session": handle_create_driver_session,
        "delete_driver_session": handle_delete_driver_session,
        "pywinauto_driver_tool": handle_pywinauto_driver_tool,
        "gen_code_tool": handle_gen_code_tool,
    }
    
    if name.startswith("verify_"):
        return await handle_verify_tool(name, arguments)
    
    handler = tool_map.get(name)
    if handler:
        return await handler(arguments)
```

---

## 三、驱动会话管理（`driver_session.py`）

```python
# 位置: pywinauto-mcp-server/driver_session.py

class DriverSessionManager:
    """
    管理 pywinauto Application/Window 会话。
    
    支持两种自动化后端:
    - uia: UI Automation (推荐，Windows 7+)
    - win32: MSAA (兼容旧应用)
    """
    
    def __init__(self):
        self.sessions = {}  # session_id → {app, window}
    
    async def create_session(self, params: dict) -> str:
        """
        创建 pywinauto 会话。
        
        params:
        - app_path: 应用可执行文件路径
        - backend: "uia" 或 "win32"
        - process_id: 可选的进程 ID（连接到已运行的应用）
        """
        from pywinauto import Application
        
        backend = params.get("backend", "uia")
        app = Application(backend=backend)
        
        if "app_path" in params:
            app.start(params["app_path"])
        elif "process_id" in params:
            app.connect(process=params["process_id"])
        
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = {
            "app": app,
            "backend": backend,
        }
        return session_id
    
    def get_app(self, session_id: str):
        return self.sessions[session_id]["app"]
    
    async def delete_session(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session:
            try:
                session["app"].kill()
            except:
                pass
```

---

## 四、驱动工具（`pywinauto_driver_tool.py`）

### 4.1 核心操作

```python
# 位置: pywinauto-mcp-server/tools/pywinauto_driver_tool.py

class PywinautoDriverTool:
    """
    Windows 桌面 UI 自动化工具。
    封装 pywinauto 的常见操作。
    """
    
    async def execute(self, action: str, params: dict) -> dict:
        app = self._get_app(params.get("session_id"))
        window = self._get_window(app, params)
        
        actions = {
            "click": self._click,
            "double_click": self._double_click,
            "right_click": self._right_click,
            "input_text": self._input_text,
            "set_text": self._set_text,
            "select_menu": self._select_menu,
            "select_combo": self._select_combo,
            "select_tab": self._select_tab,
            "select_radio": self._select_radio,
            "check_checkbox": self._check_checkbox,
            "scroll": self._scroll,
            "drag": self._drag,
            "screenshot": self._screenshot,
            "get_window_list": self._get_window_list,
            "get_element_tree": self._get_element_tree,
            "wait_for_element": self._wait_for_element,
            "close_window": self._close_window,
            "type_keys": self._type_keys,
        }
        
        return await actions[action](params)
```

### 4.2 元素定位

```python
# pywinauto 支持多种元素定位策略:

def _find_element(self, window, params: dict):
    """
    定位策略:
    - automation_id: UIA AutomationId
    - class_name: 窗口类名
    - title: 窗口标题
    - control_type: UIA ControlType (Button, Edit, etc.)
    - name: 元素名称
    - index: 同类元素中的索引
    """
    by = params.get("by", "automation_id")
    value = params.get("value")
    
    if by == "automation_id":
        return window.child_window(auto_id=value)
    elif by == "class_name":
        return window.child_window(class_name=value)
    elif by == "title":
        return window.child_window(title=value)
    elif by == "control_type":
        return window.child_window(control_type=value)
    # ...
```

### 4.3 菜单操作

```python
# 位置: pywinauto-mcp-server/tools/pywinauto_driver_tool.py:~250-290

async def _select_menu(self, params: dict):
    """
    选择菜单项。
    支持多级菜单路径: "File -> Open -> Recent"
    """
    window = self._get_current_window(params)
    menu_path = params["menu_path"].split("->")
    
    # pywinauto 菜单选择
    window.menu_select("->".join(menu_path))
```

### 4.4 键盘操作

```python
# 位置: pywinauto-mcp-server/tools/pywinauto_driver_tool.py:~300-320

async def _type_keys(self, params: dict):
    """
    模拟键盘输入。
    支持组合键: "^a" (Ctrl+A), "%f" (Alt+F), "{ENTER}"
    """
    window = self._get_current_window(params)
    keys = params["keys"]
    window.type_keys(keys)
```

---

## 五、代码生成（`utils/gen_code.py`）

```python
# 位置: pywinauto-mcp-server/utils/gen_code.py

class CodeGenerator:
    """
    pywinauto 测试代码生成器。
    生成 pytest + pywinauto 格式的测试代码。
    """
    
    def generate(self, actions: list, elements: list,
                 test_name: str, llm: Chat = None) -> str:
        code = []
        
        # 导入
        code.append("import pytest")
        code.append("from pywinauto import Application")
        code.append("from pywinauto.keyboard import send_keys")
        code.append("")
        
        # Fixture
        code.append("@pytest.fixture")
        code.append("def app():")
        code.append("    app = Application(backend='uia')")
        code.append("    app.start('APPLICATION_PATH')")
        code.append("    yield app")
        code.append("    app.kill()")
        code.append("")
        
        # 测试函数
        code.append(f"def test_{test_name}(app):")
        code.append("    window = app.window(title='WINDOW_TITLE')")
        code.append("    window.wait('visible', timeout=10)")
        code.append("")
        
        for action in actions:
            code.append(self._action_to_code(action))
        
        return "\n".join(code)
    
    def _action_to_code(self, action: dict) -> str:
        action_type = action["type"]
        
        if action_type == "click":
            return f'    window.child_window(auto_id="{action["auto_id"]}").click()'
        elif action_type == "input_text":
            return f'    window.child_window(auto_id="{action["auto_id"]}").set_text("{action["text"]}")'
        elif action_type == "select_menu":
            return f'    window.menu_select("{action["menu_path"]}")'
        # ...
```

---

## 六、LLM 集成（`llm/`）

### 6.1 `chat.py`

```python
# 位置: pywinauto-mcp-server/llm/chat.py

class Chat:
    """
    与 appium 版本相同的 LLM 封装。
    支持 OpenAI / Azure OpenAI / Ollama。
    """
    
    def __init__(self):
        self.llm = None
    
    def init_llm(self, config: dict):
        self.llm = ChatOpenAI(
            model=config.get("model_name", "gpt-4"),
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            temperature=0.1,
        )
```

### 6.2 `prompt.py` — 系统提示词

```python
# 位置: pywinauto-mcp-server/llm/prompt.py

SYSTEM_PROMPT = """
You are an expert Windows desktop test automation engineer.
Your task is to generate Python test code using pywinauto.

## Guidelines:
1. Use pytest as the testing framework
2. Use pywinauto with UIA backend for Windows automation
3. Follow Page Object Model (POM) pattern when appropriate
4. Include proper waits (wait, wait_not, timings)
5. Handle window management (connect, focus, close)

## pywinauto Patterns:
- Use `window.child_window(auto_id="...")` for element location
- Use `window.wait('visible', timeout=10)` for synchronization
- Use `window.menu_select("File->Open")` for menu navigation
- Use `window.type_keys("^a")` for keyboard shortcuts
"""
```

---

## 七、工具列表汇总

| 工具名 | 分类 | 功能 |
|--------|------|------|
| `load_config` | 配置 | 加载 JSON 配置文件 |
| `get_configuration` | 配置 | 获取当前配置 |
| `set_configuration` | 配置 | 修改配置项 |
| `create_driver_session` | 会话 | 创建 pywinauto 会话 |
| `delete_driver_session` | 会话 | 删除会话 |
| `pywinauto_driver_tool` | 驱动 | Windows UI 核心操作 |
| `verify_element` | 验证 | 验证元素存在/可见 |
| `verify_text` | 验证 | 验证文本内容 |
| `verify_screenshot` | 验证 | 截图对比验证 |
| `gen_code_tool` | 生成 | AI 生成测试代码 |

## 八、pywinauto_driver_tool 支持的操作

| 操作 | 说明 |
|------|------|
| `click` | 点击元素 |
| `double_click` | 双击元素 |
| `right_click` | 右键点击 |
| `input_text` | 逐字输入文本 |
| `set_text` | 直接设置文本 |
| `select_menu` | 选择菜单项 |
| `select_combo` | 选择下拉框项 |
| `select_tab` | 选择标签页 |
| `select_radio` | 选择单选按钮 |
| `check_checkbox` | 勾选复选框 |
| `scroll` | 滚动 |
| `drag` | 拖拽 |
| `screenshot` | 截图 |
| `get_window_list` | 获取窗口列表 |
| `get_element_tree` | 获取元素树 |
| `wait_for_element` | 等待元素出现 |
| `close_window` | 关闭窗口 |
| `type_keys` | 键盘输入 |
