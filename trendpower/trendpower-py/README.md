# trendpower

`trendpower` 是一个用 Python 实现的 **ReAct 风格** agent loop 库。TUI 层不在这个包里——这是一个你可以嵌入自己程序（脚本、FastAPI 服务、Textual 应用、Jupyter notebook 等）的核心库。

## 目录结构

```
trendpower/
├── foundation/        # Messages, Models, Tools — 核心原语
├── agent/             # ReAct agent loop、中间件、todos、skills
├── coding/            # 编码专用 agent + 工具（bash、文件操作、patch、grep……）
└── community/         # ModelProvider 实现（openai、anthropic）
```

## 安装

> 大多数用户应该装 [`trendpower-tui`](../trendpower-tui/)（它会自动把 `trendpower` 一起拉进来）。完整的安装路径（含 uv 全局命令、editable 开发模式）见仓库根 [`README.md`](../README.md)。

直接使用核心库（不要 TUI）：

```bash
# editable，方便改源码
pip install -e .

# 或用 uv
uv pip install -e .
```

## 最小示例

```python
import asyncio
from trendpower.foundation import Model
from trendpower.community.openai import OpenAIModelProvider
from trendpower.coding import create_coding_agent

async def main():
    provider = OpenAIModelProvider()  # 读取 OPENAI_API_KEY
    model = Model("gpt-4o-mini", provider)
    agent = await create_coding_agent(model=model)
    async for event in agent.stream({
        "role": "user",
        "content": [{"type": "text", "text": "列出当前目录下的文件。"}],
    }):
        print(event)

asyncio.run(main())
```

## 接入 MCP server

`trendpower.community.mcp` 模块把 [Model Context Protocol](https://modelcontextprotocol.io) server 暴露成普通的 trendpower `Tool`。三种传输方式（stdio / sse / streamable_http）共用一个接口：

```python
import asyncio
from trendpower.community.mcp import MCPManager, load_servers_from_dict
from trendpower.coding import create_coding_agent
from trendpower.foundation import Model
from trendpower.community.openai import OpenAIModelProvider

async def main():
    cfgs = load_servers_from_dict({
        "mcpServers": {
            "fs": {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            },
            "company": {
                "transport": "streamable_http",
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer ${COMPANY_API_KEY}"},
            },
        }
    })
    mgr = MCPManager(cfgs)
    try:
        tools = await mgr.connect_all()        # list[Tool]，已加 servername__ 前缀
        agent = await create_coding_agent(
            model=Model("gpt-4o-mini", OpenAIModelProvider()),
            extra_tools=tools,                 # 远程工具就这样喂给 agent
        )
        # ... agent.stream(...) ...
    finally:
        await mgr.aclose()

asyncio.run(main())
```

每个工具的 invoke 是一个绑定到 `MCPSession` 的闭包，agent loop 不知道也不关心它来自远程。错误隔离开箱即用：某个 server 起不来不会影响其他 server。配置文件格式（mirrors Claude Desktop）、`MCPToolset` / `MCPManager` API 细节、`/mcp` slash 命令、扩展指南见仓库根 [`docs/mcp.md`](../docs/mcp.md)。

## 技术说明

- API 风格：**async-first**，使用 `AsyncGenerator`。
- 工具参数 schema 使用 **pydantic**。MCP 工具走 `FunctionTool.raw_input_schema` 旁路，直接复用 server 给的 JSON Schema。
- 文件操作使用 **pathlib + aiofiles**。
- 子进程使用 **asyncio.create_subprocess_exec**。
- 取消使用自定义 `AbortSignal` 类。
