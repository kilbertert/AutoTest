# AutoGenesis API Testing

## Overview

[AutoGenesis](https://github.com/microsoft/AutoGenesis) 是一个 AI 驱动的自动化测试框架，通过 MCP 协议提供测试工具。你现在正在使用 trendpower agent 调用 AutoGenesis 的 `api-mcp-server` 来做 HTTP API 测试。

## MCP Server Setup

The `api-mcp-server` is already configured in your trendpower MCP settings. All tools below are available via MCP.

## When To Use

Use these tools when:
- User asks you to test a REST API endpoint
- User wants you to generate pytest test code from natural language requirement
- You need to verify API behavior (status code, response body, headers)
- User wants to create automated API test cases from BDD feature files

## Workflow

### For interactive API testing:
```
1. set_base_url - Set the base URL for the API
2. (Optional) set_headers - Add global headers (Content-Type, Authorization, etc.)
3. (Optional) set_auth - Configure authentication (bearer token, API key, basic auth)
4. Send HTTP request: http_get / http_post / http_put / http_delete / http_patch
5. Add assertions: assert_status / assert_json_path / assert_header / assert_body_contains
6. (Optional) extract_variable - Extract token/id from response for next requests
```

### For code generation (BDD):
```
1. before_gen_code - Initialize code generation session (pass feature_file path)
2. Execute each BDD step via corresponding MCP tool calls (one tool call per step)
3. After all steps: preview_code_changes → confirm_code_changes
4. The pytest step definitions will be automatically generated and saved
```

## Tool Reference

### Configuration Tools

| Tool | Purpose | Example |
|------|---------|---------|
| `set_base_url(base_url)` | Set API base URL | `set_base_url("https://api.example.com")` |
| `set_headers(headers)` | Set global headers | `set_headers({"Authorization": "Bearer token"})` |
| `set_auth(auth_type, ...)` | Configure authentication<br>- `auth_type: "bearer"` needs `token`<br>- `auth_type: "api_key"` needs `api_key`, `key_name`, `location`<br>- `auth_type: "basic"` needs `username`, `password`<br>- `auth_type: "none"` clears auth | |
| `set_timeout(timeout)` | Set request timeout in seconds | `set_timeout(30)` |
| `get_config()` | Get current configuration | |
| `load_config(config_path)` | Load configuration from file | |

### HTTP Request Tools

| Method | Parameters | Notes |
|--------|------------|-------|
| `http_get(url, headers?, params?, extract_path?, extract_variable?)` | `url` can include `{{variable}}` placeholders | Use `extract_path` + `extract_variable` to extract values from JSON response |
| `http_post(url, body?, headers?, params?, extract_path?, extract_variable?)` | `body` can be JSON dict or string | |
| `http_put(url, body?, headers?, params?, extract_path?, extract_variable?)` | | |
| `http_delete(url, headers?, params?)` | | |
| `http_patch(url, body?, headers?, params?, extract_path?, extract_variable?)` | | |

**Variable substitution**: All parameters automatically resolve `{{variable_name}}` placeholders using previously extracted variables.

### Assertion Tools

| Tool | Purpose |
|------|---------|
| `assert_status(expected, operator)` | Assert HTTP status code (`==`, `!=`, `<`, `>`, `in`) |
| `assert_json_path(jsonpath, expected_value?, expected_contains?)` | Assert value at JSONPath |
| `assert_json_schema(schema)` | Assert response matches JSON Schema |
| `assert_header(name, value?)` | Assert header exists and optional value |
| `assert_response_time(max_ms)` | Assert response time < N milliseconds |
| `assert_body_contains(text, case_sensitive?)` | Assert response body contains text |

### Variable Extraction Tools

| Tool | Purpose |
|------|---------|
| `extract_variable(variable_name, jsonpath)` | Extract value from last response using JSONPath |
| `set_variable(variable_name, value)` | Manually set variable |
| `get_variables()` | Get all stored variables |
| `clear_variables()` | Clear all variables |

### Code Generation Tools

| Tool | Purpose |
|------|---------|
| `before_gen_code(feature_file)` | Start code generation session, clear cache |
| `preview_code_changes()` | Preview what code will be generated |
| `confirm_code_changes()` | Write the generated code to file |

## Best Practices

1. **Always set base_url first** - This avoids repeating full URLs in every request
2. **Extract and reuse** - Extract tokens/IDs from login response and use them in subsequent requests
3. **One step = one tool call** - For BDD code generation, each Gherkin step must become exactly one MCP tool call
4. **Fail fast** - If any assertion fails, report the error to the user immediately don't continue
5. **Use variable substitution** - Leverage `{{variable}}` instead of hardcoding values

## Example

### User: Test that GET /users returns 200 and non-empty array

```
you: set_base_url("https://jsonplaceholder.typicode.com")
you: http_get("/users")
you: assert_status(200)
you: assert_json_path("$[0].name")
```

### User: Create user then get it back

```
you: set_base_url("https://jsonplaceholder.typicode.com")
you: http_post("/users", body={"name": "张三", "email": "zhangsan@example.com"}, extract_path="$id", extract_variable="new_user_id")
you: assert_status(201)
you: http_get("/users/{{new_user_id}}")
you: assert_json_path("$.id", {{new_user_id}})
```

## Integration with UI Testing

You can **combine API testing with UI testing** when multiple MCP servers are configured:
- Use `appium-mcp-server` / `pywinauto-mcp-server` for UI interactions
- Use `api-mcp-server` for backend API verification
- This gives you full-stack testing capabilities in a single agent session
