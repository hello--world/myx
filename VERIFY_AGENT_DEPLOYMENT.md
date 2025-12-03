# Agent部署验证指南

## 验证方法

### 1. 通过Web界面验证

#### 1.1 测试连接
- 进入 **服务器管理** 页面
- 找到对应的服务器
- 点击 **"测试连接"** 按钮
- 查看返回结果：
  - ✅ **成功**：显示 "Agent Web服务连接成功" 或 "Agent连接成功（心跳模式）"
  - ❌ **失败**：显示错误信息

#### 1.2 查看Agent状态
- 进入 **Agent管理** 页面
- 查看Agent状态：
  - **在线** (online)：Agent正常运行
  - **离线** (offline)：Agent未运行或无法连接
- 查看最后心跳时间：
  - 应该在最近1分钟内（Web服务模式）
  - 或在最近5分钟内（心跳模式）

### 2. 通过SSH验证（在服务器上）

#### 2.1 检查Agent服务状态
```bash
# 检查systemd服务状态
systemctl status myx-agent

# 应该看到：
# Active: active (running)
```

#### 2.2 检查Web服务是否启动
```bash
# 检查8443端口是否监听
netstat -tlnp | grep 8443
# 或
ss -tlnp | grep 8443

# 应该看到：
# LISTEN 0 128 0.0.0.0:8443
```

#### 2.3 测试Web服务健康检查
```bash
# 测试健康检查接口
curl -k https://localhost:8443/health

# 应该返回：
# {"status":"ok","version":"1.0.0","timestamp":...}
```

#### 2.4 检查Agent文件
```bash
# 检查文件是否存在
ls -la /opt/myx-agent/

# 应该看到：
# main.py
# web_server.py (如果启用Web服务)
# requirements.txt
# config.json
```

#### 2.5 检查Web服务依赖
```bash
# 检查Flask是否安装
python3 -c "import flask; print(flask.__version__)"

# 应该输出Flask版本号
```

#### 2.6 查看Agent日志
```bash
# 查看systemd日志
journalctl -u myx-agent -f

# 或查看最近的日志
journalctl -u myx-agent -n 50

# 应该看到：
# Agent启动中...
# Agent Web服务已启动: https://0.0.0.0:8443
```

### 3. 通过API验证

#### 3.1 检查Agent注册状态
```bash
# 使用curl测试（需要替换token和API地址）
curl -H "Authorization: Bearer YOUR_TOKEN" \
     https://your-api-domain/api/agents/

# 应该返回Agent列表，包含新部署的Agent
```

#### 3.2 测试Web服务连接
```bash
# 从后端服务器测试Agent Web服务（需要替换IP和token）
curl -k -H "X-Agent-Token: AGENT_TOKEN" \
     https://AGENT_IP:8443/health

# 应该返回：
# {"status":"ok","version":"1.0.0","timestamp":...}
```

### 4. 验证清单

#### ✅ Web服务模式验证
- [ ] Agent服务状态为 `active (running)`
- [ ] 8443端口正在监听
- [ ] `/health` 接口返回 `{"status":"ok"}`
- [ ] `web_server.py` 文件存在
- [ ] Flask依赖已安装
- [ ] 测试连接显示 "Agent Web服务连接成功"
- [ ] Agent状态为 `online`
- [ ] 最后心跳时间在最近1分钟内

#### ✅ 传统模式验证（如果Web服务未启用）
- [ ] Agent服务状态为 `active (running)`
- [ ] Agent状态为 `online`
- [ ] 最后心跳时间在最近5分钟内
- [ ] 测试连接显示 "Agent连接成功（心跳模式）"

### 5. 常见问题排查

#### 问题1：Web服务未启动
**症状**：8443端口未监听，测试连接回退到心跳模式

**排查步骤**：
```bash
# 1. 检查Flask是否安装
python3 -c "import flask"

# 2. 检查证书是否存在
ls -la /etc/myx-agent/ssl/

# 3. 查看Agent日志
journalctl -u myx-agent -n 100

# 4. 手动测试启动
cd /opt/myx-agent
python3 main.py
```

**解决方案**：
- 安装Flask依赖：`pip3 install --break-system-packages --ignore-installed flask cryptography pyopenssl`
- 检查证书：如果证书不存在，Agent会自动生成
- 重启服务：`systemctl restart myx-agent`

#### 问题2：SSL证书错误
**症状**：测试连接时出现SSL错误

**排查步骤**：
```bash
# 检查证书
openssl x509 -in /etc/myx-agent/ssl/agent.crt -text -noout

# 测试连接（忽略证书验证）
curl -k https://localhost:8443/health
```

**解决方案**：
- 证书是自签名的，这是正常的
- 后端客户端默认不验证证书（`verify_ssl=False`）

#### 问题3：Agent未注册
**症状**：Agent服务运行但状态为offline

**排查步骤**：
```bash
# 检查配置文件
cat /etc/myx-agent/config.json

# 检查网络连接
curl https://your-api-domain/api/agents/register/
```

**解决方案**：
- 检查API地址是否正确
- 检查网络连接
- 检查防火墙规则

### 6. 快速验证脚本

创建一个验证脚本 `verify_agent.sh`：

```bash
#!/bin/bash

echo "=== Agent部署验证 ==="
echo ""

# 1. 检查服务状态
echo "1. 检查Agent服务状态..."
systemctl is-active myx-agent && echo "✅ 服务运行中" || echo "❌ 服务未运行"

# 2. 检查文件
echo ""
echo "2. 检查Agent文件..."
[ -f /opt/myx-agent/main.py ] && echo "✅ main.py 存在" || echo "❌ main.py 不存在"
[ -f /opt/myx-agent/web_server.py ] && echo "✅ web_server.py 存在" || echo "⚠️  web_server.py 不存在（传统模式）"

# 3. 检查Web服务
echo ""
echo "3. 检查Web服务..."
if netstat -tlnp 2>/dev/null | grep -q 8443 || ss -tlnp 2>/dev/null | grep -q 8443; then
    echo "✅ 8443端口正在监听"
    curl -k -s https://localhost:8443/health > /dev/null && echo "✅ Web服务健康检查通过" || echo "⚠️  Web服务健康检查失败"
else
    echo "⚠️  8443端口未监听（可能使用传统模式）"
fi

# 4. 检查依赖
echo ""
echo "4. 检查Python依赖..."
python3 -c "import requests" 2>/dev/null && echo "✅ requests 已安装" || echo "❌ requests 未安装"
python3 -c "import flask" 2>/dev/null && echo "✅ flask 已安装" || echo "⚠️  flask 未安装（传统模式）"

# 5. 检查日志
echo ""
echo "5. 最近的日志..."
journalctl -u myx-agent -n 5 --no-pager | tail -3

echo ""
echo "=== 验证完成 ==="
```

使用方法：
```bash
chmod +x verify_agent.sh
./verify_agent.sh
```

### 7. 自动化验证

在后端可以添加一个验证接口，自动检查所有Agent的部署状态。

## 总结

**最简单的验证方法**：
1. 在Web界面点击 **"测试连接"**
2. 如果显示 "Agent Web服务连接成功" 或 "Agent连接成功（心跳模式）"，说明部署成功

**最全面的验证方法**：
1. 检查服务状态：`systemctl status myx-agent`
2. 检查端口监听：`netstat -tlnp | grep 8443`
3. 测试健康检查：`curl -k https://localhost:8443/health`
4. 查看日志：`journalctl -u myx-agent -n 50`

