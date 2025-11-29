import json
from apps.proxies.models import Proxy


def generate_xray_config(proxy: Proxy) -> dict:
    """生成单个代理的Xray配置（单个inbound，参考 xray-ui 设计）"""
    # 从 JSON 字段读取配置
    settings_dict = proxy.get_settings_dict()
    stream_settings_dict = proxy.get_stream_settings_dict()
    sniffing_dict = proxy.get_sniffing_dict()
    
    # 构建 inbound 配置
    inbound = {
        "port": proxy.port,
        "protocol": proxy.protocol,
        "tag": proxy.tag or f"inbound-{proxy.port}",
        "settings": settings_dict,
        "streamSettings": stream_settings_dict,
        "sniffing": sniffing_dict
    }
    
    # 如果有 listen，添加它
    if proxy.listen:
        inbound["listen"] = proxy.listen
    
    return inbound


def generate_xray_full_config(proxies: list) -> dict:
    """生成完整的Xray配置文件（包含所有inbounds，参考 xray-ui 的 config.json）"""
    config = {
        "log": {
            "loglevel": "warning",
            "access": "none",
            "dnsLog": False
        },
        "api": {
            "services": [
                "HandlerService",
                "LoggerService",
                "StatsService"
            ],
            "tag": "api"
        },
        "inbounds": [],
        "outbounds": [
            {
                "protocol": "freedom",
                "settings": {},
                "tag": "direct"
            },
            {
                "protocol": "blackhole",
                "tag": "blocked"
            }
        ],
        "policy": {
            "system": {
                "statsInboundDownlink": True,
                "statsInboundUplink": True,
                "statsOutboundDownlink": False,
                "statsOutboundUplink": False
            },
            "levels": {
                "0": {
                    "uplinkOnly": 1,
                    "downlinkOnly": 1,
                    "handshake": 2,
                    "connIdle": 120
                }
            }
        },
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": []
        },
        "stats": {}
    }

    # 添加所有启用的代理
    for proxy in proxies:
        if proxy.enable and proxy.status == 'active':
            inbound = generate_xray_config(proxy)
            config["inbounds"].append(inbound)

    return config


def _generate_protocol_settings_legacy(proxy: Proxy) -> dict:
    """生成协议特定的settings配置"""
    if proxy.protocol == 'vless':
        return {
            "clients": [
                {
                    "id": str(proxy.uuid),
                    "flow": _get_vless_flow(proxy),
                    "email": f"{proxy.name}@myx"
                }
            ],
            "decryption": "none"
        }
    elif proxy.protocol == 'vmess':
        return {
            "clients": [
                {
                    "id": str(proxy.uuid),
                    "alterId": 0,
                    "email": f"{proxy.name}@myx",
                    "security": "auto"
                }
            ],
            "disableInsecureEncryption": False
        }
    elif proxy.protocol == 'trojan':
        return {
            "clients": [
                {
                    "password": str(proxy.uuid),
                    "email": f"{proxy.name}@myx",
                    "flow": ""
                }
            ]
        }
    elif proxy.protocol == 'shadowsocks':
        return {
            "clients": [
                {
                    "method": "aes-256-gcm",
                    "password": str(proxy.uuid),
                    "email": f"{proxy.name}@myx"
                }
            ],
            "network": "tcp,udp"
        }
    else:
        return {}


def _get_vless_flow(proxy: Proxy) -> str:
    """获取VLESS的flow配置"""
    if not proxy.enable_tls:
        return ""
    
    # 如果使用TCP传输且启用TLS，可以使用xtls-rprx-vision
    if proxy.transport == 'tcp':
        return "xtls-rprx-vision"
    
    return ""


def _generate_stream_settings(proxy: Proxy) -> dict:
    """生成streamSettings配置"""
    stream_settings = {
        "network": proxy.transport
    }

    # 根据传输方式设置对应的配置
    if proxy.transport == 'ws':
        stream_settings["wsSettings"] = {
            "path": proxy.path or "/",
            "headers": {}
        }
        if proxy.host:
            stream_settings["wsSettings"]["headers"]["Host"] = proxy.host
    
    elif proxy.transport == 'grpc':
        stream_settings["grpcSettings"] = {
            "serviceName": proxy.path or "",
            "multiMode": False
        }
    
    elif proxy.transport == 'quic':
        stream_settings["quicSettings"] = {
            "security": "none",
            "key": "",
            "type": "none"
        }
    
    elif proxy.transport == 'h2' or proxy.transport == 'http':
        stream_settings["network"] = "http"
        stream_settings["httpSettings"] = {
            "path": proxy.path or "/",
            "host": [proxy.host] if proxy.host else []
        }
    
    elif proxy.transport == 'tcp':
        # TCP 可以配置 header
        stream_settings["tcpSettings"] = {
            "header": {
                "type": "none"
            }
        }
    
    # TLS/REALITY 配置
    if proxy.enable_tls:
        if proxy.enable_reality:
            # REALITY 配置
            reality_settings = {
                "show": False,
                "dest": proxy.sni or proxy.host or "www.microsoft.com:443",
                "xver": 0,
                "serverNames": [proxy.sni or proxy.host] if (proxy.sni or proxy.host) else [],
                "privateKey": proxy.reality_public_key or "",
                "shortIds": [proxy.reality_short_id] if proxy.reality_short_id else [""],
                "spiderX": "/"
            }
            
            stream_settings["security"] = "reality"
            stream_settings["realitySettings"] = reality_settings
            
            if proxy.sni or proxy.host:
                stream_settings["realitySettings"]["serverName"] = proxy.sni or proxy.host
        else:
            # 普通 TLS 配置
            tls_settings = {
                "certificates": [
                    {
                        "certificateFile": "/usr/local/etc/xray/cert.pem",
                        "keyFile": "/usr/local/etc/xray/key.pem"
                    }
                ],
                "alpn": ["h2", "http/1.1"]
            }
            
            if proxy.sni or proxy.host:
                tls_settings["serverName"] = proxy.sni or proxy.host
            
            stream_settings["security"] = "tls"
            stream_settings["tlsSettings"] = tls_settings

    return stream_settings


def generate_xray_config_json(proxy: Proxy) -> str:
    """生成Xray配置的JSON字符串"""
    config = generate_xray_full_config([proxy])
    return json.dumps(config, indent=2, ensure_ascii=False)


def generate_xray_config_json_for_proxies(proxies: list) -> str:
    """为多个代理生成完整的Xray配置JSON字符串"""
    config = generate_xray_full_config(proxies)
    return json.dumps(config, indent=2, ensure_ascii=False)
