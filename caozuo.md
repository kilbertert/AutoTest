1.2 其他公司电脑（每台都要做）

1.2.1 安装 Python 3.10+

1. 打开浏览器访问 https://www.python.org/downloads/windows/
2. 下载 Python 3.10.x 或 3.11.x（必须是 64-bit）
3. 双击安装包，关键勾选：
  - ☑ Add Python 3.x to PATH （最底部）
  - ☑ Install launcher for all users
4. 点 Install Now

验证安装（开 PowerShell 或 cmd）：
python --version
where python
应该显示 Python 3.10.x 或 3.11.x

1.2.2 安装 Git for Windows

1. 访问 https://git-scm.com/download/win
2. 下载 64-bit Git for Windows Setup
3. 双击安装，全部用默认选项一路 Next

验证：
git --version

1.2.3 安装 UV（推荐，比 pip 快 10-100x）

打开 PowerShell（管理员）：
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

验证：
uv --version

1.2.4 Clone 代码仓库

cd D:\workspace\project\auto-test
git clone https://github.com/kilbertert/AutoTest.git

（如果路径已存在或者你想换目录，把 D:\workspace\project\auto-test 换成你想放的位置）

已有代码的情况：
cd D:\workspace\project\auto-test\AutoGenesis
git pull

1.2.5 安装 Python 依赖

推荐方式（用 uv，10 秒）：
cd D:\workspace\project\auto-test\AutoGenesis
uv sync --all-packages

或者手动装（5-10 分钟）：
cd D:\workspace\project\auto-test\AutoGenesis
pip install openai anthropic pydantic aiofiles python-frontmatter

1.2.6 安装 Microsoft Edge（如果电脑上没有）

chrome-devtools-mcp 需要 Edge（不能用 Chrome 替代）：
1. 访问 https://www.microsoft.com/edge/download
2. 下载 Edge for Business（稳定版）
3. 安装

验证：
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --version

1.2.7 配置 MCP 服务器（每台机器都要做）

编辑 C:\Users\<用户名>\.trendpower\mcp_servers.json：

如果 ~/.trendpower/ 目录不存在，先创建：
mkdir C:\Users\%USERNAME%\.trendpower

写入内容（用记事本或 PowerShell）：

{
  "mcpServers": {
    "pywinauto": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "D:\\workspace\\project\\auto-test\\AutoGenesis\\pywinauto-mcp-server",
        "python",
        "D:\\workspace\\project\\auto-test\\AutoGenesis\\pywinauto-mcp-server\\simple_server.py",
        "--transport",
        "stdio",
        "--app",
        "edge"
      ],
      "cwd": "D:\\workspace\\project\\auto-test\\AutoGenesis\\pywinauto-mcp-server",
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    },
    "api-mcp": {
      "transport": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--project",
        "D:\\workspace\\project\\auto-test\\AutoGenesis\\api-mcp-server",
        "python",
        "D:\\workspace\\project\\auto-test\\AutoGenesis\\api-mcp-server\\simple_server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    },
    "apifox-mcp": {
      "transport": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--project",
        "D:/workspace/project/auto-test/AutoGenesis/apifox-mcp-server",
        "python",
        "D:/workspace/project/auto-test/AutoGenesis/apifox-mcp-server/simple_server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "APIFOX_ACCESS_TOKEN": "<团队共享的 apifox token>",
        "APIFOX_PROJECT_ID": "7393358",
        "APIFOX_DEFAULT_ENVIRONMENT_ID": ""
      }
    },
    "chrome-devtools": {
      "command": "npx",
      "args": [
        "-y",
        "chrome-devtools-mcp@latest",
        "--executablePath",
        "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        "--userDataDir",
        "C:\\Users\\<用户名>\\.trendpower\\qumall-profile",
        "--no-category-performance"
      ]
    },
    "excelio": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "D:/workspace/project/auto-test/AutoGenesis/excelio-mcp-server",
        "python",
        "D:/workspace/project/auto-test/AutoGenesis/excelio-mcp-server/simple_server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}

⚠️ 替换占位符：
- 把所有 <用户名> 替换成你自己的 Windows 用户名（如 admin）
- 把所有 D:\workspace\project\auto-test\AutoGenesis 替换成你代码实际安装路径
- 把 APIFOX_ACCESS_TOKEN 填入真实的 token（或删除 apifox-mcp 整段如果不需要）

最快生成方法（PowerShell）：
$content = Get-Content "D:\workspace\project\auto-test\AutoGenesis\qumall-pool\mcp_config_template.json" -Raw
$content = $content -replace '<USERNAME>', $env:USERNAME
Set-Content "$env:USERPROFILE\.trendpower\mcp_servers.json" $content -Encoding UTF8

1.2.8 手动登录 qumall（每台机器只做一次）
        "D:/workspace/project/auto-test/AutoGenesis/excelio-mcp-server/simple_server.py",
        "--transport",
        "stdio"
      ],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}

⚠️ 替换占位符：
- 把所有 <用户名> 替换成你自己的 Windows 用户名（如 admin）
- 把所有 D:\workspace\project\auto-test\AutoGenesis 替换成你代码实际安装路径
- 把 APIFOX_ACCESS_TOKEN 填入真实的 token（或删除 apifox-mcp 整段如果不需要）

最快生成方法（PowerShell）：
$content = Get-Content "D:\workspace\project\auto-test\AutoGenesis\qumall-pool\mcp_config_template.json" -Raw
$content = $content -replace '<USERNAME>', $env:USERNAME
Set-Content "$env:USERPROFILE\.trendpower\mcp_servers.json" $content -Encoding UTF8

1.2.8 手动登录 qumall（每台机器只做一次）

每台机器需要一个独立的 Edge profile 登录 qumall，因为 chrome-devtools-mcp 同时只能持有一个 profile：

"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
  --user-data-dir="C:\Users\%USERNAME%\.trendpower\qumall-profile" ^
  https://admin.qumall.qushiyun.com/

弹出的 Edge 窗口里：
1. 输入账号 huitong，密码 <your-password>
2. 输入图形验证码（你或同事看图填入）
$content = $content -replace '<USERNAME>', $env:USERNAME
Set-Content "$env:USERPROFILE\.trendpower\mcp_servers.json" $content -Encoding UTF8

1.2.8 手动登录 qumall（每台机器只做一次）

每台机器需要一个独立的 Edge profile 登录 qumall，因为 chrome-devtools-mcp 同时只能持有一个 profile：

"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
  --user-data-dir="C:\Users\%USERNAME%\.trendpower\qumall-profile" ^
  https://admin.qumall.qushiyun.com/

弹出的 Edge 窗口里：
1. 输入账号 huitong，密码 <your-password>
2. 输入图形验证码（你或同事看图填入）
3. 看到后台首页后保持 Edge 开着
4. 回到 PowerShell，按 Ctrl+C 关闭这条命令

⚠️ 登录态会持续 30 分钟左右，超时需重新登录。

---
二、首次启动（主控机）

2.1 检查 SMB 共享可访问

PowerShell（任何一台机器）：
Test-Path "\\192.168.2.77\qumall-pool\db"
应该返回 True。

如果返回 False：
1. 检查 SMB 服务是否启动（控制面板 → 程序 → 启用或关闭 Windows 功能 → SMB 1.0/CIFS 文件共享支持）
2. 检查网络：ping 192.168.2.77
3. 检查防火墙是否放行 445 端口

2.2 把 jobs 灌入 SMB 共享池

主控机（你的电脑）：
cd D:\workspace\project\auto-test\AutoGenesis
python qumall-pool/split_jobs.py --queue blueprints\qumall-full-queue.json --pending "\\192.168.2.77\qumall-pool\jobs\pending" --force

验证：
dir \\192.168.2.77\qumall-pool\jobs\pending | find /c ".json"
应该返回 40（40 个 module 对应 40 个 job）。

2.3 启动本机 worker

cd D:\workspace\project\auto-test\AutoGenesis
nohup python qumall-pool\worker.py ^
  --worker-id "host77_main" ^
  --idle-sleep 30 ^
  > "C:\Users\admin\.trendpower\runs\worker-host77.console.log" 2>&1 &

2.4 验证 worker 启动

PowerShell（另一窗口）：
curl http://localhost:8765 2>nul
或：
powershell -Command "Get-Process python | Where-Object {$_.CommandLine -like '*worker.py*'} | Format-Table Id,StartTime"

应该看到 1 个 worker.py 进程在跑。

2.5 实时看进度（任何机器都能看）

set PYTHONIOENCODING=utf-8
python D:\workspace\project\auto-test\AutoGenesis\qumall-pool\status.py

输出类似：
=== qumall-pool status ===
pool: \\192.168.2.77\qumall-pool
jobs: pending=38  claimed=2  done=1  failed=0
cases: total=3590  通过=11  失败=0  跳过=23  pending=3556
top failures:
  ...
active workers:
  host77_main: 1 job(s) — module_1922_1955_FAQ
  host_pc2: 1 job(s) — module_0119_0206_充电桩首页

---
三、其他机器加入

3.1 给同事的"30 秒加入"命令包

完整一行启动命令（同事在自己电脑 PowerShell 里跑）：
$repo = "D:\workspace\project\auto-test\AutoGenesis"
Set-Location $repo
$workerId = "host_" + $env:COMPUTERNAME
Start-Process -FilePath "python" -ArgumentList "qumall-pool/worker.py","--worker-id","$workerId","--idle-sleep","30" -RedirectStandardOutput "worker-$workerId.log" -RedirectStandardError "worker-$workerId.err" -WindowStyle Hidden
Write-Host "Worker $workerId started. Monitor: type 'status' or run python qumall-pool/status.py"

3.2 简化版（如果你确定所有路径正确）

cd D:\workspace\project\auto-test\AutoGenesis
python qumall-pool\worker.py --worker-id "host_<本机名>" --idle-sleep 30

<本机名> 替换成实际电脑名（用 hostname 命令查）。

---
四、监控和维护

4.1 实时状态命令

set PYTHONIOENCODING=utf-8
python D:\workspace\project\auto-test\AutoGenesis\qumall-pool\status.py

每 30-60 秒跑一次看进度。

powershell -Command "Get-Content \\192.168.2.77\qumall-pool\logs\<worker_id>\<latest>.ndjson.log -Tail 30 -Wait"

或者只过滤关键事件（推荐）：
set PYTHONIOENCODING=utf-8
python D:\workspace\project\auto-test\AutoGenesis\qumall-db\filter_log.py <worker_id>

4.3 看 Excel 镜像最新结果

start "" "D:\workspace\project\auto-test\AutoGenesis\blueprints\qumall-full-replay.xlsx"

打开 Excel 看 col 14（执行结果）和 col 15（备注）列实时填充。

4.4 停掉所有 worker

主控机（自己电脑）：
powershell -Command "Get-Process python | Where-Object {$_.CommandLine -like '*worker.py*'} | Stop-Process -Force"

所有机器：每台机器跑同样的命令。

4.5 重跑失败的 job（如果需要）

dir \\192.168.2.77\qumall-pool\jobs\failed
move \\192.168.2.77\qumall-pool\jobs\failed\*.json \\192.168.2.77\qumall-pool\jobs\pending\

任何 worker 会自动捡起重新跑。

---
五、常见问题

Q1：worker 启动后立即报 "trendpower not importable"

A：检查 worker.py 里有没有用 uv run --project trendpower-py。最新代码已修。如果老代码，重新 clone 最新代码。

Q2：worker 报 "Target closed" / "Protocol error"

A：chrome-devtools-mcp 在 SPA 路由切换时容易丢 target。让 agent 调 list_pages + select_page 重新选页。skill 里 2.2.1 节已经写了规则。

Q3：worker 报 "database is locked"

A：SQLite 多机并发写可能锁冲突。已用 sheet_row 作主键减少冲突。如频繁出现，改 import_xlsx.py 加 PRAGMA journal_mode=WAL。

Q4：worker 跑某个 module 30 分钟还没完

A：单个 job 超时 30 分钟自动 kill + 标 failed。失败的 job 在 \\192.168.2.77\qumall-pool\jobs\failed\ 里，可以手动 move 回 pending 重跑。

Q5：登录态掉了（每个 worker 偶尔会）

A：手动跑第 1.2.8 步那条 Edge 命令重新登录即可。

Q6：网络断开 / SMB 掉

A：worker 会 subprocess.run 超时后写 failed。恢复后把 failed/* move 回 pending 重跑。
