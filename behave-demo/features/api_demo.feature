Feature: 用户管理 API

  测试 API 端点的基本功能，演示如何使用 BDD AI Toolkit 进行接口测试

  Background:
    Given API 基础地址为 "https://jsonplaceholder.typicode.com"

  Scenario: 获取用户列表
    When 我向 "/users" 发送 GET 请求
    Then 响应状态码应为 200
    And 响应体应为一个数组
    And 数组长度应大于 0
    And 响应体中的第一个用户的 "name" 字段不应为空

  Scenario: 创建新用户
    When 我向 "/users" 发送 POST 请求
      """
      {"name": "张三", "email": "zhangsan@example.com"}
      """
    Then 响应状态码应为 201
    And 响应体中的 "name" 应为 "张三"
    And 从响应中提取 "id" 存入变量 "new_user_id"

  Scenario: 使用提取的变量获取用户
    When 我向 "/users/{{new_user_id}}" 发送 GET 请求
    Then 响应状态码应为 200
    And 响应体中的 "id" 应为 {{new_user_id}}
