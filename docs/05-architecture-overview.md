# AutoGenesis 架构总览

## 系统全景图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           AutoGenesis                                    │
│                    AI 驱动的跨平台自动化测试框架                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     VS Code (IDE Layer)                          │   │
│  │                                                                   │   │
│  │  ┌──────────────────────────────────────────────────────────┐   │   │
│  │  │              BDD AI Toolkit (Extension)                    │   │   │
│  │  │                                                           │   │   │
│  │  │  ┌──────────┐ ┌──────────────┐ ┌─────────────────────┐   │   │   │
│  │  │  │ Gherkin  │ │ Step         │ │ Test Generation     │   │   │   │
│  │  │  │ Parser   │ │ Matcher      │ │ (Figma/XMind/NL)    │   │   │   │
│  │  │  └──────────┘ └──────────────┘ └─────────────────────┘   │   │   │
│  │  │                                                           │   │   │
│  │  │  ┌──────────────────────────────────────────────────┐     │   │   │
│  │  │  │         CopilotIntegrationService                 │     │   │   │
│  │  │  │    (VS Code LM API → GitHub Copilot)              │     │   │   │
│  │  │  └──────────────────────┬───────────────────────────┘     │   │   │
│  │  └─────────────────────────┼─────────────────────────────────┘   │   │
│  └────────────────────────────┼────────────────────────────────────┘   │
│                               │                                         │
│                    MCP Protocol (JSON-RPC)                               │
│                               │                                         │
│          ┌────────────────────┼────────────────────┐                    │
│          │                    │                    │                    │
│          ▼                    ▼                    ▼                    │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐              │
│  │ pywinauto     │  │ appium        │  │ appium        │              │
│  │ MCP Server    │  │ MCP Server    │  │ MCP Server    │              │
│  │ (Windows)     │  │ (macOS/iOS/   │  │ (Android)     │              │
│  │               │  │  Android)     │  │               │              │
│  │ ┌───────────┐ │  │ ┌───────────┐ │  │ ┌───────────┐ │              │
│  │ │DriverTool │ │  │ │DriverTool │ │  │ │DriverTool │ │              │
│  │ │GenCode    │ │  │ │GenCode    │ │  │ │GenCode    │ │              │
│  │ │Verify     │ │  │ │Verify     │ │  │ │Verify     │ │              │
│  │ │Config     │ │  │ │Config     │ │  │ │Config     │ │              │
│  │ │LLM/Chat   │ │  │ │LLM/Chat   │ │  │ │LLM/Chat   │ │              │
│  │ └─────┬─────┘ │  │ └─────┬─────┘ │  │ └─────┬─────┘ │              │
│  └───────┼───────┘  └───────┼───────┘  └───────┼───────┘              │
│          │                  │                  │                       │
│          ▼                  ▼                  ▼                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐              │
│  │ pywinauto     │  │ Appium Mac2   │  │ Appium        │              │
│  │ (UIA/MSAA)    │  │ Driver        │  │ UiAutomator2  │              │
│  │               │  │               │  │ / XCUITest    │              │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘              │
│          │                  │                  │                       │
│          ▼                  ▼                  ▼                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐              │
│  │ Windows 桌面  │  │ macOS 桌面    │  │ iOS / Android │              │
│  │ 应用程序      │  │ 应用程序      │  │ 移动应用      │              │
│  └───────────────┘  └───────────────┘  └───────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## 模块依赖图

```
bdd_ai_toolkit (VS Code Extension)
    │
    ├──► CopilotIntegrationService ──► VS Code LM API
    │       │
    │       └──► MCP Protocol ──► MCP Servers
    │
    ├──► FeatureParser ──► GherkinDocument
    ├──► StepMatcher ──► StepDefinition[]
    ├──► TestCaseGenerator ──► LLM (Copilot)
    ├──► NaturalLanguageTaskExecutor ──► LLM + MCP
    └──► SetupWebViewProvider ──► MCPServerManager

pywinauto-mcp-server (Python)
    │
    ├──► simple_server.py ──► MCP stdio Server
    │       │
    │       ├──► PywinautoDriverTool ──► pywinauto Application
    │       ├──► GenCodeTool ──► CodeGenerator + Chat (LLM)
    │       ├──► VerifyTools ──► pywinauto Element
    │       └──► ConfigManager ──► JSON config
    │
    └──► Chat (LangChain) ──► OpenAI / Azure / Ollama

appium-mcp-server (Python)
    │
    ├──► simple_server.py ──► MCP stdio Server
    │       │
    │       ├──► AndroidDriverTool ──► Appium UiAutomator2
    │       ├──► IOSDriverTool ──► Appium XCUITest
    │       ├──► MacDriverTool ──► Appium Mac2
    │       ├──► GenCodeTool ──► CodeGenerator + Chat (LLM)
    │       ├──► VerifyTools ──► Appium Element
    │       └──► ConfigManager ──► JSON config
    │
    └──► Chat (LangChain) ──► OpenAI / Azure / Ollama
```

## 核心数据流

### 1. AI Agent 操控 UI 流程

```
AI Agent (Copilot/Claude)
    │
    │ "Click the login button"
    │
    ▼
MCP Protocol (JSON-RPC over stdio)
    │
    │ {
    │   "method": "tools/call",
    │   "params": {
    │     "name": "pywinauto_driver_tool",
    │     "arguments": {
    │       "action": "click",
    │       "by": "automation_id",
    │       "value": "btnLogin"
    │     }
    │   }
    │ }
    │
    ▼
MCP Server (simple_server.py)
    │
    │ call_tool("pywinauto_driver_tool", arguments)
    │
    ▼
PywinautoDriverTool.execute("click", params)
    │
    │ driver = session_manager.get_session(session_id)
    │ element = driver.window.child_window(auto_id="btnLogin")
    │ element.click()
    │
    ▼
pywinauto → Windows UI Automation API → 实际点击按钮
    │
    ▼
返回结果
    │
    │ { "success": true, "message": "Element clicked: btnLogin" }
    │
    ▼
AI Agent 收到结果，继续下一步操作
```

### 2. BDD 测试生成流程

```
用户操作
    │
    ├── 方式1: 手动编写 .feature 文件
    │       │
    │       ▼
    │   FeatureParser → GherkinDocument
    │       │
    │       ▼
    │   StepMatcher → 匹配/高亮
    │       │
    │       └──► 未匹配 → Copilot 生成 Step Definition
    │
    ├── 方式2: AI 生成 (naturalLanguageTaskExecutor)
    │       │
    │       ▼
    │   用户描述 → LLM → Gherkin Feature 文件
    │
    ├── 方式3: Figma 导入
    │       │
    │       ▼
    │   Figma JSON → UI Element Tree → LLM → Gherkin
    │
    └── 方式4: XMind 导入
            │
            ▼
        XMind 思维导图 → Feature 层级结构 → Gherkin
```

### 3. 环境安装流程

```
用户打开 VS Code
    │
    ▼
BDD AI Toolkit 激活
    │
    ├── 检测 Python 环境
    │       ├── Python 3.12+ 已安装? → 继续
    │       └── 未安装 → 提示安装
    │
    ├── 检测平台
    │       ├── Windows → pywinauto-mcp-server
    │       ├── macOS → appium-mcp-server (Mac2)
    │       └── Linux → 不支持桌面自动化
    │
    ├── 安装 MCP Server 依赖
    │       ├── pip install / uv sync
    │       └── 配置 Appium (移动端)
    │
    └── 配置 MCP 客户端
            └── VS Code settings.json
```

## 架构模式

### 1. MCP Server 架构模式（两个 Python 服务器共享）

```
simple_server.py
    │
    ├── class App
    │   ├── __init__(): 初始化 DriverSessionManager, ConfigManager, Chat
    │   └── serve(): 启动 MCP stdio 服务器
    │
    ├── list_tools(): 返回所有可用工具的定义（name, description, parameters）
    │
    └── call_tool(name, arguments): 路由到具体工具处理函数
            │
            ├── config tools → ConfigTool
            ├── driver tools → PlatformDriverTool
            ├── verify tools → VerifyTools
            └── gen code tools → GenCodeTool
```

### 2. VS Code Extension 架构模式

```
extension.ts (activate)
    │
    ├── 初始化 GlobalState
    ├── 激活 FeatureSupport (Gherkin/Matching)
    ├── 激活 Setup (环境安装)
    └── 注册 Commands
            │
            ├── generateTestCase
            ├── executeNaturalLanguageTask
            ├── generateFromFigma
            ├── generateFromXMind
            └── openSetupWizard
```

## 技术决策总结

| 决策 | 选择 | 原因 |
|------|------|------|
| AI Agent 协议 | MCP (Model Context Protocol) | 标准化的 AI-工具通信协议，Copilot 原生支持 |
| MCP 传输 | stdio (JSON-RPC) | 简单可靠，无需网络配置 |
| Windows 自动化 | pywinauto (UIA backend) | Windows 原生 API，稳定可靠 |
| 移动/桌面自动化 | Appium 3.x | 跨平台标准，支持多后端 |
| LLM 集成 | LangChain ChatOpenAI | 统一接口，支持多种 LLM 后端 |
| VS Code 扩展 | TypeScript | VS Code 原生支持 |
| MCP Server | Python | pywinauto/Appium 的 Python 生态 |
| 配置存储 | JSON 文件 | 简单、可版本控制 |
| 包管理 (Python) | uv | 快速、现代 |
| 文档站点 | VitePress | Markdown 驱动，易于维护 |
