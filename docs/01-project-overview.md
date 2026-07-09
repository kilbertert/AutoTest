# AutoGenesis — AI 驱动的跨平台自动化测试框架

## 项目定位

AutoGenesis 是一个基于 **MCP (Model Context Protocol)** 的 AI 驱动自动化测试框架，由 Microsoft 开发。它支持多个平台的测试自动化，包括：

- **Windows 桌面应用**（基于 pywinauto）
- **macOS 桌面应用**（基于 Appium）
- **iOS/Android 移动应用**（基于 Appium + BrowserStack）

此外，它还提供了一个 **VS Code 扩展**（BDD AI Toolkit），将 AI 能力集成到开发工作流中，支持 BDD（行为驱动开发）测试的录制、回放和 AI 辅助生成。

## 核心能力

1. **MCP 服务器**：基于 Model Context Protocol 的标准服务器，使 AI Agent（如 GitHub Copilot）能够直接操控桌面和移动应用
2. **AI 辅助测试脚本生成**：通过 LLM 分析 UI 元素并自动生成测试代码
3. **跨平台驱动支持**：
   - Windows: pywinauto（UIA/MSAA 后端）
   - macOS: Appium Mac2 Driver
   - Android: Appium UiAutomator2 Driver
   - iOS: Appium XCUITest Driver
4. **BDD 工作流**：VS Code 扩展支持 Feature 文件编辑、Step 匹配、自动化状态可视化
5. **GitHub Copilot 集成**：通过 MCP 协议让 Copilot 直接执行 UI 操作

## 技术栈

| 技术 | 用途 | 子项目 |
|------|------|--------|
| Python 3.12+ | MCP 服务器主语言 | appium-mcp-server, pywinauto-mcp-server |
| TypeScript | VS Code 扩展 | bdd_ai_toolkit |
| MCP (Model Context Protocol) | AI Agent 与工具间通信协议 | 所有子项目 |
| Appium 3.x | 移动端/桌面端 UI 自动化 | appium-mcp-server |
| pywinauto | Windows 桌面 UI 自动化 | pywinauto-mcp-server |
| LangChain | LLM 集成 | 所有 MCP 服务器 |
| Vite + Tailwind CSS | 文档站点 | docs/ |
| Behave (Python BDD) | BDD 测试示例 | behave-demo |

## 项目结构（Monorepo）

```
AutoGenesis/
├── appium-mcp-server/          # Appium MCP 服务器（Python）
│   ├── simple_server.py        # MCP 服务器入口（stdio 传输）
│   ├── simple_client.py        # MCP 客户端（用于测试）
│   ├── driver_session.py       # Appium 驱动会话管理
│   ├── pyproject.toml          # Python 项目配置
│   ├── llm/                    # LLM 集成模块
│   │   ├── chat.py             # LLM 对话封装
│   │   └── prompt.py           # 系统提示词
│   ├── tools/                  # MCP 工具实现
│   │   ├── appium_driver_tool.py    # Appium 驱动核心工具
│   │   ├── android_driver_tool.py   # Android 驱动工具
│   │   ├── ios_driver_tool.py       # iOS 驱动工具
│   │   ├── mac_driver_tool.py       # macOS 驱动工具
│   │   ├── config_tool.py           # 配置管理工具
│   │   ├── gen_code_tool.py         # 代码生成工具
│   │   └── verify_tools.py          # 验证工具
│   ├── utils/                  # 工具函数
│   │   ├── config_manager.py   # 配置管理器
│   │   ├── element_util.py     # UI 元素工具
│   │   ├── gen_code.py         # 代码生成核心
│   │   ├── logger.py           # 日志
│   │   └── response_format.py  # 响应格式化
│   └── conf/                   # 配置文件
│       └── appium_conf.template.json
│
├── pywinauto-mcp-server/       # Windows 桌面自动化 MCP 服务器（Python）
│   ├── simple_server.py        # MCP 服务器入口
│   ├── simple_client.py        # MCP 客户端
│   ├── driver_session.py       # pywinauto 驱动会话管理
│   ├── llm/                    # LLM 集成
│   │   ├── chat.py
│   │   └── prompt.py
│   ├── tools/                  # MCP 工具
│   │   ├── pywinauto_driver_tool.py  # Windows 驱动核心工具
│   │   ├── gen_code_tool.py          # 代码生成
│   │   └── verify_tools.py           # 验证工具
│   ├── utils/                  # 工具函数
│   │   ├── config_manager.py
│   │   ├── element_util.py
│   │   ├── gen_code.py
│   │   ├── logger.py
│   │   └── response_format.py
│   └── conf/
│       └── pywinauto_conf.json
│
├── bdd_ai_toolkit/             # VS Code 扩展（TypeScript）
│   ├── package.json            # 扩展配置
│   ├── src/
│   │   ├── extension.ts        # 扩展入口
│   │   ├── globalState.ts      # 全局状态管理
│   │   ├── constants/
│   │   │   └── prompts.ts      # LLM 提示词
│   │   ├── tools/              # 工具模块
│   │   │   ├── testCaseGenerator.ts          # 测试用例生成器
│   │   │   ├── naturalLanguageTaskExecutor.ts # 自然语言任务执行
│   │   │   ├── testCaseWorkflowPatterns.ts    # 工作流模式
│   │   │   ├── figmaExtractor.ts             # Figma 设计提取
│   │   │   └── xmindParser.ts               # XMind 思维导图解析
│   │   ├── bdd-feature-support/ # BDD Feature 支持
│   │   │   ├── core/
│   │   │   │   ├── gherkin/    # Gherkin 语法解析
│   │   │   │   └── matching/   # Step 匹配引擎
│   │   │   ├── providers/      # VS Code UI Provider
│   │   │   ├── services/       # 业务服务
│   │   │   ├── cache/          # 缓存管理
│   │   │   └── utils/          # 工具函数
│   │   └── setup/              # 环境安装向导
│   └── resources/              # Webview 资源
│
├── behave-demo/                # BDD 示例项目
│   └── features/               # Feature 文件和 Step 定义
│
└── docs/                       # VitePress 文档站点
    ├── package.json
    ├── vite.config.ts
    └── src/
```

## 核心工作流

### 1. MCP 工具调用流程

```
AI Agent (Copilot/Claude)
    │
    ▼
MCP Client (stdio/HTTP)
    │
    ▼
MCP Server (simple_server.py)
    │
    ├──► list_tools()        → 返回可用工具列表
    ├──► call_tool(name, args) → 执行具体工具
    │       │
    │       ├── driver_tool   → 操控 UI（点击/输入/滑动/截图）
    │       ├── gen_code_tool → AI 生成测试脚本
    │       ├── config_tool   → 管理设备/应用配置
    │       └── verify_tools  → 验证 UI 元素
    │
    └──► 返回 MCP Response
```

### 2. BDD 工作流（VS Code 扩展）

```
用户编辑 .feature 文件
    │
    ▼
Gherkin 解析器 → 提取 Scenario / Steps
    │
    ▼
Step 匹配引擎 → 查找 Step Definition
    │
    ▼
自动化状态服务 → 显示匹配状态
    │
    ▼
Copilot 集成 → AI 生成/补全 Step 代码
```

## 两个 MCP 服务器对比

| 维度 | appium-mcp-server | pywinauto-mcp-server |
|------|-------------------|---------------------|
| 目标平台 | macOS / iOS / Android | Windows |
| 底层框架 | Appium 3.x | pywinauto |
| 支持后端 | Mac2, XCUITest, UiAutomator2 | UIA, MSAA |
| 云端测试 | BrowserStack 集成 | 不支持 |
| 语言 | Python | Python |
