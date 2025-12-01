# MyX Deployment Tool

独立的部署工具，用于通过Ansible部署Xray、Caddy等服务。

## 特性

- 独立运行，不依赖Django框架
- 版本管理，支持自动同步到Agent端
- 完整的日志记录
- 基于Ansible的可靠部署

## 目录结构

```
deployment-tool/
├── VERSION                    # 版本号
├── README.md                  # 说明文档
├── ansible.cfg                # Ansible配置
├── agent/                     # Agent程序（Python版本）
│   ├── main.py               # Agent主程序
│   ├── requirements.txt      # Python依赖
│   └── README.md             # Agent说明文档
├── playbooks/                 # Ansible playbooks
│   ├── deploy_xray_config.yml # Xray配置部署
│   ├── deploy_xray.yml        # Xray安装
│   └── deploy_caddy.yml       # Caddy安装
├── scripts/                   # 辅助脚本
├── logs/                      # 日志目录（Agent端）
└── inventory/                 # Inventory模板
```

## 使用方法

### 在Agent端使用

1. 工具会自动同步到 `/opt/myx-deployment-tool/`
2. 执行部署：
   ```bash
   cd /opt/myx-deployment-tool
   ansible-playbook -i inventory/localhost.ini playbooks/deploy_xray_config.yml -e config_file=/tmp/xray_config.json
   ```

## 版本管理

- 版本号定义在 `VERSION` 文件中
- Agent端会检查版本，如果不一致会自动同步

