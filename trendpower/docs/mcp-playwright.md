# 用 Playwright 为例：怎么装一个 MCP server（含浏览器依赖）

这篇文档以 **Playwright MCP** 为案例，手把手讲清楚在 trendpower 里挂一个 MCP
server 的完整过程，**重点说明除了配置文件之外还需要装什么**（运行器、浏览器
内核），以及运行后会在磁盘上留下哪些东西。

> 想看 MCP 的协议层 / 设计原理，看 [`docs/mcp.md`](./mcp.md)。
> 这篇只讲「Playwright 这个具体 server 怎么从零跑起来」。

---

## 0. Playwright MCP 是什么、为什么效果直观

`@playwright/mcp` 是官方出的浏览器自动化 MCP server。连上之后，agent 多出一批
`playwright__*` 工具（打开网页、点击、填表单、截图、抓取页面结构……）。

它"效果直观"是因为：你让 agent 干活时它会**真的拉起一个 Chromium 浏览器**去访问
页面，并把页面快照 / 截图存到磁盘——肉眼可见，适合用来验证 MCP 集成是否真的通了。

---

## 1. 需要预先装的东西（关键！）

挂 Playwright MCP **不止是写一段 JSON**，它有两层外部依赖：

| 依赖 | 作用 | 怎么确认装了 | 怎么装 |
|---|---|---|---|
| **Node.js / npx** | 拉起 server 进程的运行器 | `npx -v` 能打印版本 | 装 [Node.js](https://nodejs.org)（自带 `npx`） |
| **Chromium 浏览器内核** | server 真正驱动的浏览器 | 见下方第 3 节 | 通常首次运行自动下载；也可手动 `npx playwright install chromium` |

第一层（Node）和别的 npm 系 MCP server 一样。**第二层（浏览器）是 Playwright
特有的**——这就是为什么单独写一篇文档：很多人配好 JSON 后报 "browser not found"，
原因就是浏览器内核没下载。

> **Linux 还有第三层依赖**：Chromium 在 Linux 上需要一批系统级共享库
> （libnss3、libgbm、libasound2 等），裸服务器 / Docker / WSL 上默认没装。
> 用 `npx playwright install --with-deps chromium` 一并装上（见第 3 节）。
> macOS / Windows 不需要这一步。

本机当前状态（供参考）：

```text
node v24.16.0 / npx 11.13.0      ✅ 运行器就绪
@playwright/mcp@0.0.75           ✅ 已被 npx 缓存
~/Library/Caches/ms-playwright/  ✅ 浏览器已下载（见第 3 节）
```

---

## 2. 写配置

trendpower 只读一个文件：`~/.trendpower/mcp_servers.json`（设了 `TRENDPOWER_HOME` 则读
`$TRENDPOWER_HOME/mcp_servers.json`）。加上 Playwright 这一条：

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

说明：

- `command` + `args` 就是「在终端会怎么敲这条命令」：`npx -y @playwright/mcp@latest`。
- 没写 `transport`，有 `command` 时默认按 `stdio` 处理（trendpower 自己拉起子进程）。
- `-y` 让 `npx` 在包没缓存时自动下载、不交互询问。
- key `playwright` 是逻辑名，会变成工具名前缀（见第 6 节）。

> ⚠️ 既然走 `stdio`，`npx` 必须在 `PATH` 里能被 trendpower 进程找到。装完 Node 后
> 新开一个终端再启动 trendpower 最保险。

---

## 3. 浏览器内核：那个"我帮你装的浏览器"

Playwright **不用系统里的 Chrome/Safari**，它自带一套钉死版本的浏览器内核，下载到
用户缓存目录：

- macOS: `~/Library/Caches/ms-playwright/`
- Linux: `~/.cache/ms-playwright/`
- Windows: `%USERPROFILE%\AppData\Local\ms-playwright\`

本机里实际下载下来的内容（占几百 MB，正常）：

```text
~/Library/Caches/ms-playwright/
├── chromium-1223/                 # 完整 Chromium，约 341 MB（有头模式用）
├── chromium_headless_shell-1223/  # headless 专用精简内核，约 190 MB
└── ffmpeg-1011/                   # 录制视频用
```

这就是"浏览器那个东西"。**它是一次性下载、全局共享的**，不在 trendpower 仓库里，也不
占项目空间。

什么时候会触发下载：

- 多数情况下，**第一次让 agent 真正打开网页时**，`@playwright/mcp` 会自动下载缺
  的内核。
- 如果遇到报错（典型信息：`Executable doesn't exist` / `browserType.launch:
  ... please run npx playwright install`），手动补一条即可：

  ```bash
  npx playwright install chromium
  ```

  只需要装 chromium 即可，不必装 firefox/webkit 全家桶。

**按系统区分的安装命令：**

- **macOS / Windows**：上面那条 `npx playwright install chromium` 就够了，浏览器
  内核是自包含的。
- **Linux（含 WSL / Docker / 裸服务器）**：还要装系统共享库，否则浏览器能下载却
  起不来。用下面这条一次搞定内核 + 系统依赖：

  ```bash
  npx playwright install --with-deps chromium
  ```

  `--with-deps` 在 Debian/Ubuntu 上会调 `apt` 装依赖（可能要 `sudo`）。其它发行版
  （Arch/Fedora/Alpine）`install-deps` 不一定覆盖，需按报错里缺的库名手动装。

---

## 4. 让 trendpower 连上并验证

1. **启动 / 重启 TUI**：`trendpower`。启动时并行连接所有 server，banner 会出现类似
   `MCP: 1 server(s) connected (N tool(s))` 的行。
   - 已经开着 TUI 的话，敲 `/mcp reload` 重连；但要让**正在进行的 agent 会话**看到
     新 server，**重启 TUI** 最稳妥（理由见 `docs/mcp.md`）。
2. **看状态**：敲 `/mcp list`，应出现：

   ```text
   | name       | transport | status    | tools | error |
   |------------|-----------|-----------|------:|-------|
   | playwright | stdio     | connected |    N  |       |
   ```

   - `connected` 且工具数 > 0 → 成功。
   - `failed` → 看 `error` 列对照第 7 节排错。

---

## 5. 跑一个能肉眼看到效果的例子

连上后直接用自然语言让 agent 干活，比如：

> 用 playwright 打开 https://example.com，告诉我页面标题，并截一张图。

agent 会自动挑 `playwright__*` 工具、拉起 Chromium、访问页面、返回标题和截图路径。
这就是"效果直观"的地方——它真的开了浏览器。

---

## 6. 运行后会在项目里多出什么：`.playwright-mcp/`

Playwright MCP 会在**它的工作目录**（即你启动 trendpower 的当前目录）下创建一个
`.playwright-mcp/` 文件夹，存放每次会话的产物：

```text
.playwright-mcp/
├── console-<时间戳>.log     # 浏览器 console 输出
└── page-<时间戳>.yml        # 抓到的页面结构快照
```

这些是**运行时垃圾**，不该进版本库。本仓库已把它加进 `.gitignore`：

```gitignore
# Playwright MCP 运行时产物（页面快照 / console 日志）
.playwright-mcp/
```

如果你在别的目录跑 trendpower，同样会在那里生成一个，按需删除即可。

---

## 7. 排错速查

| 现象 | 原因 / 解法 |
|---|---|
| `/mcp list` 里 `playwright` 是 `failed`，error 写 `command not found` / `ENOENT` | `npx` 没装或不在 `PATH`。先在终端单独跑 `npx -y @playwright/mcp@latest` 验证。 |
| agent 调用工具时报 `Executable doesn't exist` / `please run npx playwright install` | 浏览器内核没下载。跑 `npx playwright install chromium`。 |
| **（Linux）** 内核已下载，但启动报 `error while loading shared libraries` / 缺 `libnss3` 等 | 缺系统依赖。跑 `npx playwright install --with-deps chromium`（见第 3 节）。 |
| 第一次连接很慢 / 卡住 | `npx` 在下载 `@playwright/mcp` 包或浏览器内核（几百 MB），等它下完；之后会走缓存。 |
| 启动 banner 完全没有 MCP 那一行 | 配置文件路径不对。`/mcp` 看真实路径确认（也可查 `TRENDPOWER_HOME` 环境变量）。 |
| 改了 JSON 没生效 | 没重连。`/mcp reload`；要让 live agent 看到则重启 TUI。 |
| JSON 整个没生效且有 warning | 语法错。校验：macOS/Linux 用 `python3 -m json.tool <配置路径>`，Windows 用 `python -m json.tool <配置路径>`。 |

---

## 8. 一句话总结依赖关系

```text
你写的 JSON  ──告诉 trendpower 怎么拉起──▶  npx @playwright/mcp  ──首次访问网页时拉起──▶  Chromium 内核
   (配置)                                  (Node 运行器装)              (~/Library/Caches/ms-playwright，几百 MB)
```

三层缺一不可：**配置文件**、**Node/npx 运行器**、**Chromium 浏览器内核**。
Playwright 的特殊之处只在第三层——别的 npm 系 server（如 filesystem、github）只要前两层就够了。

---

## 9. 跨平台说明（macOS / Linux / Windows）

本文步骤三大系统通用，差异集中在下面这张表：

| 项 | macOS | Linux | Windows |
|---|---|---|---|
| 配置文件路径 | `~/.trendpower/mcp_servers.json` | 同左 | `C:\Users\<你>\.trendpower\mcp_servers.json` |
| `npx` 配置是否要改 | 否 | 否 | **否**——MCP SDK 自动把 `npx` 解析为 `npx.cmd` |
| 装浏览器 | `npx playwright install chromium` | `npx playwright install --with-deps chromium`（需系统库，可能要 `sudo`） | `npx playwright install chromium` |
| 浏览器缓存目录 | `~/Library/Caches/ms-playwright/` | `~/.cache/ms-playwright/` | `%USERPROFILE%\AppData\Local\ms-playwright\` |
| 校验 JSON 语法 | `python3 -m json.tool …` | `python3 -m json.tool …` | `python -m json.tool …` |

要点：

- **路径写法**：文中 `~/.trendpower/...` 是 macOS/Linux 习惯写法。trendpower 内部用
  `Path.home()` 解析，Windows 上自动落到 `C:\Users\<你>\.trendpower\`，无需手动改。
- **Node/npx 配置完全一致**：三个系统的 `mcpServers` 配置 JSON 一字不差，
  Windows 不用把 `npx` 改成 `npx.cmd`（SDK 已处理）。
- **唯一真正的系统差异在「装浏览器」**：只有 Linux 需要 `--with-deps` 补系统库；
  macOS/Windows 浏览器内核是自包含的。
- **WSL 按 Linux 处理**（包括 `--with-deps`）。
