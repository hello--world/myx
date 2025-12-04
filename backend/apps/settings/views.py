from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import logging
from .models import AppSettings, SubdomainWord, CloudflareAccount, CloudflareZone, CloudflareDNSRecord
from .serializers import (AppSettingsSerializer, SubdomainWordSerializer, CloudflareAccountSerializer,
                         CloudflareZoneSerializer, CloudflareDNSRecordSerializer)

logger = logging.getLogger(__name__)


class AppSettingsViewSet(viewsets.ModelViewSet):
    """应用设置视图集"""
    queryset = AppSettings.objects.all()
    serializer_class = AppSettingsSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        """获取或创建设置实例（单例）"""
        return AppSettings.get_settings()

    def list(self, request, *args, **kwargs):
        """获取设置"""
        settings = AppSettings.get_settings()
        serializer = self.get_serializer(settings)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """获取设置详情"""
        return self.list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """更新设置（单例，所以用create来更新）"""
        settings = AppSettings.get_settings()
        serializer = self.get_serializer(settings, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        """更新设置"""
        settings = self.get_object()
        serializer = self.get_serializer(settings, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        """部分更新设置"""
        return self.update(request, *args, **kwargs)


class SubdomainWordViewSet(viewsets.ModelViewSet):
    """子域名词视图集"""
    queryset = SubdomainWord.objects.all()
    serializer_class = SubdomainWordSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['is_active', 'category']
    search_fields = ['word', 'category']
    pagination_class = None  # 禁用分页，返回所有数据
    
    @action(detail=False, methods=['post'])
    def generate(self, request):
        """生成一个可用的子域名（从词库中随机选择，如果已被使用则添加数字后缀）"""
        from .utils import get_random_subdomain_word, get_subdomain_with_fallback
        from .cloudflare_client import get_used_subdomains, CloudflareAPIError
        
        exclude_words = request.data.get('exclude_words', [])
        use_dash = request.data.get('use_dash', False)  # 是否使用短横线分隔
        fallback_prefix = request.data.get('fallback_prefix', 'node')
        
        # Cloudflare 相关参数（可选）
        zone_id = request.data.get('zone_id')
        zone_name = request.data.get('zone_name')
        api_token = request.data.get('api_token')
        api_key = request.data.get('api_key')
        api_email = request.data.get('api_email')
        
        if not isinstance(exclude_words, list):
            return Response({'error': 'exclude_words 必须是列表'}, status=status.HTTP_400_BAD_REQUEST)
        
        # 如果提供了 Cloudflare 参数，查询已使用的子域名
        if zone_id and zone_name:
            try:
                used_subdomains = get_used_subdomains(
                    zone_id=zone_id,
                    zone_name=zone_name,
                    api_token=api_token,
                    api_key=api_key,
                    api_email=api_email
                )
                # 合并到 exclude_words 中
                exclude_words = list(set(exclude_words + used_subdomains))
                logger.info(f'从 Cloudflare 查询到 {len(used_subdomains)} 个已使用的子域名')
            except CloudflareAPIError as e:
                # API 查询失败，记录警告但继续使用 exclude_words
                logger.warning(f'查询 Cloudflare DNS 记录失败: {str(e)}，将使用提供的 exclude_words')
        
        # 尝试从词库中获取
        subdomain = get_random_subdomain_word(exclude_words=exclude_words, use_dash=use_dash)
        
        if not subdomain:
            # 如果词库为空，使用后备方案
            subdomain = get_subdomain_with_fallback(
                exclude_words=exclude_words,
                fallback_prefix=fallback_prefix,
                use_dash=use_dash
            )
        
        # 如果提供了 Cloudflare 参数，再次验证生成的子域名是否冲突
        if zone_id and zone_name and subdomain in exclude_words:
            # 如果生成的子域名仍然冲突，尝试添加数字后缀
            from .utils import get_available_subdomain_with_number
            subdomain = get_available_subdomain_with_number(
                base_word=subdomain.split('-')[0] if '-' in subdomain else subdomain,
                exclude_words=exclude_words,
                use_dash=use_dash
            )
        
        return Response({
            'subdomain': subdomain,
            'use_dash': use_dash,
            'exclude_words_count': len(exclude_words),
            'checked_cloudflare': bool(zone_id and zone_name)
        })

    @action(detail=False, methods=['post'])
    def batch_add(self, request):
        """批量添加子域名词"""
        words = request.data.get('words', [])
        if not words:
            return Response({'error': '请提供要添加的词列表'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not isinstance(words, list):
            return Response({'error': 'words 必须是列表'}, status=status.HTTP_400_BAD_REQUEST)
        
        created = []
        skipped = []
        errors = []
        
        for word_data in words:
            if isinstance(word_data, str):
                word = word_data.strip()
                category = None
            elif isinstance(word_data, dict):
                word = word_data.get('word', '').strip()
                category = word_data.get('category', '').strip() or None
            else:
                errors.append(f'无效的数据格式: {word_data}')
                continue
            
            if not word:
                errors.append(f'空的词: {word_data}')
                continue
            
            # 检查是否已存在
            if SubdomainWord.objects.filter(word=word).exists():
                skipped.append(word)
                continue
            
            try:
                subdomain_word = SubdomainWord.objects.create(
                    word=word,
                    category=category,
                    created_by=request.user
                )
                created.append(SubdomainWordSerializer(subdomain_word).data)
            except Exception as e:
                errors.append(f'创建 {word} 失败: {str(e)}')
        
        return Response({
            'created': created,
            'skipped': skipped,
            'errors': errors,
            'summary': {
                'total': len(words),
                'created_count': len(created),
                'skipped_count': len(skipped),
                'error_count': len(errors)
            }
        }, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def increment_usage(self, request, pk=None):
        """增加使用次数（内部使用）"""
        word = self.get_object()
        word.usage_count += 1
        word.save(update_fields=['usage_count'])
        return Response(SubdomainWordSerializer(word).data)
    
    @action(detail=False, methods=['post'], url_path='init-defaults')
    def init_defaults(self, request):
        """初始化默认子域名词库"""
        # 常用子域名词列表（与迁移文件中的保持一致）
        default_words = [
            # 通用类
            {'word': 'www', 'category': 'common'},
            {'word': 'api', 'category': 'common'},
            {'word': 'app', 'category': 'common'},
            {'word': 'web', 'category': 'common'},
            {'word': 'site', 'category': 'common'},
            
            # 服务类
            {'word': 'chat', 'category': 'service'},
            {'word': 'mail', 'category': 'service'},
            {'word': 'ftp', 'category': 'service'},
            {'word': 'ssh', 'category': 'service'},
            {'word': 'vpn', 'category': 'service'},
            {'word': 'proxy', 'category': 'service'},
            {'word': 'agent', 'category': 'service'},
            {'word': 'node', 'category': 'service'},
            {'word': 'server', 'category': 'service'},
            {'word': 'cdn', 'category': 'service'},
            
            # 应用类
            {'word': 'admin', 'category': 'app'},
            {'word': 'dashboard', 'category': 'app'},
            {'word': 'panel', 'category': 'app'},
            {'word': 'portal', 'category': 'app'},
            {'word': 'console', 'category': 'app'},
            
            # 其他
            {'word': 'test', 'category': 'other'},
            {'word': 'dev', 'category': 'other'},
            {'word': 'staging', 'category': 'other'},
            {'word': 'demo', 'category': 'other'},
        ]
        
        created = []
        skipped = []
        
        # 批量创建（如果不存在）
        for word_data in default_words:
            word_obj, created_flag = SubdomainWord.objects.get_or_create(
                word=word_data['word'],
                defaults={
                    'category': word_data['category'],
                    'is_active': True,
                    'created_by': request.user
                }
            )
            if created_flag:
                created.append(SubdomainWordSerializer(word_obj).data)
            else:
                skipped.append(word_data['word'])
        
        return Response({
            'message': f'初始化完成：成功创建 {len(created)} 个，跳过 {len(skipped)} 个（已存在）',
            'created': created,
            'skipped': skipped,
            'total': len(default_words)
        }, status=status.HTTP_201_CREATED)


class CloudflareAccountViewSet(viewsets.ModelViewSet):
    """Cloudflare 账户视图集"""
    queryset = CloudflareAccount.objects.all()
    serializer_class = CloudflareAccountSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """只返回当前用户创建的账户"""
        return CloudflareAccount.objects.filter(created_by=self.request.user)
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """测试 Cloudflare 账户连接"""
        account = self.get_object()
        
        try:
            from .cloudflare_client import get_cloudflare_api_headers, CloudflareAPIError
            import requests
            from django.utils import timezone
            
            # 检查凭证
            logger.info(f'测试 Cloudflare 账户: id={account.id}, name={account.name}')
            logger.debug(f'API Token 存在: {bool(account.api_token)}, 长度: {len(account.api_token) if account.api_token else 0}')
            logger.debug(f'API Key 存在: {bool(account.api_key)}, Email: {account.api_email}')
            
            # 清理 API Token 和 Key（去除首尾空格和换行符）
            api_token = account.api_token.strip() if account.api_token else None
            api_key = account.api_key.strip() if account.api_key else None
            api_email = account.api_email.strip() if account.api_email else None
            
            headers = get_cloudflare_api_headers(
                api_token=api_token,
                api_key=api_key,
                api_email=api_email
            )
            
            # 测试 API：验证 Token
            # 如果使用 API Token，先尝试获取账户列表，然后使用 accounts/{account_id}/tokens/verify
            # 如果使用 Global API Key，使用 user 端点
            if api_token:
                # 先获取账户列表，找到第一个账户 ID
                try:
                    accounts_url = 'https://api.cloudflare.com/client/v4/accounts'
                    accounts_response = requests.get(accounts_url, headers=headers, timeout=10)
                    
                    if accounts_response.status_code == 200:
                        accounts_result = accounts_response.json()
                        if accounts_result.get('success', False):
                            accounts = accounts_result.get('result', [])
                            if accounts:
                                account_id = accounts[0].get('id')
                                account_name = accounts[0].get('name', '')
                                
                                # 使用 accounts/{account_id}/tokens/verify 端点验证
                                test_url = f'https://api.cloudflare.com/client/v4/accounts/{account_id}/tokens/verify'
                                
                                # 更新账户信息
                                account.account_id = account_id
                                account.account_name = account_name
                                account.save(update_fields=['account_id', 'account_name'])
                                
                                logger.info(f'找到账户 ID: {account_id}, 使用 accounts/tokens/verify 端点')
                            else:
                                # 如果没有账户，尝试使用 user/tokens/verify
                                test_url = 'https://api.cloudflare.com/client/v4/user/tokens/verify'
                                logger.info('未找到账户，使用 user/tokens/verify 端点')
                        else:
                            # API 调用失败，尝试使用 user/tokens/verify
                            test_url = 'https://api.cloudflare.com/client/v4/user/tokens/verify'
                            logger.warning('获取账户列表失败，使用 user/tokens/verify 端点')
                    else:
                        # 获取账户列表失败，尝试使用 user/tokens/verify
                        test_url = 'https://api.cloudflare.com/client/v4/user/tokens/verify'
                        logger.warning(f'获取账户列表失败: {accounts_response.status_code}，使用 user/tokens/verify 端点')
                except Exception as e:
                    # 获取账户列表异常，尝试使用 user/tokens/verify
                    test_url = 'https://api.cloudflare.com/client/v4/user/tokens/verify'
                    logger.warning(f'获取账户列表异常: {str(e)}，使用 user/tokens/verify 端点')
            elif api_key and api_email:
                # Global API Key 验证端点
                test_url = 'https://api.cloudflare.com/client/v4/user'
            else:
                return Response({
                    'status': 'failed',
                    'message': '未提供有效的 API 凭证'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            logger.info(f'测试 Cloudflare 账户连接: account_id={account.id}, url={test_url}')
            # 不记录完整的 Token，只记录前几位和后几位
            if api_token:
                token_preview = f"{api_token[:4]}...{api_token[-4:]}" if len(api_token) > 8 else "***"
                logger.info(f'使用 API Token，长度: {len(api_token)}, 预览: {token_preview}')
                # 检查 Token 是否包含不可见字符
                if api_token != api_token.strip() or '\n' in api_token or '\r' in api_token:
                    logger.warning(f'API Token 包含特殊字符，已清理')
                logger.debug(f'请求头: Authorization: Bearer {token_preview}')
            else:
                logger.info(f'使用 Global API Key, Email: {api_email}')
                logger.debug(f'请求头: X-Auth-Key: ***, X-Auth-Email: {api_email}')
            
            # 发送请求
            logger.debug(f'发送请求到: {test_url}')
            logger.debug(f'请求头键: {list(headers.keys())}')
            
            try:
                response = requests.get(test_url, headers=headers, timeout=10)
            except requests.exceptions.RequestException as e:
                logger.error(f'请求异常: {str(e)}')
                raise
            
            logger.info(f'Cloudflare API 响应: status={response.status_code}')
            logger.debug(f'响应头: {dict(response.headers)}')
            logger.debug(f'响应内容: {response.text[:500]}')
            
            if response.status_code == 200:
                result = response.json()
                logger.debug(f'API 响应内容: {result}')
                
                if result.get('success', False):
                    # 尝试获取账户信息
                    account_info = result.get('result', {})
                    if account_info:
                        # 如果是 Token 验证，可能包含账户信息
                        if 'id' in account_info:
                            account.account_id = account_info.get('id')
                        if 'email' in account_info:
                            account.account_name = account_info.get('email')
                    
                    # 更新账户信息
                    account.last_check = timezone.now()
                    account.last_check_status = 'success'
                    account.save(update_fields=['last_check', 'last_check_status', 'account_id', 'account_name'])
                    
                    return Response({
                        'status': 'success',
                        'message': '连接测试成功',
                        'result': account_info
                    })
                else:
                    errors = result.get('errors', [])
                    error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors]) if errors else 'API 验证失败'
                    
                    account.last_check = timezone.now()
                    account.last_check_status = 'failed'
                    account.save(update_fields=['last_check', 'last_check_status'])
                    
                    return Response({
                        'status': 'failed',
                        'message': error_msg
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                # 尝试解析错误信息
                try:
                    error_result = response.json()
                    logger.debug(f'错误响应 JSON: {error_result}')
                    errors = error_result.get('errors', [])
                    if errors:
                        error_msg = '; '.join([e.get('message', 'Unknown error') for e in errors])
                    else:
                        error_msg = error_result.get('message', f'API 请求失败: {response.status_code}')
                except Exception as json_error:
                    logger.warning(f'解析错误响应失败: {json_error}, 原始响应: {response.text[:500]}')
                    error_msg = f'API 请求失败: {response.status_code} - {response.text[:200]}'
                
                logger.error(f'Cloudflare API 测试失败: status={response.status_code}, message={error_msg}')
                
                account.last_check = timezone.now()
                account.last_check_status = 'failed'
                account.save(update_fields=['last_check', 'last_check_status'])
                
                return Response({
                    'status': 'failed',
                    'message': error_msg
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except CloudflareAPIError as e:
            account.last_check = timezone.now()
            account.last_check_status = 'failed'
            account.save(update_fields=['last_check', 'last_check_status'])
            return Response({
                'status': 'failed',
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            account.last_check = timezone.now()
            account.last_check_status = 'failed'
            account.save(update_fields=['last_check', 'last_check_status'])
            return Response({
                'status': 'failed',
                'message': f'测试失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CloudflareZoneViewSet(viewsets.ModelViewSet):
    """Cloudflare Zone 视图集"""
    queryset = CloudflareZone.objects.all()
    serializer_class = CloudflareZoneSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """只返回当前用户创建的账户的 Zone"""
        return CloudflareZone.objects.filter(account__created_by=self.request.user)
    
    @action(detail=False, methods=['post'])
    def sync(self, request):
        """从 Cloudflare 同步 Zone 列表"""
        account_id = request.data.get('account_id')
        
        if not account_id:
            return Response({'error': '请提供账户 ID'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            account = CloudflareAccount.objects.get(id=account_id, created_by=request.user)
        except CloudflareAccount.DoesNotExist:
            return Response({'error': '账户不存在或无权限'}, status=status.HTTP_404_NOT_FOUND)
        
        try:
            from .cloudflare_client import list_zones, get_cloudflare_api_headers, CloudflareAPIError
            import requests
            from django.utils import timezone
            
            # 获取 API 凭证
            api_token = account.api_token.strip() if account.api_token else None
            api_key = account.api_key.strip() if account.api_key else None
            api_email = account.api_email.strip() if account.api_email else None
            
            # 获取 Zone 列表
            zones = list_zones(api_token=api_token, api_key=api_key, api_email=api_email)
            
            created_count = 0
            updated_count = 0
            dns_created_count = 0
            dns_updated_count = 0
            
            for zone_data in zones:
                zone_id = zone_data.get('id')
                zone_name = zone_data.get('name')
                zone_status = zone_data.get('status')
                
                if not zone_id or not zone_name:
                    continue
                
                zone, created = CloudflareZone.objects.get_or_create(
                    account=account,
                    zone_id=zone_id,
                    defaults={
                        'zone_name': zone_name,
                        'status': zone_status
                    }
                )
                
                if created:
                    created_count += 1
                else:
                    # 更新现有 Zone
                    zone.zone_name = zone_name
                    zone.status = zone_status
                    zone.updated_at = timezone.now()
                    zone.save()
                    updated_count += 1
                
                # 同步该 Zone 的 DNS 记录
                try:
                    from .cloudflare_client import list_zone_dns_records
                    
                    dns_records = list_zone_dns_records(
                        zone_id=zone_id,
                        api_token=api_token,
                        api_key=api_key,
                        api_email=api_email
                    )
                    
                    for record_data in dns_records:
                        record_id = record_data.get('id')
                        record_type = record_data.get('type')
                        name = record_data.get('name')
                        content = record_data.get('content')
                        ttl = record_data.get('ttl', 1)
                        proxied = record_data.get('proxied', False)
                        
                        if not record_id or not record_type or not name or not content:
                            continue
                        
                        dns_record, dns_created = CloudflareDNSRecord.objects.get_or_create(
                            zone=zone,
                            record_id=record_id,
                            defaults={
                                'record_type': record_type,
                                'name': name,
                                'content': content,
                                'ttl': ttl,
                                'proxied': proxied,
                                'is_active': True
                            }
                        )
                        
                        if dns_created:
                            dns_created_count += 1
                        else:
                            # 更新现有 DNS 记录
                            dns_record.record_type = record_type
                            dns_record.name = name
                            dns_record.content = content
                            dns_record.ttl = ttl
                            dns_record.proxied = proxied
                            dns_record.updated_at = timezone.now()
                            dns_record.save()
                            dns_updated_count += 1
                            
                except Exception as e:
                    logger.warning(f'同步 Zone {zone_name} 的 DNS 记录失败: {str(e)}')
                    continue
            
            message = f'同步完成：Zone 新增 {created_count} 个，更新 {updated_count} 个'
            if dns_created_count > 0 or dns_updated_count > 0:
                message += f'；DNS 记录新增 {dns_created_count} 个，更新 {dns_updated_count} 个'
            
            return Response({
                'message': message,
                'created': created_count,
                'updated': updated_count,
                'total': len(zones),
                'dns_created': dns_created_count,
                'dns_updated': dns_updated_count
            })
            
        except CloudflareAPIError as e:
            return Response({
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'同步 Zone 失败: {str(e)}', exc_info=True)
            return Response({
                'error': f'同步失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CloudflareDNSRecordViewSet(viewsets.ModelViewSet):
    """Cloudflare DNS 记录视图集"""
    queryset = CloudflareDNSRecord.objects.all()
    serializer_class = CloudflareDNSRecordSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['zone', 'record_type', 'is_active']
    search_fields = ['name', 'content']
    
    def get_queryset(self):
        """只返回当前用户创建的账户的 DNS 记录"""
        return CloudflareDNSRecord.objects.filter(zone__account__created_by=self.request.user)
    
    def create(self, request, *args, **kwargs):
        """创建 DNS 记录"""
        zone_id = request.data.get('zone')
        if not zone_id:
            return Response({'error': '请提供 Zone ID'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            zone = CloudflareZone.objects.get(id=zone_id, account__created_by=request.user)
        except CloudflareZone.DoesNotExist:
            return Response({'error': 'Zone 不存在或无权限'}, status=status.HTTP_404_NOT_FOUND)
        
        account = zone.account
        
        # 获取 API 凭证
        api_token = account.api_token.strip() if account.api_token else None
        api_key = account.api_key.strip() if account.api_key else None
        api_email = account.api_email.strip() if account.api_email else None
        
        try:
            from .cloudflare_client import create_dns_record, CloudflareAPIError
            
            # 创建 DNS 记录
            record_data = create_dns_record(
                zone_id=zone.zone_id,
                record_type=request.data.get('record_type'),
                name=request.data.get('name'),
                content=request.data.get('content'),
                api_token=api_token,
                api_key=api_key,
                api_email=api_email,
                ttl=request.data.get('ttl', 1),
                proxied=request.data.get('proxied', False)
            )
            
            # 保存到数据库
            dns_record = CloudflareDNSRecord.objects.create(
                zone=zone,
                record_id=record_data.get('id'),
                record_type=request.data.get('record_type'),
                name=request.data.get('name'),
                content=request.data.get('content'),
                ttl=request.data.get('ttl', 1),
                proxied=request.data.get('proxied', False),
                is_active=True
            )
            
            serializer = self.get_serializer(dns_record)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except CloudflareAPIError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'创建 DNS 记录失败: {str(e)}', exc_info=True)
            return Response({'error': f'创建失败: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def update(self, request, *args, **kwargs):
        """更新 DNS 记录"""
        instance = self.get_object()
        zone = instance.zone
        account = zone.account
        
        # 获取 API 凭证
        api_token = account.api_token.strip() if account.api_token else None
        api_key = account.api_key.strip() if account.api_key else None
        api_email = account.api_email.strip() if account.api_email else None
        
        try:
            from .cloudflare_client import update_dns_record, CloudflareAPIError
            
            # 准备更新数据
            update_data = {}
            if 'name' in request.data:
                update_data['name'] = request.data['name']
            if 'content' in request.data:
                update_data['content'] = request.data['content']
            if 'ttl' in request.data:
                update_data['ttl'] = request.data['ttl']
            if 'proxied' in request.data:
                update_data['proxied'] = request.data['proxied']
            
            # 更新 Cloudflare 上的记录
            record_data = update_dns_record(
                zone_id=zone.zone_id,
                record_id=instance.record_id,
                api_token=api_token,
                api_key=api_key,
                api_email=api_email,
                **update_data
            )
            
            # 更新数据库
            if 'name' in request.data:
                instance.name = request.data['name']
            if 'content' in request.data:
                instance.content = request.data['content']
            if 'ttl' in request.data:
                instance.ttl = request.data['ttl']
            if 'proxied' in request.data:
                instance.proxied = request.data['proxied']
            if 'is_active' in request.data:
                instance.is_active = request.data['is_active']
            instance.save()
            
            serializer = self.get_serializer(instance)
            return Response(serializer.data)
            
        except CloudflareAPIError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'更新 DNS 记录失败: {str(e)}', exc_info=True)
            return Response({'error': f'更新失败: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def destroy(self, request, *args, **kwargs):
        """删除 DNS 记录"""
        instance = self.get_object()
        zone = instance.zone
        account = zone.account
        
        # 获取 API 凭证
        api_token = account.api_token.strip() if account.api_token else None
        api_key = account.api_key.strip() if account.api_key else None
        api_email = account.api_email.strip() if account.api_email else None
        
        try:
            from .cloudflare_client import delete_dns_record, CloudflareAPIError
            
            # 从 Cloudflare 删除
            delete_dns_record(
                zone_id=zone.zone_id,
                record_id=instance.record_id,
                api_token=api_token,
                api_key=api_key,
                api_email=api_email
            )
            
            # 从数据库删除
            instance.delete()
            
            return Response(status=status.HTTP_204_NO_CONTENT)
            
        except CloudflareAPIError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'删除 DNS 记录失败: {str(e)}', exc_info=True)
            return Response({'error': f'删除失败: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

