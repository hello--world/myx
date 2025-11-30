import json
from rest_framework import serializers
from .models import Proxy


class ProxySerializer(serializers.ModelSerializer):
    """代理节点序列化器（参考 xray-ui 设计）"""
    server_name = serializers.CharField(source='server.name', read_only=True)
    server_host = serializers.CharField(source='server.host', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    
    # JSON 字段的序列化/反序列化
    settings_dict = serializers.SerializerMethodField()
    stream_settings_dict = serializers.SerializerMethodField()
    sniffing_dict = serializers.SerializerMethodField()
    
    # 用于接收前端传来的 JSON 对象
    settings = serializers.JSONField(write_only=True, required=False)
    stream_settings = serializers.JSONField(write_only=True, required=False)
    sniffing = serializers.JSONField(write_only=True, required=False)

    class Meta:
        model = Proxy
        fields = [
            'id', 'name', 'server', 'server_name', 'server_host',
            'remark', 'enable', 'up', 'down', 'total', 'expiry_time',
            'listen', 'port', 'protocol', 'settings', 'stream_settings', 'tag', 'sniffing',
            'settings_dict', 'stream_settings_dict', 'sniffing_dict',
            'status', 'deployment_status', 'deployment_log', 'deployed_at',
            'created_at', 'updated_at', 'created_by', 'created_by_username'
        ]
        read_only_fields = ['id', 'up', 'down', 'created_at', 'updated_at', 'created_by', 'tag']

    def get_settings_dict(self, obj):
        """返回 settings 字典"""
        return obj.get_settings_dict()
    
    def get_stream_settings_dict(self, obj):
        """返回 streamSettings 字典"""
        return obj.get_stream_settings_dict()
    
    def get_sniffing_dict(self, obj):
        """返回 sniffing 字典"""
        return obj.get_sniffing_dict()

    def validate_port(self, value):
        """验证端口是否可用（从数据库查询已使用的端口）"""
        # 检查端口是否已被其他代理使用
        instance = self.instance
        if instance:
            # 更新时，排除自己
            if Proxy.objects.filter(port=value).exclude(pk=instance.pk).exists():
                raise serializers.ValidationError(f"端口{value}已被其他代理节点使用")
        else:
            # 创建时，检查所有代理
            if Proxy.objects.filter(port=value).exists():
                raise serializers.ValidationError(f"端口{value}已被其他代理节点使用")
        
        return value
    
    def create(self, validated_data):
        # 处理 JSON 字段
        settings_dict = validated_data.pop('settings', {})
        stream_settings_dict = validated_data.pop('stream_settings', {})
        sniffing_dict = validated_data.pop('sniffing', {})
        
        # 转换为 JSON 字符串存储
        validated_data['settings'] = json.dumps(settings_dict, ensure_ascii=False)
        validated_data['stream_settings'] = json.dumps(stream_settings_dict, ensure_ascii=False)
        validated_data['sniffing'] = json.dumps(sniffing_dict, ensure_ascii=False)
        
        # 生成 tag
        if not validated_data.get('tag'):
            validated_data['tag'] = f"inbound-{validated_data.get('port', 0)}"
        
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)
    
    def update(self, instance, validated_data):
        # 处理 JSON 字段
        if 'settings' in validated_data:
            validated_data['settings'] = json.dumps(validated_data['settings'], ensure_ascii=False)
        if 'stream_settings' in validated_data:
            validated_data['stream_settings'] = json.dumps(validated_data['stream_settings'], ensure_ascii=False)
        if 'sniffing' in validated_data:
            validated_data['sniffing'] = json.dumps(validated_data['sniffing'], ensure_ascii=False)
        
        return super().update(instance, validated_data)

