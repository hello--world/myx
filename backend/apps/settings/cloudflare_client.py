"""
Cloudflare API 客户端工具
"""
import requests
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class CloudflareAPIError(Exception):
    """Cloudflare API 错误"""
    pass


def get_cloudflare_api_headers(api_token: Optional[str] = None, 
                                api_key: Optional[str] = None,
                                api_email: Optional[str] = None) -> Dict[str, str]:
    """
    获取 Cloudflare API 请求头
    
    Args:
        api_token: API Token（推荐）
        api_key: Global API Key（不推荐）
        api_email: API Email（配合 api_key 使用）
    
    Returns:
        请求头字典
    """
    headers = {
        'Content-Type': 'application/json'
    }
    
    if api_token:
        # 使用 API Token（推荐方式）
        headers['Authorization'] = f'Bearer {api_token}'
    elif api_key and api_email:
        # 使用 Global API Key + Email（兼容旧方式）
        headers['X-Auth-Key'] = api_key
        headers['X-Auth-Email'] = api_email
    else:
        raise CloudflareAPIError('需要提供 API Token 或 (API Key + Email)')
    
    return headers


def list_zone_dns_records(zone_id: str, 
                          api_token: Optional[str] = None,
                          api_key: Optional[str] = None,
                          api_email: Optional[str] = None,
                          record_type: Optional[str] = None,
                          name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    列出指定 Zone 的所有 DNS 记录
    
    Args:
        zone_id: Cloudflare Zone ID
        api_token: API Token
        api_key: Global API Key
        api_email: API Email
        record_type: 过滤记录类型（如 'A', 'AAAA', 'CNAME'）
        name: 过滤记录名称（支持通配符，如 '*.example.com'）
    
    Returns:
        DNS 记录列表
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records'
    
    params = {}
    if record_type:
        params['type'] = record_type
    if name:
        params['name'] = name
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'Cloudflare API 错误: {error_msg}')
        
        return result.get('result', [])
    
    except requests.exceptions.RequestException as e:
        logger.error(f'查询 Cloudflare DNS 记录失败: {str(e)}')
        raise CloudflareAPIError(f'查询 DNS 记录失败: {str(e)}')


def get_used_subdomains(zone_id: str,
                        zone_name: str,
                        api_token: Optional[str] = None,
                        api_key: Optional[str] = None,
                        api_email: Optional[str] = None) -> List[str]:
    """
    获取指定 Zone 中已使用的子域名前缀列表
    
    Args:
        zone_id: Cloudflare Zone ID
        zone_name: Zone 名称（如 'example.com'）
        api_token: API Token
        api_key: Global API Key
        api_email: API Email
    
    Returns:
        已使用的子域名前缀列表（不包含域名后缀，如 ['www', 'api', 'chat']）
    """
    try:
        # 查询所有 DNS 记录
        records = list_zone_dns_records(zone_id, api_token, api_key, api_email)
        
        used_subdomains = set()
        
        for record in records:
            name = record.get('name', '')
            if not name:
                continue
            
            # 提取子域名前缀
            # 例如: 'www.example.com' -> 'www'
            #      'api.example.com' -> 'api'
            #      'example.com' -> '' (根域名，跳过)
            if name == zone_name:
                # 根域名，跳过
                continue
            
            if name.endswith(f'.{zone_name}'):
                # 子域名，提取前缀
                prefix = name.replace(f'.{zone_name}', '')
                if prefix:
                    used_subdomains.add(prefix)
            elif '.' not in name:
                # 只有前缀，没有域名后缀（可能是部分记录）
                used_subdomains.add(name)
        
        return sorted(list(used_subdomains))
    
    except CloudflareAPIError as e:
        logger.warning(f'获取已使用子域名失败: {str(e)}，将使用本地数据库记录')
        # 如果 API 查询失败，返回空列表（让调用方使用数据库记录）
        return []
    except Exception as e:
        logger.error(f'获取已使用子域名时发生未知错误: {str(e)}', exc_info=True)
        return []


def list_zones(api_token: Optional[str] = None,
               api_key: Optional[str] = None,
               api_email: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    列出所有 Cloudflare Zone
    
    Args:
        api_token: API Token
        api_key: Global API Key
        api_email: API Email
    
    Returns:
        Zone 列表
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = 'https://api.cloudflare.com/client/v4/zones'
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'Cloudflare API 错误: {error_msg}')
        
        return result.get('result', [])
    
    except requests.exceptions.RequestException as e:
        logger.error(f'查询 Cloudflare Zone 列表失败: {str(e)}')
        raise CloudflareAPIError(f'查询 Zone 列表失败: {str(e)}')


def create_dns_record(zone_id: str,
                     record_type: str,
                     name: str,
                     content: str,
                     api_token: Optional[str] = None,
                     api_key: Optional[str] = None,
                     api_email: Optional[str] = None,
                     ttl: int = 1,
                     proxied: bool = False) -> Dict[str, Any]:
    """
    创建 DNS 记录
    
    Args:
        zone_id: Zone ID
        record_type: 记录类型（A, AAAA, CNAME 等）
        name: 记录名称
        content: 记录内容（IP 地址或 CNAME 目标）
        api_token: API Token
        api_key: Global API Key
        api_email: API Email
        ttl: TTL 值（1 = 自动）
        proxied: 是否启用代理
    
    Returns:
        创建的 DNS 记录信息
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records'
    
    data = {
        'type': record_type,
        'name': name,
        'content': content,
        'ttl': ttl,
        'proxied': proxied
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'Cloudflare API 错误: {error_msg}')
        
        return result.get('result', {})
    
    except requests.exceptions.RequestException as e:
        logger.error(f'创建 DNS 记录失败: {str(e)}')
        raise CloudflareAPIError(f'创建 DNS 记录失败: {str(e)}')


def update_dns_record(zone_id: str,
                     record_id: str,
                     api_token: Optional[str] = None,
                     api_key: Optional[str] = None,
                     api_email: Optional[str] = None,
                     **updates) -> Dict[str, Any]:
    """
    更新 DNS 记录
    
    Args:
        zone_id: Zone ID
        record_id: 记录 ID
        api_token: API Token
        api_key: Global API Key
        api_email: API Email
        **updates: 要更新的字段（name, content, ttl, proxied 等）
    
    Returns:
        更新后的 DNS 记录信息
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}'
    
    try:
        response = requests.patch(url, headers=headers, json=updates, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'Cloudflare API 错误: {error_msg}')
        
        return result.get('result', {})
    
    except requests.exceptions.RequestException as e:
        logger.error(f'更新 DNS 记录失败: {str(e)}')
        raise CloudflareAPIError(f'更新 DNS 记录失败: {str(e)}')


def delete_dns_record(zone_id: str,
                     record_id: str,
                     api_token: Optional[str] = None,
                     api_key: Optional[str] = None,
                     api_email: Optional[str] = None) -> bool:
    """
    删除 DNS 记录
    
    Args:
        zone_id: Zone ID
        record_id: 记录 ID
        api_token: API Token
        api_key: Global API Key
        api_email: API Email
    
    Returns:
        是否删除成功
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{record_id}'
    
    try:
        response = requests.delete(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'Cloudflare API 错误: {error_msg}')
        
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f'删除 DNS 记录失败: {str(e)}')
        raise CloudflareAPIError(f'删除 DNS 记录失败: {str(e)}')


def create_origin_certificate(
    hostnames: List[str],
    api_token: Optional[str] = None,
    api_key: Optional[str] = None,
    api_email: Optional[str] = None,
    validity_days: int = 5475  # 15 年
) -> Dict[str, Any]:
    """
    创建 Cloudflare 源证书
    
    Args:
        hostnames: 域名列表，支持通配符（如 ['*.example.com', 'example.com']）
        api_token: API Token（推荐）
        api_key: Global API Key（备选）
        api_email: API Email（备选）
        validity_days: 有效期（天数，默认 15 年）
    
    Returns:
        包含证书 ID、证书内容、私钥的字典
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = 'https://api.cloudflare.com/client/v4/certificates'
    
    data = {
        'hostnames': hostnames,
        'requested_validity': validity_days
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'创建源证书失败: {error_msg}')
        
        cert_data = result.get('result', {})
        return {
            'id': cert_data.get('id'),
            'certificate': cert_data.get('certificate'),
            'private_key': cert_data.get('private_key'),
            'hostnames': cert_data.get('hostnames', []),
            'expires_on': cert_data.get('expires_on')
        }
    
    except requests.exceptions.RequestException as e:
        logger.error(f'创建源证书失败: {str(e)}')
        raise CloudflareAPIError(f'创建源证书失败: {str(e)}')


def get_origin_certificate(
    cert_id: str,
    api_token: Optional[str] = None,
    api_key: Optional[str] = None,
    api_email: Optional[str] = None
) -> Dict[str, Any]:
    """
    获取 Cloudflare 源证书详情
    
    Args:
        cert_id: 证书 ID
        api_token: API Token（推荐）
        api_key: Global API Key（备选）
        api_email: API Email（备选）
    
    Returns:
        证书信息字典
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = f'https://api.cloudflare.com/client/v4/certificates/{cert_id}'
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'获取源证书失败: {error_msg}')
        
        cert_data = result.get('result', {})
        return {
            'id': cert_data.get('id'),
            'certificate': cert_data.get('certificate'),
            'private_key': cert_data.get('private_key'),
            'hostnames': cert_data.get('hostnames', []),
            'expires_on': cert_data.get('expires_on')
        }
    
    except requests.exceptions.RequestException as e:
        logger.error(f'获取源证书失败: {str(e)}')
        raise CloudflareAPIError(f'获取源证书失败: {str(e)}')


def list_origin_certificates(
    api_token: Optional[str] = None,
    api_key: Optional[str] = None,
    api_email: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    列出所有源证书
    
    Returns:
        证书列表
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = 'https://api.cloudflare.com/client/v4/certificates'
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'列出源证书失败: {error_msg}')
        
        return result.get('result', [])
    
    except requests.exceptions.RequestException as e:
        logger.error(f'列出源证书失败: {str(e)}')
        raise CloudflareAPIError(f'列出源证书失败: {str(e)}')


def revoke_origin_certificate(
    cert_id: str,
    api_token: Optional[str] = None,
    api_key: Optional[str] = None,
    api_email: Optional[str] = None
) -> bool:
    """
    撤销 Cloudflare 源证书
    
    Returns:
        是否成功
    """
    headers = get_cloudflare_api_headers(api_token, api_key, api_email)
    
    url = f'https://api.cloudflare.com/client/v4/certificates/{cert_id}'
    
    try:
        response = requests.delete(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if not result.get('success', False):
            errors = result.get('errors', [])
            error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
            raise CloudflareAPIError(f'撤销源证书失败: {error_msg}')
        
        return True
    
    except requests.exceptions.RequestException as e:
        logger.error(f'撤销源证书失败: {str(e)}')
        raise CloudflareAPIError(f'撤销源证书失败: {str(e)}')

