# Appium MCP Server — 移动端/桌面端自动化 MCP 服务器

## 文件概览

| 文件 | 路径 | 行数（约） | 作用 |
|------|------|-----------|------|
| 服务器入口 | `appium-mcp-server/simple_server.py` | ~330 | MCP 服务器主程序 |
| 客户端 | `appium-mcp-server/simple_client.py` | ~95 | MCP 客户端（测试用） |
| 驱动会话 | `appium-mcp-server/driver_session.py` | ~50 | Appium Driver 会话管理 |
| LLM 对话 | `appium-mcp-server/llm/chat.py` | ~145 | LLM 封装（LangChain） |
| LLM 提示词 | `appium-mcp-server/llm/prompt.py` | ~65 | 系统提示词 |
| 驱动工具 | `appium-mcp-server/tools/appium_driver_tool.py` | ~390 | Appium 核心工具 |
| Android 工具 | `appium-mcp-server/tools/android_driver_tool.py` | ~155 | Android 驱动工具 |
| iOS 工具 | `appium-mcp-server/tools/ios_driver_tool.py` | ~155 | iOS 驱动工具 |
| Mac 工具 | `appium-mcp-server/tools/mac_driver_tool.py` | ~150 | macOS 驱动工具 |
| 配置工具 | `appium-mcp-server/tools/config_tool.py` | ~230 | 配置管理工具 |
| 代码生成 | `appium-mcp-server/tools/gen_code_tool.py` | ~95 | AI 代码生成工具 |
| 验证工具 | `appium-mcp-server/tools/verify_tools.py` | ~200 | UI 验证工具 |
| 配置管理 | `appium-mcp-server/utils/config_manager.py` | ~235 | 配置加载/保存 |
| 元素工具 | `appium-mcp-server/utils/element_util.py` | ~50 | UI 元素序列化 |
| 代码生成器 | `appium-mcp-server/utils/gen_code.py` | ~320 | 测试代码生成核心 |
| 日志 | `appium-mcp-server/utils/logger.py` | ~20 | 日志配置 |
| 响应格式化 | `appium-mcp-server/utils/response_format.py` | ~25 | MCP 响应格式 |

---

## 一、服务器入口（`simple_server.py`）

### 1.1 概述

这是 Appium MCP 服务器的**主入口**。它使用 Python 标准库 `asyncio` 和 MCP SDK 实现了一个 stdio 传输的 MCP 服务器。

### 1.2 核心架构

```python
# 位置: appium-mcp-server/simple_server.py

class App:
    def __init__(self):
        self.driver_session_manager = DriverSessionManager()  # 驱动会话管理
        self.config_manager = ConfigManager()                 # 配置管理
        self.chat = Chat()                                    # LLM 对话

    async def serve(self, endpoint: str):
        # 创建 MCP Server 实例
        server = Server(self._get_app_name())
        
        # 注册工具列表处理器
        @server.list_tools()
        async def list_tools() -> list[Tool]:
            ...
        
        # 注册工具调用处理器
        @server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            ...
        
        # 启动 stdio 传输
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, ...)
```

### 1.3 `list_tools()` — 工具注册

```python
# 位置: appium-mcp-server/simple_server.py:~80-230
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # 配置管理工具
        Tool(name="load_config", ...),       # 加载配置文件
        Tool(name="get_configuration", ...), # 获取当前配置
        Tool(name="set_configuration", ...), # 设置配置项
        
        # 驱动管理工具
        Tool(name="create_driver_session", ...), # 创建驱动会话
        Tool(name="delete_driver_session", ...), # 删除驱动会话
        
        # 平台驱动工具
        Tool(name="android_driver_tool", ...), # Android 操作
        Tool(name="ios_driver_tool", ...),     # iOS 操作
        Tool(name="mac_driver_tool", ...),     # macOS 操作
        
        # UI 验证工具
        Tool(name="verify_element", ...),      # 验证元素存在
        Tool(name="verify_text", ...),         # 验证文本内容
        Tool(name="verify_screenshot", ...),   # 验证截图
        Tool(name="verify_toast", ...),        # 验证 Toast 消息
        
        # 代码生成工具
        Tool(name="gen_code_tool", ...),       # 生成测试代码
    ]
```

### 1.4 `call_tool()` — 工具路由

```python
# 位置: appium-mcp-server/simple_server.py:~235-330
@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # 工具名 → 处理函数 映射
    if name == "load_config":
        return await load_config(arguments)
    elif name == "create_driver_session":
        return await create_driver_session(arguments)
    elif name == "android_driver_tool":
        return await handle_android_driver_tool(arguments)
    elif name == "gen_code_tool":
        return await handle_gen_code_tool(arguments)
    # ... 更多工具路由
    
    # 特殊处理：verify_* 工具通过 verify_tools 模块处理
    elif name.startswith("verify_"):
        return await handle_verify_tool(name, arguments)
```

---

## 二、驱动会话管理（`driver_session.py`）

### 2.1 类定义

```python
# 位置: appium-mcp-server/driver_session.py

class DriverSessionManager:
    """
    管理 Appium Driver 会话的生命周期。
    支持多个平台: android, ios, mac
    """
    
    def __init__(self):
        self.sessions = {}  # session_id → driver 实例
    
    async def create_session(self, platform: str, capabilities: dict):
        """根据平台创建对应的 Appium Driver"""
        if platform == "android":
            from appium.webdriver.webdriver import WebDriver
            driver = WebDriver(command_executor, desired_capabilities=capabilities)
        elif platform == "ios":
            driver = WebDriver(command_executor, desired_capabilities=capabilities)
        elif platform == "mac":
            from appium.webdriver.mac import Mac2Driver
            driver = Mac2Driver(command_executor, desired_capabilities=capabilities)
        
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = driver
        return session_id
    
    def get_session(self, session_id: str):
        return self.sessions.get(session_id)
    
    async def delete_session(self, session_id: str):
        driver = self.sessions.pop(session_id, None)
        if driver:
            driver.quit()
```

---

## 三、LLM 集成（`llm/`）

### 3.1 `chat.py` — LLM 对话封装

```python
# 位置: appium-mcp-server/llm/chat.py

class Chat:
    """
    LLM 对话管理器，封装 LangChain ChatOpenAI。
    支持 OpenAI、Azure OpenAI、Ollama 等兼容端点。
    """
    
    def __init__(self):
        self.llm = None
    
    def init_llm(self, config: dict):
        """初始化 LLM，从配置读取 API key、model、base_url"""
        self.llm = ChatOpenAI(
            model=config.get("model_name", "gpt-4"),
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            temperature=0.1,
        )
    
    def chat(self, messages: list) -> str:
        """发送消息并返回 LLM 响应"""
        response = self.llm.invoke(messages)
        return response.content
    
    def generate_test_code(self, context: str, instructions: str) -> str:
        """使用 LLM 生成测试代码"""
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Context: {context}\n\nInstructions: {instructions}")
        ]
        return self.chat(messages)
```

### 3.2 `prompt.py` — 系统提示词

```python
# 位置: appium-mcp-server/llm/prompt.py

SYSTEM_PROMPT = """
You are an expert test automation engineer. Your task is to generate 
Python test code using Appium for mobile/desktop app testing.

## Guidelines:
1. Use pytest as the testing framework
2. Use Appium Python Client for automation
3. Follow Page Object Model (POM) pattern
4. Include proper waits and error handling
5. Generate clean, maintainable code

## Code Style:
- Use descriptive variable names
- Add docstrings for test functions
- Include setup and teardown methods
- Use explicit waits instead of sleep()
"""
```

---

## 四、驱动工具（`tools/`）

### 4.1 `appium_driver_tool.py` — 核心驱动工具

```python
# 位置: appium-mcp-server/tools/appium_driver_tool.py

class AppiumDriverTool:
    """
    Appium 驱动核心操作工具。
    封装常见的 UI 操作: 点击、输入、滑动、截图等。
    """
    
    def __init__(self, driver_session_manager, config_manager):
        self.driver_session_manager = driver_session_manager
        self.config_manager = config_manager
    
    async def execute(self, action: str, params: dict) -> dict:
        """
        执行驱动操作。
        
        支持的 action:
        - click: 点击元素
        - input_text: 输入文本
        - swipe: 滑动
        - screenshot: 截图
        - get_page_source: 获取页面源码
        - find_element: 查找元素
        - scroll: 滚动
        - tap: 轻触坐标
        - long_press: 长按
        - back: 返回
        """
        driver = self._get_driver(params.get("session_id"))
        
        if action == "click":
            element = driver.find_element(by=params["by"], value=params["value"])
            element.click()
        
        elif action == "input_text":
            element = driver.find_element(by=params["by"], value=params["value"])
            element.send_keys(params["text"])
        
        elif action == "swipe":
            driver.swipe(
                params["start_x"], params["start_y"],
                params["end_x"], params["end_y"],
                duration=params.get("duration", 500)
            )
        
        elif action == "screenshot":
            screenshot_base64 = driver.get_screenshot_as_base64()
            return {"screenshot": screenshot_base64}
        
        elif action == "get_page_source":
            return {"page_source": driver.page_source}
        
        # ... 更多操作
```

### 4.2 平台特定工具

#### `android_driver_tool.py`

```python
# 位置: appium-mcp-server/tools/android_driver_tool.py

class AndroidDriverTool:
    """
    Android 平台特定的操作工具。
    包括: ADB 命令、应用管理、系统按键等。
    """
    
    async def execute(self, action: str, params: dict) -> dict:
        actions = {
            "start_activity": self._start_activity,
            "press_key": self._press_key,
            "get_toast": self._get_toast_message,
            "adb_command": self._execute_adb,
            "install_app": self._install_app,
            "uninstall_app": self._uninstall_app,
            "get_device_info": self._get_device_info,
        }
        return await actions[action](params)
```

#### `ios_driver_tool.py`

```python
# 位置: appium-mcp-server/tools/ios_driver_tool.py

class IOSDriverTool:
    """
    iOS 平台特定的操作工具。
    包括: 手势、Face ID 模拟、系统操作等。
    """
    
    async def execute(self, action: str, params: dict) -> dict:
        actions = {
            "swipe_gesture": self._swipe_gesture,
            "simulate_face_id": self._simulate_face_id,
            "simulate_touch_id": self._simulate_touch_id,
            "shake": self._shake_device,
            "lock": self._lock_device,
            "unlock": self._unlock_device,
        }
        return await actions[action](params)
```

#### `mac_driver_tool.py`

```python
# 位置: appium-mcp-server/tools/mac_driver_tool.py

class MacDriverTool:
    """
    macOS 桌面应用操作工具。
    基于 Appium Mac2 Driver。
    """
    
    async def execute(self, action: str, params: dict) -> dict:
        actions = {
            "click_menu": self._click_menu_bar,
            "type_shortcut": self._type_shortcut,
            "launch_app": self._launch_application,
            "terminate_app": self._terminate_application,
            "get_window_list": self._get_window_list,
            "focus_window": self._focus_window,
        }
        return await actions[action](params)
```

### 4.3 `config_tool.py` — 配置管理工具

```python
# 位置: appium-mcp-server/tools/config_tool.py

class ConfigTool:
    """
    管理测试配置，包括:
    - Appium 服务器地址
    - 设备/模拟器配置
    - 应用包名/路径
    - BrowserStack 云测试配置
    - LLM API 配置
    """
    
    async def load_config(self, path: str) -> dict:
        """从 JSON 文件加载配置"""
        
    async def get_configuration(self) -> dict:
        """获取当前完整配置"""
        
    async def set_configuration(self, key: str, value: any) -> dict:
        """设置单个配置项"""
```

### 4.4 `gen_code_tool.py` — 代码生成工具

```python
# 位置: appium-mcp-server/tools/gen_code_tool.py

class GenCodeTool:
    """
    基于 UI 操作历史生成测试代码。
    支持生成 Python pytest + Appium 代码。
    """
    
    def __init__(self, chat: Chat):
        self.chat = chat
        self.code_generator = CodeGenerator()
    
    async def generate(self, params: dict) -> dict:
        """
        生成测试代码。
        
        输入: 操作历史 + 页面元素信息
        输出: 完整的 Python 测试文件
        """
        actions_history = params.get("actions", [])
        page_elements = params.get("elements", [])
        test_name = params.get("test_name", "generated_test")
        
        code = self.code_generator.generate(
            actions=actions_history,
            elements=page_elements,
            test_name=test_name,
            llm=self.chat,
        )
        return {"code": code, "file_name": f"test_{test_name}.py"}
```

### 4.5 `verify_tools.py` — 验证工具

```python
# 位置: appium-mcp-server/tools/verify_tools.py

class VerifyTools:
    """
    UI 验证工具集。
    """
    
    async def verify_element(self, params: dict) -> dict:
        """验证元素是否存在、可见、可点击"""
        
    async def verify_text(self, params: dict) -> dict:
        """验证页面文本内容"""
        
    async def verify_screenshot(self, params: dict) -> dict:
        """截图并与基准截图对比"""
        
    async def verify_toast(self, params: dict) -> dict:
        """验证 Android Toast 消息"""
```

---

## 五、工具函数（`utils/`）

### 5.1 `config_manager.py` — 配置管理器

```python
# 位置: appium-mcp-server/utils/config_manager.py

class ConfigManager:
    """
    配置文件管理器。
    加载/保存 JSON 配置，支持合并和默认值。
    """
    
    def __init__(self):
        self.config = {}
        self.default_config = self._load_defaults()
    
    def load(self, path: str) -> dict:
        """从 JSON 文件加载配置"""
        with open(path) as f:
            loaded = json.load(f)
        self.config = {**self.default_config, **loaded}
        return self.config
    
    def get(self, key: str, default=None):
        """获取配置项（支持点号分隔的嵌套 key）"""
        keys = key.split(".")
        value = self.config
        for k in keys:
            value = value.get(k)
            if value is None:
                return default
        return value
    
    def set(self, key: str, value: any):
        """设置配置项"""
        keys = key.split(".")
        target = self.config
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        target[keys[-1]] = value
```

### 5.2 `element_util.py` — 元素工具

```python
# 位置: appium-mcp-server/utils/element_util.py

def serialize_element(element) -> dict:
    """将 Appium WebElement 序列化为字典"""
    return {
        "tag": element.tag_name,
        "text": element.text,
        "location": element.location,
        "size": element.size,
        "attributes": {
            "class": element.get_attribute("class"),
            "id": element.get_attribute("resource-id"),
            "content_desc": element.get_attribute("content-desc"),
            "clickable": element.get_attribute("clickable"),
            "enabled": element.get_attribute("enabled"),
        }
    }
```

### 5.3 `gen_code.py` — 代码生成核心

```python
# 位置: appium-mcp-server/utils/gen_code.py

class CodeGenerator:
    """
    测试代码生成器。
    将 UI 操作序列转换为 Python pytest 代码。
    
    支持两种模式:
    1. 模板模式: 直接根据操作类型生成代码
    2. LLM 模式: 使用 LLM 优化代码质量
    """
    
    def generate(self, actions: list, elements: list, 
                 test_name: str, llm: Chat = None) -> str:
        """生成测试代码"""
        # 生成操作代码
        code_lines = self._generate_imports()
        code_lines += self._generate_test_function(test_name)
        
        for action in actions:
            code_lines.append(self._action_to_code(action))
        
        code_lines += self._generate_teardown()
        
        raw_code = "\n".join(code_lines)
        
        # 如果有 LLM，用 LLM 优化代码
        if llm:
            raw_code = llm.generate_test_code(
                context=raw_code,
                instructions="Optimize this test code, add proper waits and error handling"
            )
        
        return raw_code
    
    def _action_to_code(self, action: dict) -> str:
        """将单个操作转换为代码行"""
        action_type = action["type"]
        
        if action_type == "click":
            return f'    driver.find_element(by=AppiumBy.{action["by"].upper()}, value="{action["value"]}").click()'
        
        elif action_type == "input":
            return f'    driver.find_element(by=AppiumBy.{action["by"].upper()}, value="{action["value"]}").send_keys("{action["text"]}")'
        
        elif action_type == "swipe":
            return f'    driver.swipe({action["start_x"]}, {action["start_y"]}, {action["end_x"]}, {action["end_y"]})'
        
        # ... 更多操作类型
```

### 5.4 `logger.py` — 日志

```python
# 位置: appium-mcp-server/utils/logger.py
import logging

def setup_logger(name: str = "appium-mcp-server", level=logging.INFO):
    logger = logging.getLogger(name)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(handler)
    logger.setLevel(level)
    return logger
```

### 5.5 `response_format.py` — 响应格式化

```python
# 位置: appium-mcp-server/utils/response_format.py

def format_response(success: bool, data: any = None, 
                    error: str = None, message: str = None) -> dict:
    """统一响应格式"""
    return {
        "success": success,
        "data": data,
        "error": error,
        "message": message,
    }
```

---

## 六、核心数据流图

```
AI Agent (Copilot/Claude)
        │
        │ MCP Protocol (stdio JSON-RPC)
        ▼
┌──────────────────────────────────────┐
│         simple_server.py             │
│                                      │
│  list_tools() → 返回 15+ 工具定义     │
│  call_tool()  → 工具路由分发          │
└──────────────────────────────────────┘
        │
        ├── config_tool ──────► ConfigManager ──► JSON 配置
        │
        ├── android/ios/mac_driver_tool
        │       │
        │       └──► DriverSessionManager ──► Appium Driver
        │               │
        │               └──► 实际设备/模拟器
        │
        ├── verify_tools ───► 验证元素/文本/截图
        │
        └── gen_code_tool ──► Chat (LLM) + CodeGenerator
                │
                └──► 生成 Python 测试代码
```

## 七、工具列表汇总

| 工具名 | 分类 | 功能 |
|--------|------|------|
| `load_config` | 配置 | 加载 JSON 配置文件 |
| `get_configuration` | 配置 | 获取当前配置 |
| `set_configuration` | 配置 | 修改配置项 |
| `create_driver_session` | 会话 | 创建 Appium 驱动会话 |
| `delete_driver_session` | 会话 | 删除驱动会话 |
| `android_driver_tool` | 平台 | Android 设备操作 |
| `ios_driver_tool` | 平台 | iOS 设备操作 |
| `mac_driver_tool` | 平台 | macOS 桌面操作 |
| `verify_element` | 验证 | 验证元素存在/可见 |
| `verify_text` | 验证 | 验证文本内容 |
| `verify_screenshot` | 验证 | 截图对比验证 |
| `verify_toast` | 验证 | Android Toast 验证 |
| `gen_code_tool` | 生成 | AI 生成测试代码 |
