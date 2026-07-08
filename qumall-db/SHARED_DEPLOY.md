# Multi-worker 部署手册

把 3590 条 qumall 用例分摊到 N 台机器并行跑。共享 SQLite DB + 每机独立 Edge profile + 24/7 持续。

## 架构

```
┌─ Worker A (Windows) ──────┐   ┌─ Worker B (Windows) ──────┐   ┌─ Worker C ──────┐
│ qumall-pilot.db (本地副本) │   │ qumall-pilot.db (本地副本) │   │ (本地副本)       │
│ Edge profile-A/            │   │ Edge profile-B/            │   │ profile-C/        │
│ run_long.py --worker-id=A  │   │ run_long.py --worker-id=B  │   │ --worker-id=C     │
└──────────┬─────────────────┘   └──────────┬─────────────────┘   └────────┬────────┘
           │ claim-next / set / release       │                                │
           ▼                                   ▼                                ▼
        ┌──────────────────────────────────────────────────┐
        │  SMB / NFS 共享文件夹 \\server\qumall\           │
        │   ├── qumall-pilot.db          (共享, 所有人读写) │
        │   ├── qumall-pilot.xlsx        (镜像, 只有 1 台写) │
        │   ├── qumall-pilot-queue.json  (只读导入用)       │
        │   └── checkpoints/             (每机私有)          │
        └──────────────────────────────────────────────────┘
```

**注意：xlsx 镜像的写回**允许多 worker 通过 `excelio__update_cells` 写——openpyxl 在 portalocker 锁上会等待，但每行写是原子的（一次一格），所以**多 worker 同时写不同行不会冲突**。但同一行的写是**不安全的**——所以确保每 worker 的 claim-next 拿到的 case 不重叠（SQLite 已经保证）。

## 一、前置（一次性，每机都要做）

### 1. 准备共享文件夹

任一台文件服务器开 SMB 共享，例如 `D:\qumall-pool` 共享为 `\\fileserver\qumall-pool`。每台 worker 都 mount 到本地一个固定路径（建议 `C:\qumall-pool` 软链或 `subst` 命令映射）。

### 2. 复制基础设施

每机：
```bash
# 项目仓库（任一分支都行，跑 qumall-fulltest skill 必须）
D:\workspace\project\auto-test\AutoGenesis\

# Python 依赖
cd D:\workspace\project\auto-test\AutoGenesis\trendpower\trendpower-py
uv sync

# 配置 mini-maxi 或 mimo（任选能跑工具调用的模型）
# TRENDPOWER_PROVIDER / TRENDPOWER_MODEL / TRENDPOWER_BASE_URL / OPENAI_API_KEY

# mcp_servers.json
# 5 servers: pywinauto / api-mcp / apifox-mcp / chrome-devtools / excelio
# chrome-devtools 用 --executablePath 指 Edge, --userDataDir 指向本机 profile
```

### 3. 每机的 Edge profile 独立

每台机器的 `chrome-devtools` 启动参数里 `--userDataDir` 必须不同：
- 机器 A: `C:\Users\<user-A>\.trendpower\qumall-profile-A`
- 机器 B: `C:\Users\<user-B>\.trendpower\qumall-profile-B`
- 机器 C: `C:\Users\<user-C>\.trendpower\qumall-profile-C`

每机自己手工登录一次 qumall 后台（用对应账号）→ 登录态固化在本机 profile。

### 4. 共享 qumall.db

在 worker A 上：
```bash
cd D:\workspace\project\auto-test\AutoGenesis
uv run python qumall-db/cli.py init --db C:\qumall-pool\qumall-pilot.db
uv run python qumall-db/import_xlsx.py \
    --db C:\qumall-pool\qumall-pilot.db \
    --queue D:\workspace\project\auto-test\AutoGenesis\blueprints\qumall-pilot-queue.json
```

(`import_xlsx.py` 默认会调 `excelio-mcp-server/dump_queue.py`，需要在 share 里有 `qumall-pilot-queue.json`)

镜像 xlsx 也放共享：`C:\qumall-pool\qumall-pilot.xlsx`（所有 worker 都从这里读 col 0-13，写 col 14/15）。

## 二、每机起一个 worker（24/7 持续跑）

### 手动起

机器 A:
```bash
cd D:\workspace\project\auto-test\AutoGenesis
$env:TRENDPOWER_PROVIDER="openai"
$env:TRENDPOWER_MODEL="mimo-v2.5-pro"
$env:TRENDPOWER_BASE_URL="https://token-plan-cn.xiaomimimo.com/v1"
$env:OPENAI_API_KEY="tp-..."
$env:QUMALL_USERNAME="huitong"
$env:QUMALL_PASSWORD="123456"
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONUTF8="1"

python run_long.py \
  --prompt "$(cat blueprints/worker_prompt.txt | sed 's/{WORKER_ID}/A/g')" \
  --worker-id A \
  --run-id qumall-pool \
  --cwd D:\workspace\project\auto-test\AutoGenesis \
  --mcp-config C:\Users\<user-A>\.trendpower\mcp_servers.json
```

机器 B/C 同上，**唯一区别**：
- `--worker-id B` / `C`
- prompt 里的 `{WORKER_ID}` 替换成 B / C
- mcp-config 路径改成自己的

### Windows Task Scheduler 24/7 自启

把上面命令存成 `D:\workspace\project\auto-test\AutoGenesis\scripts\start_worker.ps1`，然后用 XML 配 Task Scheduler（每天开机自动起 + 异常时重启）：

```xml
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>qumall worker A (24/7)</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-21-...  <!-- 当前用户 SID --></UserId>
      <LogonType>InteractiveToken</LogonType>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>  <!-- 无限 -->
  </Settings>
  <Actions>
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NoProfile -ExecutionPolicy Bypass -File D:\workspace\project\auto-test\AutoGenesis\scripts\start_worker.ps1</Arguments>
    </Exec>
  </Actions>
</Task>
```

每机一个 task，worker-id 写死在 ps1 脚本里。

## 三、监控

### 单机关键事件流（推荐 tail 这个）
```bash
PYTHONIOENCODING=utf-8 python qumall-db/filter_log.py qumall-pool-A --tail 30
```

### 全局进度（任何机器跑）
```bash
PYTHONIOENCODING=utf-8 python qumall-db/cli.py stats --db C:\qumall-pool\qumall-pilot.db
```
返回 `by_worker` 数组显示每台机器的 in-flight claim 数 + 最早 claim 时间。

### 找崩溃 worker
```bash
# sweep all expired leases
PYTHONIOENCODING=utf-8 python qumall-db/cli.py sweep-expired --db C:\qumall-pool\qumall-pilot.db
# 任何 worker 崩溃超 30 分钟，它的 case 自动被 release
```

## 四、故障处理手册

| 现象 | 原因 | 修法 |
|---|---|---|
| 某 worker PID 没了 | 崩溃 | 重启它，claim-next 自动从其他 worker 抢剩下的活 |
| `stats.by_status` 长期不增长 | claim 走完 / 死锁 | 跑 `sweep-expired`；查 xlsx 镜像最后几行是哪个 worker 写的 |
| `stats.by_worker` 缺一个 | 某 worker 死机 | 等 30 分钟 lease 过期 + sweep，或手 `release` |
| 多 worker 抢到同 case | SQL 旧版 bug | 升级 qumall-db ≥ ad6093d (claim-next 修复版) |
| 镜像 xlsx 写冲突 | portalocker 等待 | 30s 内自愈，excelio__update_cells 是原子的 |
| `Could not open database file` | SMB 断开 | 重连 SMB，再 claim-next |
| chrome-devtools `Target closed` | SPA 路由切换 | 已在 skill 2.2.1 章节处理；list_pages + select_page + wait_for |
| 验证码 / 未登录态 | 手工输入 | `ask_user_question` 暂停；登录态失效需重手工登录 |

## 五、扩展到 5+ worker

- 每加一台 worker，只需在共享盘外的机器上重复"前置"步骤
- `claim-next` 的 lease + sweep 机制确保 N 路不冲突
- 监控 `stats.by_worker` 看每路 in-flight 数
- 如果某 worker 慢（30 分钟 5 case），让其他 worker 跑得快即可平衡

## 六、停机 / 重新调度

- 关所有 worker → 共享 DB 留有 claimed-but-not-set 行 → 下次开 worker A 会先 claim-new（跳过 claimed）或先 sweep
- 重新清库：`import_xlsx.py --reset` 重建（不推荐，会清掉所有进度）
- 推荐：每晚 1 机器跑 `python qumall-db/cli.py sweep-expired` 当 cron 维护

## 七、性能预期

- 单机 30s/case × 8h = 960 case/天
- 3 机并行 2880 case/天
- 3590 case 一天半跑完
- 6 机 6 小时跑完

**瓶颈不在 worker 数**，在：
1. qumall 后台 API 响应速度（20-100ms/请求 × 5 步/case = 200-500ms 纯网络时间）
2. 模型 token 速度（每 case ~5-10k tokens）
3. 单机 Edge 进程最多 1 个（profile 锁）
