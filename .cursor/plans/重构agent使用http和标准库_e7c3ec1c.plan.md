---
name: 重构Agent使用HTTP和标准库
overview: 重构 deployment-tool/agent，删除RPC和第三方库依赖，使用Python标准库（http.server）实现HTTP服务器，通过systemd环境变量传递配置，保留安全逻辑（随机端口、随机path），简化逻辑只保留命令执行功能。
todos:
  - id: "1"
    content: 重构代理节点管理页面为左侧 tab 导航结构
    status: completed
  - id: "2"
    content: 将 Caddy 管理从操作按钮移到左侧 tab
    status: completed
  - id: "3"
    content: 创建独立的 Caddyfile 管理 tab（管理所有服务器的 Caddyfile）
    status: completed
  - id: "4"
    content: 将系统设置移到最后一个 tab
    status: completed
---

# 重构 Agent 使用 HTTP 和标准库

## 目标

重构 `deployment-tool/agent`，删除RPC和第三方库依赖，使用Python标准库实现HTTP服务器，通过systemd环境变量传递配置，保留安全逻辑，简化逻辑只保留命令执行功能。

## 主要变更

### 1. 架构变更

#### 从 JSON-RPC 改为 HTTP API

- **删除**：`rpc_server.py` - JSON-RPC服务器
- **删除**：`rpc_client.py` - Agent端RPC客户端
- **新建**：使用Python标准库 `http.server` 实现HTTP服务器
- **API端点**：
  - `POST /{http_path}/execute` - 执行命令（系统命令、Ansible命令）
  - `POST /{http_path}/file` - **通用文件上传接口（set）**
  - `GET /{http_path}/file?path=...` - **通用文件获取接口（get）**
  - `GET /{http_path}/log/{command_id}?offset=0` - 获取命令日志（服务器轮询）
  - `GET /health` - 健康检查（可选，或通过执行命令完成）

#### 从第三方库改为标准库

- **删除**：Flask依赖（`from flask import ...`）
- **删除**：websockets依赖
- **删除**：uv依赖（不使用uv运行）
- **使用**：Python标准库 `http.server.HTTPServer` 和 `http.server.BaseHTTPRequestHandler`
- **使用**：Python标准库 `json`、`urllib.parse` 处理请求

### 2. 配置管理变更

#### 删除配置文件

- **删除**：`/etc/myx-agent/config.json` 配置文件
- **删除**：`Config` 类的 `save_config()` 和 `load_config()` 方法
- **删除**：`install_agent.yml` 中创建配置文件的步骤

#### 使用环境变量（通过systemd传递）

- **修改**：`Config` 类从环境变量读取配置
  - `AGENT_TOKEN` - Agent Token
  - `SECRET_KEY` - 加密密钥
  - `HTTP_PORT` - HTTP端口（服务器随机分配）
  - `HTTP_PATH` - HTTP路径（服务器随机分配，用于路径混淆）
  - `CERTIFICATE_PATH` - SSL证书路径（可选）
  - `PRIVATE_KEY_PATH` - SSL私钥路径（可选）

#### 修改 systemd 服务文件

- **修改**：`install_agent.yml` 中的systemd服务文件
- **添加**：Environment变量传递配置
- **修改 ExecStart**：从 `/usr/local/bin/uv run` 改为 `/usr/bin/python3`
- **示例**：
  ```ini
  [Service]
  Environment="AGENT_TOKEN={{ agent_token }}"
  Environment="SECRET_KEY={{ secret_key }}"
  Environment="HTTP_PORT={{ http_port }}"
  Environment="HTTP_PATH={{ http_path }}"
  Environment="CERTIFICATE_PATH={{ certificate_path }}"
  Environment="PRIVATE_KEY_PATH={{ private_key_path }}"
  ExecStart=/usr/bin/python3 {{ agent_dir }}/main.py
  ```


### 3. 删除多余代码

#### 删除文件

- `deployment-tool/agent/rpc_server.py` - JSON-RPC服务器
- `deployment-tool/agent/rpc_client.py` - Agent端RPC客户端

#### 删除 `main.py` 中的代码

- `AgentWebServer` 类（93-280行）- 使用Flask的Web服务器
- `Agent.run()` 中的 `enable_rpc` 和 `enable_web_service` 相关逻辑
- `Agent` 类中不必要的辅助方法：
  - `_save_rpc_port_to_config()` - 不再需要
  - `_load_rpc_port()` - 改为从环境变量读取
  - `save_config()` / `load_config()` - 删除

### 4. 新建 HTTP 服务器（使用标准库）

#### 新建 `http_server.py`

- **使用**：`http.server.HTTPServer` 和 `http.server.BaseHTTPRequestHandler`
- **实现**：
  - `AgentHTTPRequestHandler` 类处理HTTP请求
  - 路由处理：解析URL路径，分发到对应方法
  - Token验证：从请求头 `X-Agent-Token` 验证
  - JSON请求/响应：使用 `json` 模块解析和生成
  - SSL支持：使用 `ssl` 模块包装socket

#### HTTP API 端点

- `POST /{http_path}/execute` - 执行命令
  - 请求体：`{"command": "bash", "args": ["-c", "..."], "timeout": 300, "command_id": 123}`
  - 响应：`{"status": "accepted", "command_id": 123}`
- `POST /{http_path}/file` - **通用文件上传接口（set）**
  - 请求体：`{"path": "/tmp/myx-agent/playbook.yml", "content": "...", "mode": "0644"}`
  - 响应：`{"status": "ok", "path": "/tmp/myx-agent/playbook.yml"}`
  - 用途：上传YAML文件、配置文件等任意文件
- `GET /{http_path}/file?path=/tmp/myx-agent/playbook.yml` - **通用文件获取接口（get）**
  - 响应：`{"status": "ok", "content": "...", "path": "/tmp/myx-agent/playbook.yml"}`
  - 用途：获取已上传的文件内容
- `GET /{http_path}/log/{command_id}?offset=0` - 获取命令日志
  - 响应：`{"log_data": "...", "new_offset": 100, "is_final": false, "result": {...}}`
- `GET /health` - 健康检查（可选）

### 5. 简化 `main.py` 中的 `Agent` 类

#### 保留的核心方法

- `execute_command()` - 执行命令（系统命令、Ansible命令）
  - 系统命令：直接执行
  - Ansible命令：调用 `ansible_executor.run_playbook()`
- `get_command_log()` - 获取命令日志（服务器轮询）
- `set_file()` - **通用文件上传方法（set）**
  - 接收文件路径和内容，保存到指定位置
  - 支持设置文件权限
- `get_file()` - **通用文件获取方法（get）**
  - 根据文件路径读取文件内容
  - 返回文件内容或错误信息

#### 删除的方法

- `_execute_ansible_wrapper()` - 直接集成到 `execute_command`
- `_save_rpc_port_to_config()` - 不再需要
- `_load_rpc_port()` - 改为从环境变量读取
- `save_config()` / `load_config()` - 删除
- `upload_playbook()` - 改为使用通用的 `set_file()`

#### 修改 `Config` 类

- **删除**：`to_dict()` 和 `from_dict()` 方法
- **修改**：`__init__()` 从环境变量读取配置
  ```python
  def __init__(self):
      self.agent_token = os.environ.get('AGENT_TOKEN', '')
      self.secret_key = os.environ.get('SECRET_KEY', '')
      self.http_port = int(os.environ.get('HTTP_PORT', '8443'))
      self.http_path = os.environ.get('HTTP_PATH', '')
      self.certificate_path = os.environ.get('CERTIFICATE_PATH')
      self.private_key_path = os.environ.get('PRIVATE_KEY_PATH')
  ```


### 6. 简化 `ansible_executor.py`

#### 修改 `run_playbook` 方法

- 支持从临时文件执行playbook
- **删除Ansible安装检查**：假设Ansible已在安装Agent时安装

#### 删除

- `ensure_ansible_installed()` 和 `_install_ansible()` - 完全删除

### 7. 修改 `install_agent.yml`

#### 删除配置文件创建步骤

- 删除创建 `/etc/myx-agent/config.json` 的任务

#### 删除 uv 相关步骤

- 删除 uv 安装步骤
- 删除使用 uv 运行的相关配置

#### 修改 systemd 服务文件

- 添加 Environment 变量传递配置
- 使用服务器随机分配的端口和路径
- **修改 ExecStart**：从 `/usr/local/bin/uv run` 改为 `/usr/bin/python3`

### 8. 安全逻辑保留

#### 随机端口和路径

- 服务器在部署时随机生成端口和路径
- 通过systemd环境变量传递给Agent
- Agent使用这些值启动HTTP服务器

#### Token验证

- 所有API请求必须包含 `X-Agent-Token` 头
- 验证Token匹配 `AGENT_TOKEN` 环境变量

#### SSL支持（可选）

- 如果提供了证书路径，使用SSL包装HTTP服务器
- 使用Python标准库 `ssl` 模块

## 文件修改清单

1. **新建 `deployment-tool/agent/http_server.py`**

   - 使用 `http.server` 实现HTTP服务器
   - 实现路由、Token验证、JSON处理
   - 实现通用文件上传/获取接口

2. **修改 `deployment-tool/agent/main.py`**

   - 删除 `AgentWebServer` 类
   - 修改 `Config` 类从环境变量读取
   - 简化 `Agent` 类
   - 添加 `set_file()` 和 `get_file()` 方法
   - 修改 `main()` 函数启动HTTP服务器

3. **修改 `deployment-tool/agent/ansible_executor.py`**

   - 删除Ansible安装检查
   - 支持临时文件执行

4. **修改 `deployment-tool/playbooks/install_agent.yml`**

   - 删除配置文件创建步骤
   - 删除 uv 相关安装步骤
   - 修改systemd服务文件添加Environment变量
   - 修改 ExecStart 为 `/usr/bin/python3`

5. **删除文件**

   - `deployment-tool/agent/rpc_server.py`
   - `deployment-tool/agent/rpc_client.py`

6. **修改 `requirements.txt`**

   - 删除 Flask、websockets 等第三方库依赖
   - 删除 uv 相关依赖
   - 只保留必要的依赖（如 ansible-runner，如果需要）

## 注意事项

- 使用Python标准库，不依赖第三方库
- 不使用uv运行，直接使用python3运行
- 通用文件接口：使用 `set_file` 和 `get_file` 简化后续逻辑
- 保持向后兼容性：确保服务器端的HTTP调用能正常工作
- 临时文件管理：上传的文件需要定期清理
- 错误处理：确保所有HTTP端点都有适当的错误处理
- 日志记录：保留必要的日志记录
- 日志获取是关键功能：确保日志获取端点稳定可靠
- 服务器端轮询：当前架构已经是服务器端轮询，保持不变
- 安全逻辑：保留随机端口、随机路径、Token验证