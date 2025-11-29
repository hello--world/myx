.PHONY: build clean install linux-amd64 linux-arm64 all

build:
	go build -o myx-agent -ldflags="-s -w" main.go

clean:
	rm -f myx-agent myx-agent-linux-amd64 myx-agent-linux-arm64

install: build
	sudo cp myx-agent /usr/local/bin/
	sudo chmod +x /usr/local/bin/myx-agent

linux-amd64:
	@echo "构建 Linux amd64..."
	GOOS=linux GOARCH=amd64 go build -o myx-agent-linux-amd64 -ldflags="-s -w" main.go
	@echo "✓ myx-agent-linux-amd64 构建完成"

linux-arm64:
	@echo "构建 Linux arm64..."
	GOOS=linux GOARCH=arm64 go build -o myx-agent-linux-arm64 -ldflags="-s -w" main.go
	@echo "✓ myx-agent-linux-arm64 构建完成"

all: linux-amd64 linux-arm64
	@echo ""
	@echo "所有二进制文件构建完成！"
	@ls -lh myx-agent-linux-*

