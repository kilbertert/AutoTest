import asyncio
from trendpower_tui.mcp.config_loader import load_configured_servers
from trendpower.community.mcp import MCPManager

async def main():
    cfgs = load_configured_servers()
    print('configs', [(c.name, c.transport, c.command) for c in cfgs])
    mgr = MCPManager(cfgs)
    try:
        tools = await mgr.connect_all()
        print('tools', len(tools), [t.name for t in tools[:20]])
        print('status', mgr.status())
    finally:
        await mgr.aclose()

asyncio.run(main())
