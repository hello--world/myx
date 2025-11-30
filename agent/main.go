package main

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	cryptoRand "crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"time"

	"golang.org/x/crypto/pbkdf2"
)

const (
	DefaultAPIURL        = "http://localhost:8000/api/agents"
	HeartbeatMinInterval = 30 * time.Second  // 最小心跳间隔：30秒
	HeartbeatMaxInterval = 300 * time.Second // 最大心跳间隔：300秒
	PollMinInterval      = 5 * time.Second   // 最小轮询间隔：5秒
	PollMaxInterval      = 60 * time.Second  // 最大轮询间隔：60秒
)

type Config struct {
	ServerToken          string
	SecretKey            string
	APIURL               string
	AgentToken           string
	HeartbeatMode        string // 心跳模式: "push" 或 "pull"
	HeartbeatMinInterval int    // 最小心跳间隔（秒）
	HeartbeatMaxInterval int    // 最大心跳间隔（秒）
	PollMinInterval      int    // 最小轮询间隔（秒）
	PollMaxInterval      int    // 最大轮询间隔（秒）
}

type RegisterRequest struct {
	ServerToken string `json:"server_token"`
	Version     string `json:"version,omitempty"`
	Hostname    string `json:"hostname,omitempty"`
	OS          string `json:"os,omitempty"`
}

type RegisterResponse struct {
	Token         string `json:"token"`
	SecretKey     string `json:"secret_key"`
	ServerID      int    `json:"server_id"`
	HeartbeatMode string `json:"heartbeat_mode,omitempty"` // 心跳模式
}

type HeartbeatRequest struct {
	Status  string `json:"status,omitempty"`
	Version string `json:"version,omitempty"`
}

type CommandRequest struct {
	Command string   `json:"command"`
	Args    []string `json:"args,omitempty"`
	Timeout int      `json:"timeout,omitempty"`
}

type CommandResponse struct {
	ID      int      `json:"id"`
	Command string   `json:"command"`
	Args    []string `json:"args"`
	Timeout int      `json:"timeout"`
}

type PollResponse struct {
	Commands      []CommandResponse `json:"commands"`
	Status        string            `json:"status"`
	HeartbeatMode string            `json:"heartbeat_mode,omitempty"` // 心跳模式
	Config        *AgentConfig      `json:"config,omitempty"`
}

type AgentConfig struct {
	HeartbeatMinInterval int `json:"heartbeat_min_interval"`
	HeartbeatMaxInterval int `json:"heartbeat_max_interval"`
	PollMinInterval      int `json:"poll_min_interval"`
	PollMaxInterval      int `json:"poll_max_interval"`
}

type HeartbeatResponse struct {
	Status        string       `json:"status"`
	HeartbeatMode string       `json:"heartbeat_mode,omitempty"` // 心跳模式
	Config        *AgentConfig `json:"config,omitempty"`
}

var (
	config     Config
	httpClient = &http.Client{Timeout: 10 * time.Second}
)

func main() {
	var serverToken = flag.String("token", "", "服务器Token（用于首次注册）")
	var apiURL = flag.String("api", DefaultAPIURL, "API服务器地址")
	var configFile = flag.String("config", "/etc/myx-agent/config.json", "配置文件路径")
	flag.Parse()

	// 加载配置
	if *serverToken != "" {
		// 首次注册
		if err := register(*serverToken, *apiURL); err != nil {
			log.Fatalf("注册失败: %v", err)
		}
		return
	}

	// 从配置文件加载
	if err := loadConfig(*configFile); err != nil {
		log.Fatalf("加载配置失败: %v", err)
	}

	// 初始化随机数种子
	rand.Seed(time.Now().UnixNano())

	// 启动Agent
	log.Println("Agent启动中...")
	log.Printf("API地址: %s", config.APIURL)
	log.Printf("Agent Token: %s", config.AgentToken)
	log.Printf("心跳模式: %s", config.HeartbeatMode)

	// 启动心跳和命令轮询
	// 只有在推送模式下才启动心跳循环
	if config.HeartbeatMode != "pull" {
		go heartbeatLoop()
		log.Println("心跳模式: 推送模式（Agent主动发送心跳）")
	} else {
		log.Println("心跳模式: 拉取模式（中心服务器主动检查），不发送心跳")
	}
	commandLoop()
}

func register(serverToken, apiURL string) error {
	hostname, _ := os.Hostname()
	req := RegisterRequest{
		ServerToken: serverToken,
		Version:     "1.0.0",
		Hostname:    hostname,
		OS:          runtime.GOOS,
	}

	jsonData, _ := json.Marshal(req)
	resp, err := http.Post(apiURL+"/register/", "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("注册失败: %s", string(body))
	}

	var regResp RegisterResponse
	if err := json.NewDecoder(resp.Body).Decode(&regResp); err != nil {
		return err
	}

	// 保存配置
	heartbeatMode := regResp.HeartbeatMode
	if heartbeatMode == "" {
		heartbeatMode = "push" // 默认推送模式
	}
	config = Config{
		ServerToken:   serverToken,
		SecretKey:     regResp.SecretKey,
		APIURL:        apiURL,
		AgentToken:    regResp.Token,
		HeartbeatMode: heartbeatMode,
	}

	// 创建配置目录
	configDir := "/etc/myx-agent"
	os.MkdirAll(configDir, 0755)

	// 保存配置文件
	configData, _ := json.MarshalIndent(config, "", "  ")
	configPath := configDir + "/config.json"
	if err := os.WriteFile(configPath, configData, 0600); err != nil {
		return fmt.Errorf("保存配置失败: %v", err)
	}

	log.Printf("注册成功！")
	log.Printf("配置文件已保存到: %s", configPath)
	log.Printf("Agent Token: %s", regResp.Token)
	return nil
}

func loadConfig(configFile string) error {
	data, err := os.ReadFile(configFile)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, &config)
}

func heartbeatLoop() {
	for {
		// 生成随机间隔：30-300秒
		interval := randomDuration(HeartbeatMinInterval, HeartbeatMaxInterval)
		log.Printf("下次心跳将在 %v 后发送", interval)

		time.Sleep(interval)

		if err := sendHeartbeat(); err != nil {
			log.Printf("心跳失败: %v", err)
		}
	}
}

func sendHeartbeat() error {
	req := HeartbeatRequest{
		Status:  "online",
		Version: "1.0.0",
	}

	jsonData, _ := json.Marshal(req)
	httpReq, _ := http.NewRequest("POST", config.APIURL+"/heartbeat/", bytes.NewBuffer(jsonData))
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("X-Agent-Token", config.AgentToken)

	resp, err := httpClient.Do(httpReq)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("心跳失败: %d", resp.StatusCode)
	}

	// 解析响应，更新配置
	var heartbeatResp HeartbeatResponse
	if err := json.NewDecoder(resp.Body).Decode(&heartbeatResp); err == nil {
		// 更新心跳模式
		if heartbeatResp.HeartbeatMode != "" {
			config.HeartbeatMode = heartbeatResp.HeartbeatMode
		}
		// 更新其他配置
		if heartbeatResp.Config != nil {
			updateConfig(heartbeatResp.Config)
		}
	}

	return nil
}

func commandLoop() {
	for {
		// 从配置获取间隔范围（秒转纳秒）
		minInterval := time.Duration(config.PollMinInterval) * time.Second
		maxInterval := time.Duration(config.PollMaxInterval) * time.Second
		if minInterval == 0 {
			minInterval = PollMinInterval
		}
		if maxInterval == 0 {
			maxInterval = PollMaxInterval
		}

		commands, err := pollCommands()
		if err != nil {
			log.Printf("轮询命令失败: %v", err)
			// 使用默认间隔
			interval := randomDuration(minInterval, maxInterval)
			time.Sleep(interval)
			continue
		}

		for _, cmd := range commands {
			go executeCommand(cmd)
		}

		// 生成随机间隔
		interval := randomDuration(minInterval, maxInterval)
		time.Sleep(interval)
	}
}

func pollCommands() ([]CommandResponse, error) {
	httpReq, _ := http.NewRequest("GET", config.APIURL+"/poll/", nil)
	httpReq.Header.Set("X-Agent-Token", config.AgentToken)

	resp, err := httpClient.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("轮询失败: %d", resp.StatusCode)
	}

	var pollResp PollResponse
	if err := json.NewDecoder(resp.Body).Decode(&pollResp); err != nil {
		return nil, err
	}

	// 更新心跳模式（如果服务器返回了）
	if pollResp.HeartbeatMode != "" {
		oldMode := config.HeartbeatMode
		config.HeartbeatMode = pollResp.HeartbeatMode
		if oldMode != pollResp.HeartbeatMode {
			log.Printf("心跳模式已更新: %s -> %s", oldMode, pollResp.HeartbeatMode)
			// 注意：如果从push切换到pull，心跳循环已经在运行，但不会再发送
			// 如果从pull切换到push，需要重启Agent才能启动心跳循环
		}
	}

	// 更新配置（如果服务器返回了新配置）
	if pollResp.Config != nil {
		updateConfig(pollResp.Config)
	}

	return pollResp.Commands, nil
}

func executeCommand(cmd CommandResponse) {
	log.Printf("执行命令 [ID:%d]: %s %v", cmd.ID, cmd.Command, cmd.Args)

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cmd.Timeout)*time.Second)
	defer cancel()

	execCmd := exec.CommandContext(ctx, cmd.Command, cmd.Args...)
	var stdout, stderr bytes.Buffer
	execCmd.Stdout = &stdout
	execCmd.Stderr = &stderr

	err := execCmd.Run()

	success := err == nil
	stdoutStr := stdout.String()
	stderrStr := stderr.String()

	log.Printf("命令执行完成 [ID:%d]: success=%v", cmd.ID, success)
	if !success {
		log.Printf("错误: %v", err)
	}

	// 发送执行结果到API
	sendCommandResult(cmd.ID, success, stdoutStr, stderrStr, err)
}

func sendCommandResult(commandID int, success bool, stdout, stderr string, err error) {
	result := map[string]interface{}{
		"success": success,
		"stdout":  stdout,
		"stderr":  stderr,
	}

	if err != nil {
		result["error"] = err.Error()
	}

	jsonData, _ := json.Marshal(result)
	httpReq, _ := http.NewRequest("POST",
		fmt.Sprintf("%s/commands/%d/result/", config.APIURL, commandID),
		bytes.NewBuffer(jsonData))
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("X-Agent-Token", config.AgentToken)

	resp, err := httpClient.Do(httpReq)
	if err != nil {
		log.Printf("发送命令结果失败: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("发送命令结果失败: %d", resp.StatusCode)
	}
}

// updateConfig 更新 Agent 配置（线程安全）
func updateConfig(newConfig *AgentConfig) {
	if newConfig == nil {
		return
	}
	if newConfig.HeartbeatMinInterval > 0 {
		config.HeartbeatMinInterval = newConfig.HeartbeatMinInterval
	}
	if newConfig.HeartbeatMaxInterval > 0 {
		config.HeartbeatMaxInterval = newConfig.HeartbeatMaxInterval
	}
	if newConfig.PollMinInterval > 0 {
		config.PollMinInterval = newConfig.PollMinInterval
	}
	if newConfig.PollMaxInterval > 0 {
		config.PollMaxInterval = newConfig.PollMaxInterval
	}
	log.Printf("配置已更新: 心跳 %d-%d秒, 轮询 %d-%d秒",
		config.HeartbeatMinInterval, config.HeartbeatMaxInterval,
		config.PollMinInterval, config.PollMaxInterval)
}

// randomDuration 生成指定范围内的随机时间间隔
func randomDuration(min, max time.Duration) time.Duration {
	if min >= max {
		return min
	}
	// 生成随机数（纳秒）
	randomNanos := rand.Int63n(int64(max-min)) + int64(min)
	return time.Duration(randomNanos)
}

// 加密函数（使用AES-256-GCM）
func encrypt(plaintext, key string) (string, error) {
	keyBytes := pbkdf2.Key([]byte(key), []byte("myx-salt"), 4096, 32, sha256.New)
	block, err := aes.NewCipher(keyBytes)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	nonce := make([]byte, gcm.NonceSize())
	if _, err := io.ReadFull(cryptoRand.Reader, nonce); err != nil {
		return "", err
	}

	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// 解密函数
func decrypt(ciphertextStr, key string) (string, error) {
	keyBytes := pbkdf2.Key([]byte(key), []byte("myx-salt"), 4096, 32, sha256.New)
	block, err := aes.NewCipher(keyBytes)
	if err != nil {
		return "", err
	}

	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}

	data, err := base64.StdEncoding.DecodeString(ciphertextStr)
	if err != nil {
		return "", err
	}

	nonceSize := gcm.NonceSize()
	if len(data) < nonceSize {
		return "", fmt.Errorf("ciphertext too short")
	}

	nonce, ciphertextBytes := data[:nonceSize], data[nonceSize:]

	plaintext, err := gcm.Open(nil, nonce, ciphertextBytes, nil)
	if err != nil {
		return "", err
	}

	return string(plaintext), nil
}
