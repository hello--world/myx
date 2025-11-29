from rest_framework import serializers
from .models import Deployment


class DeploymentSerializer(serializers.ModelSerializer):
    """部署任务序列化器"""
    server_name = serializers.CharField(source='server.name', read_only=True)
    server_host = serializers.CharField(source='server.host', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Deployment
        fields = [
            'id', 'name', 'server', 'server_name', 'server_host',
            'deployment_type', 'connection_method', 'deployment_target', 'status', 'log', 'error_message',
            'started_at', 'completed_at', 'created_at', 'updated_at',
            'created_by', 'created_by_username'
        ]
        read_only_fields = [
            'id', 'status', 'log', 'error_message',
            'started_at', 'completed_at', 'created_at', 'updated_at', 'created_by'
        ]

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class QuickDeploySerializer(serializers.Serializer):
    """快速部署序列化器（可选择已有服务器或直接输入SSH信息）"""
    # 使用已有服务器
    server_id = serializers.IntegerField(required=False, help_text='服务器ID（使用已有服务器时）')
    
    # 直接输入SSH信息（不保存密码）
    name = serializers.CharField(max_length=100, required=False, help_text='服务器名称（直接输入时）')
    host = serializers.CharField(max_length=255, required=False, help_text='主机地址（直接输入时）')
    port = serializers.IntegerField(default=22, required=False, help_text='SSH端口（直接输入时）')
    username = serializers.CharField(max_length=100, required=False, help_text='SSH用户名（直接输入时）')
    password = serializers.CharField(required=False, allow_blank=True, help_text='SSH密码（直接输入时，不保存）')
    private_key = serializers.CharField(required=False, allow_blank=True, help_text='SSH私钥（直接输入时，不保存）')
    
    # 部署目标
    deployment_target = serializers.ChoiceField(
        choices=[('host', '宿主机'), ('docker', 'Docker')],
        default='host',
        help_text='部署目标'
    )
    
    def validate(self, data):
        """验证：必须提供server_id或SSH信息"""
        server_id = data.get('server_id')
        host = data.get('host')
        
        if not server_id and not host:
            raise serializers.ValidationError('请选择已有服务器或输入SSH信息')
        
        if server_id and host:
            raise serializers.ValidationError('不能同时选择服务器和输入SSH信息')
        
        # 如果直接输入，验证必填字段
        if host:
            if not data.get('name'):
                raise serializers.ValidationError('请输入服务器名称')
            if not data.get('username'):
                raise serializers.ValidationError('请输入SSH用户名')
            if not data.get('password') and not data.get('private_key'):
                raise serializers.ValidationError('请输入SSH密码或私钥')
        
        return data
