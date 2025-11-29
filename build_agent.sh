#!/bin/bash
# Agent 构建脚本

set -e

cd "$(dirname "$0")/agent"

echo "构建 Agent 二进制文件..."

# 检查 Go 是否安装
if ! command -v go &> /dev/null; then
    echo "错误: Go 未安装，请先安装 Go"
    exit 1
fi

echo "Go 版本: $(go version)"

# 下载依赖
echo "下载依赖..."
go mod download

# 构建 Linux amd64
echo "构建 Linux amd64..."
GOOS=linux GOARCH=amd64 go build -o myx-agent-linux-amd64 -ldflags="-s -w" main.go
echo "✓ myx-agent-linux-amd64 构建完成"

# 构建 Linux arm64
echo "构建 Linux arm64..."
GOOS=linux GOARCH=arm64 go build -o myx-agent-linux-arm64 -ldflags="-s -w" main.go
echo "✓ myx-agent-linux-arm64 构建完成"

echo ""
echo "所有二进制文件构建完成！"
echo "文件位置:"
ls -lh myx-agent-linux-*

