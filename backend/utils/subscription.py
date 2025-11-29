import base64
import json
import uuid
from urllib.parse import quote
from apps.proxies.models import Proxy


def generate_v2ray_link(proxy: Proxy, request) -> str:
    """生成V2Ray订阅链接"""
    server_host = proxy.server.host
    port = proxy.port
    uuid_str = str(proxy.uuid)

    if proxy.protocol == 'vless':
        link = f"vless://{uuid_str}@{server_host}:{port}"
        params = []
        if proxy.transport and proxy.transport != 'tcp':
            params.append(f"type={proxy.transport}")
        if proxy.path:
            params.append(f"path={quote(proxy.path)}")
        if proxy.host:
            params.append(f"host={quote(proxy.host)}")
        if proxy.enable_tls:
            params.append("security=tls")
            if proxy.sni:
                params.append(f"sni={quote(proxy.sni)}")
        if proxy.enable_reality:
            params.append("fp=chrome")
            if proxy.reality_public_key:
                params.append(f"pbk={proxy.reality_public_key}")
            if proxy.reality_short_id:
                params.append(f"sid={proxy.reality_short_id}")
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
            "net": proxy.transport or "tcp",
            "type": "none",
            "host": proxy.host or "",
            "path": proxy.path or "",
            "tls": "tls" if proxy.enable_tls else "none"
        }
        link = "vmess://" + base64.b64encode(json.dumps(vmess_config).encode()).decode()
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
        uuid_str = str(proxy.uuid)

        if proxy.protocol == 'vless':
            proxy_config = {
                "name": proxy.name,
                "type": "vless",
                "server": server_host,
                "port": port,
                "uuid": uuid_str,
                "tls": proxy.enable_tls,
                "network": proxy.transport or "tcp",
                "udp": True
            }

            if proxy.transport == 'ws':
                proxy_config["ws-opts"] = {
                    "path": proxy.path or "/"
                }
                if proxy.host:
                    proxy_config["ws-opts"]["headers"] = {
                        "Host": proxy.host
                    }
            elif proxy.transport == 'grpc':
                proxy_config["grpc-opts"] = {
                    "grpc-service-name": proxy.path or ""
                }

            if proxy.enable_tls:
                if proxy.sni:
                    proxy_config["servername"] = proxy.sni
                if proxy.enable_reality:
                    proxy_config["reality-opts"] = {
                        "public-key": proxy.reality_public_key or "",
                        "short-id": proxy.reality_short_id or ""
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
                "tls": proxy.enable_tls,
                "network": proxy.transport or "tcp"
            }

            if proxy.transport == 'ws':
                proxy_config["ws-opts"] = {
                    "path": proxy.path or "/"
                }
                if proxy.host:
                    proxy_config["ws-opts"]["headers"] = {
                        "Host": proxy.host
                    }

            if proxy.enable_tls and proxy.sni:
                proxy_config["servername"] = proxy.sni

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

