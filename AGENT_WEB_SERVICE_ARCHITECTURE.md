# Agent Web服务架构重构说明

## 概述

本次重构将Agent从"主动轮询"模式改为"Web服务"模式，后端可以主动连接到Agent的Web服务执行命令，所有通信通过HTTPS加密。

## 架构变化

### 旧架构（轮询模式）
```
后端 → 创建命令到数据库队列
Agent → 定期轮询后端API获取命令
Agent → 执行命令并上报结果
```

### 新架构（Web服务模式）
```
Agent → 启动HTTPS Web服务（默认8443端口）
后端 → 主动连接到Agent Web服务
后端 → 直接推送命令到Agent
Agent → 执行命令并返回结果
```

## 主要改动

### 1. Agent模型扩展

新增字段：
- `web_service_port`: Web服务端口（默认8443）
- `web_service_enabled`: 是否启用Web服务（默认True）
- `certificate_path`: SSL证书路径
- `private_key_path`: SSL私钥路径

### 2. Agent Web服务器

**文件**: `deployment-tool/agent/web_server.py`

功能：
- 基于Flask实现HTTPS Web服务
- 自动生成自签名证书（首次启动）
- 提供以下API接口：
  - `GET /health`: 健康检查
  - `GET /api/status`: 获取Agent状态
  - `POST /api/execute`: 执行命令
  - `POST /api/commands/<id>/result`: 提交命令结果（内部使用）

### 3. 后端客户端

**文件**: `backend/apps/agents/client.py`

功能：
- `AgentWebClient`: Agent Web服务客户端类
- 支持HTTPS连接（默认不验证证书，因为使用自签名证书）
- 提供命令执行、状态查询、健康检查等方法

### 4. 命令队列优化

**文件**: `backend/apps/agents/command_queue.py`

改进：
- 自动检测Agent是否启用Web服务
- 如果启用Web服务，直接推送命令（实时）
- 如果未启用或推送失败，回退到传统轮询模式

## 部署和使用

### Agent启动

Agent默认启用Web服务模式：

```bash
# 启动Agent（启用Web服务，端口8443）
python3 /opt/myx-agent/main.py

# 启动Agent（指定端口）
python3 /opt/myx-agent/main.py --web-port 9443

# 禁用Web服务，使用传统轮询模式
python3 /opt/myx-agent/main.py --no-web
```

### 证书管理

**自动生成**（推荐）：
- Agent首次启动时自动生成自签名证书
- 证书保存在：`/etc/myx-agent/ssl/agent.crt`
- 私钥保存在：`/etc/myx-agent/ssl/agent.key`

**使用自定义证书**：
1. 将证书和私钥放到Agent服务器
2. 在Agent配置中指定路径：
   ```json
   {
     "certificate_path": "/path/to/cert.crt",
     "private_key_path": "/path/to/key.key"
   }
   ```

### 后端配置

后端会自动检测Agent的Web服务状态：

```python
from apps.agents.client import get_agent_client

# 获取Agent客户端
client = get_agent_client(agent)

if client:
    # Agent启用了Web服务
    if client.health_check():
        # 执行命令
        result = client.execute_command('ls', ['-la'])
else:
    # Agent未启用Web服务，使用传统模式
    pass
```

## 安全特性

1. **HTTPS加密**: 所有通信通过HTTPS加密
2. **Token认证**: 使用Agent Token进行身份验证
3. **自签名证书**: 自动生成，无需手动配置
4. **可选证书验证**: 后端可以选择是否验证证书

## 兼容性

- **向后兼容**: 如果Agent未启用Web服务，自动回退到传统轮询模式
- **平滑迁移**: 可以逐步迁移，新旧模式可以共存
- **配置灵活**: 可以通过配置启用/禁用Web服务

## 优势

1. **实时性**: 命令立即推送到Agent，无需等待轮询
2. **效率**: 减少不必要的轮询请求
3. **安全性**: HTTPS加密通信
4. **可控性**: 后端主动控制命令执行时机

## 注意事项

1. **防火墙**: 确保Agent服务器的8443端口（或自定义端口）对外开放
2. **证书警告**: 使用自签名证书时，浏览器/客户端会显示证书警告（这是正常的）
3. **网络要求**: 后端需要能够访问Agent服务器的IP和端口
4. **性能**: Web服务模式对Agent服务器资源消耗略高于轮询模式

## 故障排查

### Agent Web服务无法启动

1. 检查端口是否被占用：`netstat -tlnp | grep 8443`
2. 检查Flask是否安装：`pip3 install flask`
3. 检查证书目录权限：`ls -la /etc/myx-agent/ssl/`

### 后端无法连接Agent

1. 检查网络连通性：`curl -k https://agent-ip:8443/health`
2. 检查防火墙规则
3. 检查Agent是否启用Web服务：查看Agent配置中的`web_service_enabled`

### 证书问题

1. 删除旧证书重新生成：`rm -rf /etc/myx-agent/ssl/*`
2. 检查证书权限：证书644，私钥600
3. 手动生成证书：参考`web_server.py`中的`_generate_self_signed_cert`方法

## 迁移指南

### 从轮询模式迁移到Web服务模式

1. **更新Agent代码**: 部署新版本的Agent（包含Web服务器）
2. **更新依赖**: `pip3 install flask cryptography pyopenssl`
3. **重启Agent**: Agent会自动启用Web服务
4. **更新后端**: 后端代码已自动支持，无需额外配置
5. **验证**: 检查Agent日志，确认Web服务已启动

### 回退到轮询模式

如果遇到问题，可以临时回退：

```bash
# Agent启动时添加 --no-web 参数
python3 /opt/myx-agent/main.py --no-web
```

或在配置文件中设置：
```json
{
  "web_service_enabled": false
}
```

