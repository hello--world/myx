package main

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
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
	PollMaxInterval      = 60 * time.Second   // 最大轮询间隔：60秒
)

type Config struct {
	ServerToken string
	SecretKey   string
	APIURL      string
	AgentToken  string
}

type RegisterRequest struct {
	ServerToken string `json:"server_token"`
	Version     string `json:"version,omitempty"`
	Hostname    string `json:"hostname,omitempty"`
	OS          string `json:"os,omitempty"`
}

type RegisterResponse struct {
	Token     string `json:"token"`
	SecretKey string `json:"secret_key"`
	ServerID  int    `json:"server_id"`
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
	Commands []CommandResponse `json:"commands"`
	Status   string            `json:"status"`
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

	// 启动Agent
	log.Println("Agent启动中...")
	log.Printf("API地址: %s", config.APIURL)
	log.Printf("Agent Token: %s", config.AgentToken)

	// 启动心跳和命令轮询
	go heartbeatLoop()
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
	config = Config{
		ServerToken: serverToken,
		SecretKey:   regResp.SecretKey,
		APIURL:      apiURL,
		AgentToken:  regResp.Token,
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

	return nil
}

func commandLoop() {
	for {
		// 生成随机间隔：5-60秒
		interval := randomDuration(PollMinInterval, PollMaxInterval)
		
		commands, err := pollCommands()
		if err != nil {
			log.Printf("轮询命令失败: %v", err)
			time.Sleep(interval)
			continue
		}

		for _, cmd := range commands {
			go executeCommand(cmd)
		}
		
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
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
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
