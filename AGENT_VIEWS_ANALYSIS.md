# backend/apps/agents/views.py 功能分析

## 文件结构概览

这个文件包含了 Agent 相关的所有 API 端点，分为三个主要部分：

1. **工具函数** - 辅助功能
2. **ViewSet 类** - 面向 Web 前端的 REST API（需要认证）
3. **独立 API 视图** - 面向 Agent 端的接口（允许匿名访问）

---

## 一、工具函数

### `get_agent_by_token(token)` (第23-45行)
**功能**: 通过 token 查找 Agent，自动处理 UUID 格式转换

**特点**:
- 支持带连字符和不带连字符的 UUID 格式
- 自动尝试两种格式转换
- 用于所有 Agent 端调用的接口中

---

## 二、ViewSet 类（Web 前端 API）

### 1. `AgentViewSet` (第48-299行)
**类型**: `ReadOnlyModelViewSet`（只读，自定义 action 用于写操作）

**基础功能**:
- `GET /api/agents/` - 列表查询（只返回当前用户的 Agent）
- `GET /api/agents/{id}/` - 详情查询

**自定义 Actions**:

#### 1.1 `send_command` (第57-80行)
- **路径**: `POST /api/agents/{id}/send_command/`
- **功能**: 向 Agent 下发命令
- **参数**: `command`, `args`, `timeout`
- **调用**: `AgentService.send_command()`

#### 1.2 `update_certificate` (第82-130行)
- **路径**: `POST /api/agents/{id}/update_certificate/`
- **功能**: 更新 Agent 的 SSL 证书
- **参数**: 
  - `regenerate`: 是否重新生成证书
  - `verify_ssl`: SSL 验证选项
- **调用**: `CertificateService.regenerate_agent_certificate()` 或 `update_verify_ssl()`

#### 1.3 `upgrade` (第132-239行) ⭐ **核心功能**
- **路径**: `POST /api/agents/{id}/upgrade/`
- **功能**: 升级 Agent
- **流程**:
  1. 取消正在运行的相同部署任务
  2. 创建新的部署任务
  3. 根据 Agent 状态选择升级方式：
     - **Agent 在线**: 通过 `AgentUpgradeService.upgrade_via_agent()`（Agent 自升级）
     - **Agent 离线**: 通过 `AgentUpgradeService.upgrade_via_ssh()`（SSH 升级，异步执行）
- **返回**: 部署任务 ID

#### 1.4 `stop` (第241-255行)
- **路径**: `POST /api/agents/{id}/stop/`
- **功能**: 停止 Agent 服务
- **调用**: `AgentService.stop_agent()`

#### 1.5 `start` (第257-271行)
- **路径**: `POST /api/agents/{id}/start/`
- **功能**: 启动 Agent 服务
- **调用**: `AgentService.start_agent()`

#### 1.6 `commands` (第273-282行)
- **路径**: `GET /api/agents/{id}/commands/`
- **功能**: 获取 Agent 的命令历史（最近 50 条）

#### 1.7 `check_status` (第284-299行)
- **路径**: `POST /api/agents/{id}/check_status/`
- **功能**: 手动检查 Agent 状态（拉取模式）
- **调用**: `AgentService.check_agent_status()`

### 2. `CommandTemplateViewSet` (第302-309行)
**类型**: `ModelViewSet`（完整的 CRUD）

**功能**: 管理命令模板
- `GET /api/agents/command-templates/` - 列表
- `POST /api/agents/command-templates/` - 创建
- `GET /api/agents/command-templates/{id}/` - 详情
- `PUT/PATCH /api/agents/command-templates/{id}/` - 更新
- `DELETE /api/agents/command-templates/{id}/` - 删除

---

## 三、独立 API 视图（Agent 端调用）

这些接口使用 `@permission_classes([AllowAny])`，允许 Agent 匿名访问。

### 1. `agent_register` (第312-427行) ⭐ **核心功能**
- **路径**: `POST /api/agents/register/`
- **功能**: Agent 注册接口（Agent 首次启动时调用）
- **流程**:
  1. 通过 `server_token`（服务器 ID）查找服务器
  2. 生成或获取 Agent 记录
  3. 生成 token、secret_key、RPC 端口
  4. 更新 Agent 状态为 `online`
  5. 记录注册日志
- **返回**: `token`, `secret_key`, `server_id`

### 2. `agent_command` (第430-460行)
- **路径**: `POST /api/agents/command/`
- **功能**: Agent 命令执行接口（**已废弃？**）
- **说明**: 这个接口似乎只是返回命令，实际执行由 Agent 完成
- **注意**: 代码注释说"Agent会轮询或通过WebSocket获取命令"，可能已被 `agent_poll_commands` 替代

### 3. `agent_poll_commands` (第463-510行) ⭐ **核心功能**
- **路径**: `GET /api/agents/poll_commands/`
- **功能**: Agent 轮询命令接口（**拉取模式的核心接口**）
- **流程**:
  1. 验证 Agent token
  2. 更新心跳时间（`last_heartbeat`）
  3. 更新 Agent 状态为 `online`
  4. 从命令队列获取待执行的命令
  5. 返回命令列表和配置信息
- **返回**: 
  - `commands`: 待执行命令列表
  - `config`: 心跳和轮询间隔配置

### 4. `agent_command_result` (第513-571行) ⭐ **核心功能**
- **路径**: `POST /api/agents/command/{command_id}/result/`
- **功能**: Agent 上报命令执行结果
- **参数**:
  - `success`: 是否成功
  - `stdout`: 标准输出
  - `error`/`stderr`: 错误信息
  - `append`: 是否追加（默认 false，最终结果）
- **流程**:
  1. 验证 Agent token
  2. 更新命令执行结果
  3. 记录执行日志（支持 base64 解码）
- **返回**: `{'status': 'ok'}`

### 5. `agent_command_progress` (第574-608行)
- **路径**: `POST /api/agents/command/{command_id}/progress/`
- **功能**: Agent 上报命令执行进度（实时增量输出）
- **参数**:
  - `stdout`: 标准输出增量
  - `stderr`: 错误输出增量
  - `append`: 是否追加（默认 true，增量更新）
- **用途**: 用于长时间运行的命令，实时上报输出

### 6. `agent_report_progress` (第611-636行)
- **路径**: `POST /api/agents/deployment/{deployment_id}/progress/`
- **功能**: Agent 上报部署进度
- **参数**: `log` - 部署日志内容
- **用途**: 在部署过程中实时更新部署日志

### 7. `agent_file_download` (第639-676行)
- **路径**: `GET /api/agents/files/{filename}/`
- **功能**: 提供 Agent 文件下载
- **允许的文件**: `main.py`, `requirements.txt`
- **用途**: Agent 可以从服务器下载最新版本的文件

---

## 四、关键设计模式

### 1. **拉取模式（Pull Model）**
- Agent 主动轮询 `agent_poll_commands` 获取命令
- 服务器不主动推送，Agent 定期拉取

### 2. **命令队列机制**
- 使用 `CommandQueue` 管理待执行命令
- Agent 通过 `agent_poll_commands` 获取命令
- 通过 `agent_command_result` 上报结果

### 3. **心跳机制**
- Agent 每次调用 `agent_poll_commands` 时更新心跳
- 自动更新 `last_heartbeat` 和 `status='online'`

### 4. **Token 认证**
- 所有 Agent 端接口使用 `X-Agent-Token` header
- 通过 `get_agent_by_token()` 验证身份

### 5. **Service 层分离**
- Web 前端 API 调用 Service 层（`AgentService`, `CertificateService`, `AgentUpgradeService`）
- Agent 端 API 直接操作模型和队列

---

## 五、API 端点总结

### Web 前端 API（需要认证）
```
GET    /api/agents/                          # 列表
GET    /api/agents/{id}/                     # 详情
POST   /api/agents/{id}/send_command/         # 下发命令
POST   /api/agents/{id}/update_certificate/  # 更新证书
POST   /api/agents/{id}/upgrade/              # 升级Agent
POST   /api/agents/{id}/stop/                 # 停止服务
POST   /api/agents/{id}/start/                # 启动服务
GET    /api/agents/{id}/commands/             # 命令历史
POST   /api/agents/{id}/check_status/         # 检查状态
```

### Agent 端 API（匿名访问）
```
POST   /api/agents/register/                      # 注册
GET    /api/agents/poll_commands/                 # 轮询命令 ⭐
POST   /api/agents/command/{id}/result/           # 上报结果 ⭐
POST   /api/agents/command/{id}/progress/         # 上报进度
POST   /api/agents/deployment/{id}/progress/       # 上报部署进度
GET    /api/agents/files/{filename}/               # 下载文件
```

---

## 六、潜在问题和改进建议

### 1. **代码重复**
- `get_agent_by_token()` 在多个函数中重复调用
- Token 验证逻辑重复

### 2. **已废弃的接口**
- `agent_command` 接口可能已废弃，建议确认并删除

### 3. **错误处理**
- 部分接口缺少详细的错误处理
- 日志记录不够统一

### 4. **代码组织**
- 文件过长（678行），建议拆分：
  - Agent 管理相关（ViewSet）
  - Agent 端 API（独立视图）
  - 命令模板（单独文件）

### 5. **安全性**
- Agent 端接口使用 `AllowAny`，依赖 Token 验证
- 建议添加速率限制防止滥用

---

## 七、核心流程

### Agent 注册流程
```
Agent 启动 → POST /api/agents/register/
         → 返回 token, secret_key
         → Agent 保存凭证
```

### 命令执行流程
```
1. Web前端 → POST /api/agents/{id}/send_command/
         → AgentService.send_command() → 命令入队

2. Agent 轮询 → GET /api/agents/poll_commands/
              → 获取待执行命令
              → 执行命令

3. Agent 上报 → POST /api/agents/command/{id}/result/
              → 更新命令结果
              → 记录日志
```

### Agent 升级流程
```
Web前端 → POST /api/agents/{id}/upgrade/
      → 创建部署任务
      → Agent在线: upgrade_via_agent()
      → Agent离线: upgrade_via_ssh()
      → 使用 install_agent.yml playbook
```

---

## 总结

这个文件是 Agent 系统的核心，负责：
1. **Web 前端管理界面** - 通过 ViewSet 提供 Agent 管理功能
2. **Agent 端通信** - 通过独立 API 视图实现拉取模式通信
3. **命令执行机制** - 命令队列、轮询、结果上报
4. **Agent 生命周期** - 注册、升级、启停

文件虽然复杂，但功能清晰，主要问题是代码组织可以进一步优化。

