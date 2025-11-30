import base64
import json
import uuid
from urllib.parse import quote
from apps.proxies.models import Proxy


def generate_v2ray_link(proxy: Proxy, request) -> str:
    """生成V2Ray订阅链接"""
    server_host = proxy.server.host
    port = proxy.port
    
    # 从 JSON 配置中提取信息
    settings = proxy.get_settings_dict()
    stream_settings = proxy.get_stream_settings_dict()
    
    # 提取 UUID（根据协议不同，字段名可能不同）
    if proxy.protocol == 'vless':
        uuid_str = settings.get('id') or settings.get('uuid', '')
    elif proxy.protocol == 'vmess':
        uuid_str = settings.get('id') or settings.get('uuid', '')
    elif proxy.protocol == 'trojan':
        uuid_str = settings.get('password', '')
    elif proxy.protocol == 'shadowsocks':
        uuid_str = settings.get('password', '')
    else:
        uuid_str = ''
    
    if not uuid_str:
        return ""
    
    # 提取传输设置
    network = stream_settings.get('network', 'tcp')
    ws_settings = stream_settings.get('wsSettings', {})
    grpc_settings = stream_settings.get('grpcSettings', {})
    path = ws_settings.get('path') or grpc_settings.get('serviceName', '')
    host = ws_settings.get('headers', {}).get('Host', '')
    
    # 提取 TLS 设置
    security = stream_settings.get('security', 'none')
    tls_settings = stream_settings.get('tlsSettings', {})
    reality_settings = stream_settings.get('realitySettings', {})
    sni = tls_settings.get('serverName') or reality_settings.get('serverName', '')
    enable_tls = security in ['tls', 'reality']
    enable_reality = security == 'reality'
    reality_public_key = reality_settings.get('publicKey', '')
    reality_short_id = reality_settings.get('shortIds', [])
    if reality_short_id and isinstance(reality_short_id, list):
        reality_short_id = reality_short_id[0] if reality_short_id else ''
    else:
        reality_short_id = str(reality_short_id) if reality_short_id else ''

    if proxy.protocol == 'vless':
        link = f"vless://{uuid_str}@{server_host}:{port}"
        params = []
        if network and network != 'tcp':
            params.append(f"type={network}")
        if path:
            params.append(f"path={quote(path)}")
        if host:
            params.append(f"host={quote(host)}")
        if enable_tls:
            params.append("security=tls")
            if sni:
                params.append(f"sni={quote(sni)}")
        if enable_reality:
            params.append("fp=chrome")
            if reality_public_key:
                params.append(f"pbk={reality_public_key}")
            if reality_short_id:
                params.append(f"sid={reality_short_id}")
        if params:
            link += "?" + "&".join(params)
        link += f"#{quote(proxy.name)}"
    elif proxy.protocol == 'vmess':
        vmess_config = {
            "v": "2",
            "ps": proxy.name,
            "add": server_host,
            "port": str(port),
            "id": uuid_str,
            "aid": "0",
            "scy": "auto",
            "net": network or "tcp",
            "type": "none",
            "host": host or "",
            "path": path or "",
            "tls": "tls" if enable_tls else "none"
        }
        link = "vmess://" + base64.b64encode(json.dumps(vmess_config).encode()).decode()
    elif proxy.protocol == 'trojan':
        link = f"trojan://{uuid_str}@{server_host}:{port}"
        params = []
        if network and network != 'tcp':
            params.append(f"type={network}")
        if path:
            params.append(f"path={quote(path)}")
        if host:
            params.append(f"host={quote(host)}")
        if enable_tls:
            params.append("security=tls")
            if sni:
                params.append(f"sni={quote(sni)}")
        if params:
            link += "?" + "&".join(params)
        link += f"#{quote(proxy.name)}"
    elif proxy.protocol == 'shadowsocks':
        method = settings.get('method', 'aes-256-gcm')
        link = f"ss://{base64.b64encode(f'{method}:{uuid_str}'.encode()).decode()}@{server_host}:{port}"
        params = []
        if enable_tls:
            params.append("tls=true")
        if params:
            link += "?" + "&".join(params)
        link += f"#{quote(proxy.name)}"
    else:
        return ""

    return link


def generate_v2ray_subscription(proxies, request) -> str:
    """生成V2Ray格式订阅（Base64编码）"""
    links = []
    for proxy in proxies:
        link = generate_v2ray_link(proxy, request)
        if link:
            links.append(link)
    return base64.b64encode("\n".join(links).encode()).decode()


def generate_clash_subscription(proxies, request) -> dict:
    """生成Clash格式订阅"""
    proxies_config = []
    proxy_groups = []

    for proxy in proxies:
        server_host = proxy.server.host
        port = proxy.port
        
        # 从 JSON 配置中提取信息
        settings = proxy.get_settings_dict()
        stream_settings = proxy.get_stream_settings_dict()
        
        # 提取 UUID
        if proxy.protocol == 'vless':
            uuid_str = settings.get('id') or settings.get('uuid', '')
        elif proxy.protocol == 'vmess':
            uuid_str = settings.get('id') or settings.get('uuid', '')
        elif proxy.protocol == 'trojan':
            uuid_str = settings.get('password', '')
        elif proxy.protocol == 'shadowsocks':
            uuid_str = settings.get('password', '')
            method = settings.get('method', 'aes-256-gcm')
        else:
            uuid_str = ''
        
        if not uuid_str:
            continue
        
        # 提取传输设置
        network = stream_settings.get('network', 'tcp')
        ws_settings = stream_settings.get('wsSettings', {})
        grpc_settings = stream_settings.get('grpcSettings', {})
        path = ws_settings.get('path') or grpc_settings.get('serviceName', '')
        host = ws_settings.get('headers', {}).get('Host', '')
        
        # 提取 TLS 设置
        security = stream_settings.get('security', 'none')
        tls_settings = stream_settings.get('tlsSettings', {})
        reality_settings = stream_settings.get('realitySettings', {})
        sni = tls_settings.get('serverName') or reality_settings.get('serverName', '')
        enable_tls = security in ['tls', 'reality']
        enable_reality = security == 'reality'
        reality_public_key = reality_settings.get('publicKey', '')
        reality_short_id = reality_settings.get('shortIds', [])
        if reality_short_id and isinstance(reality_short_id, list):
            reality_short_id = reality_short_id[0] if reality_short_id else ''
        else:
            reality_short_id = str(reality_short_id) if reality_short_id else ''

        if proxy.protocol == 'vless':
            proxy_config = {
                "name": proxy.name,
                "type": "vless",
                "server": server_host,
                "port": port,
                "uuid": uuid_str,
                "tls": enable_tls,
                "network": network or "tcp",
                "udp": True
            }

            if network == 'ws':
                proxy_config["ws-opts"] = {
                    "path": path or "/"
                }
                if host:
                    proxy_config["ws-opts"]["headers"] = {
                        "Host": host
                    }
            elif network == 'grpc':
                proxy_config["grpc-opts"] = {
                    "grpc-service-name": path or ""
                }

            if enable_tls:
                if sni:
                    proxy_config["servername"] = sni
                if enable_reality:
                    proxy_config["reality-opts"] = {
                        "public-key": reality_public_key or "",
                        "short-id": reality_short_id or ""
                    }

            proxies_config.append(proxy_config)

        elif proxy.protocol == 'vmess':
            proxy_config = {
                "name": proxy.name,
                "type": "vmess",
                "server": server_host,
                "port": port,
                "uuid": uuid_str,
                "alterId": 0,
                "cipher": "auto",
                "tls": enable_tls,
                "network": network or "tcp"
            }

            if network == 'ws':
                proxy_config["ws-opts"] = {
                    "path": path or "/"
                }
                if host:
                    proxy_config["ws-opts"]["headers"] = {
                        "Host": host
                    }

            if enable_tls and sni:
                proxy_config["servername"] = sni

            proxies_config.append(proxy_config)
        
        elif proxy.protocol == 'trojan':
            proxy_config = {
                "name": proxy.name,
                "type": "trojan",
                "server": server_host,
                "port": port,
                "password": uuid_str,
                "tls": enable_tls,
                "network": network or "tcp"
            }
            
            if network == 'ws':
                proxy_config["ws-opts"] = {
                    "path": path or "/"
                }
                if host:
                    proxy_config["ws-opts"]["headers"] = {
                        "Host": host
                    }
            
            if enable_tls and sni:
                proxy_config["sni"] = sni
            
            proxies_config.append(proxy_config)
        
        elif proxy.protocol == 'shadowsocks':
            proxy_config = {
                "name": proxy.name,
                "type": "ss",
                "server": server_host,
                "port": port,
                "cipher": method,
                "password": uuid_str
            }
            
            proxies_config.append(proxy_config)

    config = {
        "proxies": proxies_config,
        "proxy-groups": [
            {
                "name": "Proxy",
                "type": "select",
                "proxies": [p["name"] for p in proxies_config]
            }
        ],
        "rules": [
            "GEOIP,CN,DIRECT",
            "MATCH,Proxy"
        ]
    }

    return json.dumps(config, ensure_ascii=False, indent=2)

