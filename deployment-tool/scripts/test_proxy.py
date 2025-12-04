#!/usr/bin/env python3
"""
测试代理节点连接（使用xray客户端自测）
"""
import os
import sys
import json
import subprocess
import time
import signal
import tempfile
import shutil
from pathlib import Path


def find_xray_binary():
    """查找xray二进制文件路径"""
    xray_path = shutil.which('xray')
    if xray_path:
        return xray_path
    
    # 尝试常见路径
    common_paths = [
        '/usr/local/bin/xray',
        '/usr/bin/xray',
        '/opt/xray/xray'
    ]
    
    for path in common_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    
    return None


def validate_config(xray_bin, config_file):
    """验证xray配置文件"""
    print(f"[信息] 开始验证配置文件: {config_file}")
    print(f"[信息] 使用Xray二进制文件: {xray_bin}")
    
    try:
        print("[信息] 执行配置验证命令...")
        result = subprocess.run(
            [xray_bin, '-test', '-config', config_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        print(f"[信息] 验证命令返回码: {result.returncode}")
        
        if result.returncode == 0:
            print("[成功] 配置验证通过")
            if result.stdout:
                print(f"[信息] 验证输出:\n{result.stdout}")
            return True
        else:
            print(f"[错误] 配置验证失败 (返回码: {result.returncode})")
            if result.stderr:
                print(f"[错误] 错误输出:\n{result.stderr}")
            if result.stdout:
                print(f"[信息] 标准输出:\n{result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print("[错误] 配置验证超时（超过10秒）")
        return False
    except Exception as e:
        print(f"[错误] 配置验证异常: {e}")
        import traceback
        print(f"[错误] 异常堆栈:\n{traceback.format_exc()}")
        return False


def start_xray_client(xray_bin, config_file, log_file):
    """启动xray客户端"""
    print(f"[信息] 准备启动Xray客户端...")
    print(f"[信息] 配置文件: {config_file}")
    print(f"[信息] 日志文件: {log_file}")
    
    try:
        print("[信息] 执行Xray客户端启动命令...")
        # 启动xray客户端（后台运行）
        process = subprocess.Popen(
            [xray_bin, '-config', config_file],
            stdout=open(log_file, 'w'),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        
        print(f"[信息] Xray客户端进程已创建，PID: {process.pid}")
        print("[信息] 等待进程启动（3秒）...")
        
        # 等待进程启动
        time.sleep(3)
        
        # 检查进程是否还在运行
        poll_result = process.poll()
        if poll_result is not None:
            # 进程已退出，读取日志
            print(f"[错误] Xray客户端进程已退出，返回码: {poll_result}")
            with open(log_file, 'r') as f:
                log_content = f.read()
            print(f"[错误] Xray客户端日志:\n{log_content}")
            return None
        
        print(f"[成功] Xray客户端已启动，进程ID: {process.pid}")
        print("[信息] 客户端正在运行，准备进行连接测试...")
        return process
    except FileNotFoundError:
        print(f"[错误] 未找到Xray二进制文件: {xray_bin}")
        return None
    except PermissionError:
        print(f"[错误] 没有执行权限: {xray_bin}")
        return None
    except Exception as e:
        print(f"[错误] 启动Xray客户端异常: {e}")
        import traceback
        print(f"[错误] 异常堆栈:\n{traceback.format_exc()}")
        return None


def test_proxy_connection(test_url='http://www.google.com', timeout=10):
    """通过本地SOCKS代理测试连接"""
    print(f"[信息] 开始测试代理连接...")
    print(f"[信息] 测试URL: {test_url}")
    print(f"[信息] SOCKS代理地址: socks5://127.0.0.1:10808")
    print(f"[信息] 连接超时: {timeout}秒")
    
    try:
        print("[信息] 执行curl命令通过SOCKS代理测试连接...")
        # 使用curl通过SOCKS代理测试连接
        result = subprocess.run(
            [
                'curl',
                '-x', 'socks5://127.0.0.1:10808',
                '--connect-timeout', str(timeout),
                '-s',
                '-o', '/dev/null',
                '-w', '%{http_code}',
                test_url
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5
        )
        
        print(f"[信息] curl命令返回码: {result.returncode}")
        
        if result.returncode == 0:
            http_code = result.stdout.strip()
            print(f"[信息] 获取到HTTP状态码: {http_code}")
            
            if http_code in ['200', '301', '302']:
                print(f"[成功] 代理连接测试成功 (HTTP状态码: {http_code})")
                if http_code == '200':
                    print("[信息] 服务器返回200 OK，连接正常")
                elif http_code in ['301', '302']:
                    print(f"[信息] 服务器返回{http_code}重定向，连接正常")
                return True
            else:
                print(f"[失败] 代理连接测试失败 (HTTP状态码: {http_code})")
                print(f"[信息] 状态码说明: {http_code} 表示请求未成功")
                if result.stderr:
                    print(f"[错误] curl错误输出: {result.stderr}")
                return False
        else:
            print(f"[失败] curl命令执行失败 (返回码: {result.returncode})")
            if result.stderr:
                print(f"[错误] curl错误输出:\n{result.stderr}")
            if result.stdout:
                print(f"[信息] curl标准输出:\n{result.stdout}")
            return False
    except subprocess.TimeoutExpired:
        print(f"[失败] 代理连接测试超时（超过{timeout + 5}秒）")
        print("[信息] 可能原因: 代理连接速度慢、网络问题或代理配置错误")
        return False
    except FileNotFoundError:
        print("[错误] curl命令未找到，无法进行连接测试")
        print("[信息] 请确保系统已安装curl命令")
        return False
    except Exception as e:
        print(f"[错误] 代理连接测试异常: {e}")
        import traceback
        print(f"[错误] 异常堆栈:\n{traceback.format_exc()}")
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("[信息] 开始代理节点连接测试")
    print("=" * 60)
    
    # 检查参数
    if len(sys.argv) < 2:
        print("[错误] 缺少配置文件路径参数")
        print("用法: python3 test_proxy.py <config_json>")
        sys.exit(1)
    
    config_json = sys.argv[1]
    print(f"[信息] 接收到的配置参数长度: {len(config_json)} 字符")
    
    # 查找xray二进制文件
    print("[信息] 查找Xray二进制文件...")
    xray_bin = find_xray_binary()
    if not xray_bin:
        print("[错误] 未找到xray二进制文件")
        print("[信息] 已检查的路径:")
        print("  - PATH环境变量")
        print("  - /usr/local/bin/xray")
        print("  - /usr/bin/xray")
        print("  - /opt/xray/xray")
        sys.exit(1)
    
    print(f"[成功] 找到Xray二进制文件: {xray_bin}")
    
    # 创建临时目录
    print("[信息] 创建临时目录...")
    temp_dir = tempfile.mkdtemp(prefix='xray_test_')
    config_file = os.path.join(temp_dir, 'client_config.json')
    log_file = os.path.join(temp_dir, 'xray_client.log')
    print(f"[信息] 临时目录: {temp_dir}")
    print(f"[信息] 配置文件路径: {config_file}")
    print(f"[信息] 日志文件路径: {log_file}")
    
    try:
        # 写入配置文件
        print("[信息] 解析并写入配置文件...")
        try:
            # 如果传入的是JSON字符串，先解析
            if isinstance(config_json, str) and config_json.strip().startswith('{'):
                print("[信息] 检测到JSON字符串格式，开始解析...")
                config_data = json.loads(config_json)
                print("[成功] JSON解析成功")
            else:
                # 假设是文件路径
                print(f"[信息] 检测到文件路径格式: {config_json}")
                if not os.path.exists(config_json):
                    print(f"[错误] 配置文件不存在: {config_json}")
                    sys.exit(1)
                with open(config_json, 'r') as f:
                    config_data = json.load(f)
                print("[成功] 从文件读取配置成功")
            
            # 显示配置摘要
            print("[信息] 配置摘要:")
            if 'outbounds' in config_data:
                outbounds = config_data['outbounds']
                if outbounds:
                    outbound = outbounds[0]
                    print(f"  - 协议: {outbound.get('protocol', 'unknown')}")
                    if 'streamSettings' in outbound:
                        stream = outbound['streamSettings']
                        print(f"  - 传输方式: {stream.get('network', 'unknown')}")
                        print(f"  - 安全: {stream.get('security', 'none')}")
            
            with open(config_file, 'w') as f:
                json.dump(config_data, f, indent=2)
            print(f"[成功] 配置文件已写入: {config_file}")
            
        except json.JSONDecodeError as e:
            print(f"[错误] JSON配置解析失败: {e}")
            print(f"[信息] 配置内容前100字符: {config_json[:100]}...")
            sys.exit(1)
        except Exception as e:
            print(f"[错误] 读取配置文件失败: {e}")
            import traceback
            print(f"[错误] 异常堆栈:\n{traceback.format_exc()}")
            sys.exit(1)
        
        # 验证配置
        print("\n" + "=" * 60)
        print("[步骤 1/3] 验证配置文件")
        print("=" * 60)
        if not validate_config(xray_bin, config_file):
            print("[失败] 配置验证失败，测试终止")
            sys.exit(1)
        
        # 启动xray客户端
        print("\n" + "=" * 60)
        print("[步骤 2/3] 启动Xray客户端")
        print("=" * 60)
        xray_process = start_xray_client(xray_bin, config_file, log_file)
        if not xray_process:
            print("[失败] Xray客户端启动失败，测试终止")
            sys.exit(1)
        
        try:
            # 测试代理连接
            print("\n" + "=" * 60)
            print("[步骤 3/3] 测试代理连接")
            print("=" * 60)
            test_result = test_proxy_connection()
            
            print("\n" + "=" * 60)
            print("[信息] 测试结果汇总")
            print("=" * 60)
            if test_result:
                print("[成功] 测试完成：代理节点工作正常")
                print("[信息] 所有测试步骤均通过")
                sys.exit(0)
            else:
                print("[失败] 测试完成：代理节点连接失败")
                print("[信息] 请检查:")
                print("  1. 代理节点配置是否正确")
                print("  2. 代理节点服务是否正常运行")
                print("  3. 网络连接是否正常")
                print("  4. 防火墙规则是否允许连接")
                sys.exit(1)
        finally:
            # 停止xray客户端进程
            print("\n[信息] 开始清理资源...")
            try:
                print(f"[信息] 停止Xray客户端进程 (PID: {xray_process.pid})...")
                xray_process.terminate()
                # 等待进程结束（最多5秒）
                try:
                    xray_process.wait(timeout=5)
                    print("[成功] Xray客户端进程已正常停止")
                except subprocess.TimeoutExpired:
                    # 强制杀死
                    print("[警告] 进程未在5秒内停止，强制终止...")
                    xray_process.kill()
                    xray_process.wait()
                    print("[信息] Xray客户端进程已强制终止")
            except ProcessLookupError:
                print("[信息] 进程已不存在，无需停止")
            except Exception as e:
                print(f"[警告] 停止Xray客户端进程时出错: {e}")
                import traceback
                print(f"[警告] 异常堆栈:\n{traceback.format_exc()}")
    finally:
        # 清理临时文件
        print("[信息] 清理临时文件...")
        try:
            shutil.rmtree(temp_dir)
            print(f"[成功] 临时文件已清理: {temp_dir}")
        except Exception as e:
            print(f"[警告] 清理临时文件时出错: {e}")
            import traceback
            print(f"[警告] 异常堆栈:\n{traceback.format_exc()}")
        
        print("\n" + "=" * 60)
        print("[信息] 测试流程结束")
        print("=" * 60)


if __name__ == '__main__':
    main()

