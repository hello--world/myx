from apps.proxies.models import Proxy


def generate_caddy_config(proxy: Proxy, domain: str = None, cert_path: str = None) -> str:
    """生成Caddy配置"""
    config_lines = []

    if domain:
        config_lines.append(f"{domain} {{")
    else:
        config_lines.append(":80 {")

    # 自动HTTPS
    if domain and not cert_path:
        config_lines.append("    tls {")
        config_lines.append("        on_demand")
        config_lines.append("    }")

    # 反代理配置
    config_lines.append("    reverse_proxy localhost:{}".format(proxy.port))

    # 如果使用自定义证书
    if cert_path:
        config_lines.append("    tls {} {}".format(
            cert_path + "/cert.pem",
            cert_path + "/key.pem"
        ))

    config_lines.append("}")

    return "\n".join(config_lines)


def generate_caddy_full_config(proxies: list, domains: dict = None) -> str:
    """生成完整的Caddy配置文件"""
    config_sections = []

    for proxy in proxies:
        domain = domains.get(proxy.id) if domains else None
        config_sections.append(generate_caddy_config(proxy, domain))

    return "\n\n".join(config_sections)

