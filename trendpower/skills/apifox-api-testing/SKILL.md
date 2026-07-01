---
name: apifox-api-testing
description: Test APIs whose definitions live on Apifox. Use when the user says "测试 Apifox 上的接口", "接口在 apifox 上", "test the login API from apifox", "看看 apifox 上有哪些接口", or otherwise references Apifox as the source of truth for API definitions. This skill orchestrates apifox-mcp (discover endpoints/scenarios) + api-mcp (actually send requests + assert) — it does NOT replace api-mcp, it feeds it.
---

# Apifox API Testing

## When To Use

The user wants to test APIs that are documented/managed on an Apifox platform. The agent's job is to:

1. **Discover** what endpoints exist and read their contract — via `apifox-mcp` tools.
2. **Execute** tests by sending real HTTP requests and asserting — via `api-mcp` tools (http_*, assert_*, extract_*).
3. **(Optional) Regression** — only when the user explicitly asks to run a pre-arranged Apifox scenario — via `apifox-mcp`'s `apifox_run_scenario`.

## Why two MCP servers

- `apifox-mcp` = **documentation + regression layer**. It reads Apifox's stored endpoint definitions and runs QA-prepared scenarios. It CANNOT write inline assertions — `apifox run` only executes assertions that QA configured in the Apifox GUI beforehand.
- `api-mcp` = **execution layer**. It sends HTTP requests (http_get/post/...) and checks results (assert_status / assert_json_path / ...). The LLM writes the assertions here, freely.

So for "test endpoint X", you read the contract from apifox-mcp, then drive the actual test through api-mcp.

## Workflow

### First time / sanity check
```
apifox_cli_version      # confirm CLI installed
apifox_check_token      # confirm token + project reachable
```

**Where the token comes from:** apifox-mcp reads `APIFOX_ACCESS_TOKEN` and `APIFOX_PROJECT_ID` from the `env` block of its entry in `~/.trendpower/mcp_servers.json` at server startup. They are **NOT** passed in the user's prompt. If the user types a token in the prompt, ignore it — the server already has one (or doesn't, in which case the tools below will tell you so).

**If `apifox_check_token` reports `token_configured: false` or `reachable: false`:** report the exact error to the user and tell them to edit `~/.trendpower/mcp_servers.json` → `mcpServers.apifox-mcp.env` to set `APIFOX_ACCESS_TOKEN` and `APIFOX_PROJECT_ID`, then **restart trendpower** (env vars are only read at server start). Token is generated in Apifox under 个人设置 → API 访问令牌 (new format prefix `afxp_`; older `APS-` may also work).

**If the tool errors with "无效的项目 ID":** the project_id is a name, not a numeric ID. Use `apifox project list` (call the apifox CLI directly via bash) to find the numeric ID, or ask the user for it.

### Test a specific endpoint by name
```
1. apifox_list_endpoints(path_contains="health")   # find the endpoint id (path filter is more reliable than name_contains)
2. apifox_get_endpoint_detail(endpoint_id="<id>")  # read params / body / responses
3. api-mcp: set_base_url("<base url>")              # from the endpoint or user
4. api-mcp: http_get("<path>") / http_post(...)     # construct from the contract
5. api-mcp: assert_status(200)
6. api-mcp: assert_json_path("$.data.field")        # verify contract
7. api-mcp: extract_variable("token", "$.data.token")  # for chained calls
```

### Explore the whole project
```
apifox_list_endpoints()                            # all endpoints, scannable list
apifox_list_endpoints(method="GET", tag="User")    # filtered
```

### Run a QA regression scenario (only on explicit request)
```
apifox_list_scenarios()                            # find scenario id
apifox_run_scenario(scenario_id="<id>")            # runs QA's pre-arranged assertions
```
Only do this when the user says something like "跑一下 Apifox 上的回归场景". For exploratory testing, stay on the apifox_get_endpoint_detail → api-mcp path.

## Tool reference (apifox-mcp)

| Tool | Purpose |
|------|---------|
| `apifox_cli_version()` | CLI installed? version? |
| `apifox_check_token(project_id?)` | token valid + project reachable? |
| `apifox_list_endpoints(project_id?, method?, tag?, path_contains?, name_contains?)` | scannable endpoint list `{id, method, path, name, status, tags}` |
| `apifox_get_endpoint_detail(endpoint_id, project_id?)` | full contract of one endpoint |
| `apifox_list_scenarios(project_id?)` | QA test scenarios `{id, name, step_count}` |
| `apifox_run_scenario(scenario_id, project_id?, environment_id?, reporters?, iteration_count?)` | run a QA scenario, get report |

All `project_id` args default to the `APIFOX_PROJECT_ID` env var — omit it when the user is working in the single configured project.

## Tool reference (api-mcp) — execution layer

See the `autogenesis-api-testing` skill for the full list. Key tools: `set_base_url`, `set_headers`, `set_auth`, `http_get/post/put/delete/patch`, `assert_status`, `assert_json_path`, `assert_json_schema`, `assert_header`, `assert_response_time`, `extract_variable`, `set_variable`.

## Best practices

1. **Always read the contract first** — don't guess the request body. Call `apifox_get_endpoint_detail` and build the body from its schema.
2. **Extract and chain** — for multi-step flows (login → use token), extract variables with api-mcp and reuse via `{{var}}`.
3. **Fail fast** — if `apifox_check_token` or `apifox_list_endpoints` fails, report the error to the user; don't try to test blind.
4. **Don't conflate the two servers** — apifox-mcp cannot assert; api-mcp cannot read Apifox. Use both.
5. **Regression vs exploratory** — `apifox_run_scenario` is for QA's pre-built scenarios only. For "test this endpoint", build the request yourself via api-mcp.
