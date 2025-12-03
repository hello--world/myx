#!/bin/bash
set -e

# 检查Ansible是否已安装
if command -v ansible-playbook &> /dev/null; then
    echo "[信息] Ansible已安装: $(ansible-playbook --version | head -1)"
    exit 0
fi

echo "[信息] 检测到Ansible未安装，开始安装..."

# 尝试使用系统包管理器安装
if command -v apt-get &> /dev/null; then
    echo "[信息] 使用apt-get安装Ansible..."
    apt-get update -qq > /dev/null 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ansible > /dev/null 2>&1 || {
        echo "[警告] apt-get安装失败，尝试使用pip安装..."
        if command -v pip3 &> /dev/null; then
            pip3 install --quiet ansible || {
                echo "[错误] pip3安装Ansible失败"
                exit 1
            }
        elif command -v pip &> /dev/null; then
            pip install --quiet ansible || {
                echo "[错误] pip安装Ansible失败"
                exit 1
            }
        else
            echo "[错误] 无法安装Ansible，请手动安装"
            exit 1
        fi
    }
elif command -v yum &> /dev/null; then
    echo "[信息] 使用yum安装Ansible..."
    yum install -y -q ansible > /dev/null 2>&1 || {
        echo "[警告] yum安装失败，尝试使用pip安装..."
        if command -v pip3 &> /dev/null; then
            pip3 install --quiet ansible || {
                echo "[错误] pip3安装Ansible失败"
                exit 1
            }
        elif command -v pip &> /dev/null; then
            pip install --quiet ansible || {
                echo "[错误] pip安装Ansible失败"
                exit 1
            }
        else
            echo "[错误] 无法安装Ansible，请手动安装"
            exit 1
        fi
    }
elif command -v pip3 &> /dev/null || command -v pip &> /dev/null; then
    echo "[信息] 使用pip安装Ansible..."
    if command -v pip3 &> /dev/null; then
        pip3 install --quiet ansible || {
            echo "[错误] pip3安装Ansible失败"
            exit 1
        }
    else
        pip install --quiet ansible || {
            echo "[错误] pip安装Ansible失败"
            exit 1
        }
    fi
else
    echo "[错误] 无法安装Ansible，请手动安装"
    exit 1
fi

# 验证安装
if command -v ansible-playbook &> /dev/null; then
    echo "[成功] Ansible安装成功: $(ansible-playbook --version | head -1)"
    exit 0
else
    echo "[错误] Ansible安装失败"
    exit 1
fi

