from rest_framework import serializers
from .models import Server


class ServerSerializer(serializers.ModelSerializer):
    """服务器序列化器"""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    has_password = serializers.SerializerMethodField()
    has_private_key = serializers.SerializerMethodField()
    has_agent = serializers.SerializerMethodField()
    agent_status = serializers.SerializerMethodField()
    agent_rpc_supported = serializers.SerializerMethodField()

    class Meta:
        model = Server
        fields = [
            'id', 'name', 'host', 'port', 'username',
            'password', 'private_key', 'connection_method', 'deployment_target',
            'agent_connect_host', 'agent_connect_port',
            'status', 'last_check', 'save_password', 'auto_clear_password_after_agent_install', 'enable_ssh_key',
            'has_password', 'has_private_key', 'has_agent',
            'agent_status', 'agent_rpc_supported',
            'created_at', 'updated_at', 'created_by', 'created_by_username'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by', 'has_password', 'has_private_key', 'has_agent', 'agent_status', 'agent_rpc_supported']
        extra_kwargs = {
            'name': {'required': False, 'allow_blank': True},
            'password': {'write_only': True, 'required': False},
            'private_key': {'write_only': True, 'required': False},
        }

    def get_has_password(self, obj):
        """检查是否有密码（不返回密码内容）"""
        return bool(obj.password)

    def get_has_private_key(self, obj):
        """检查是否有私钥（不返回私钥内容）"""
        return bool(obj.private_key)

    def get_has_agent(self, obj):
        """检查是否有Agent"""
        try:
            from apps.agents.models import Agent
            Agent.objects.get(server=obj)
            return True
        except:
            return False
    
    def get_agent_status(self, obj):
        """获取Agent状态"""
        try:
            from apps.agents.models import Agent
            agent = Agent.objects.get(server=obj)
            return agent.status
        except:
            return None
    
    def get_agent_rpc_supported(self, obj):
        """检查Agent是否有HTTP端口配置（向后兼容，字段名保留）"""
        try:
            from apps.agents.models import Agent
            agent = Agent.objects.get(server=obj)
            # 检查Agent是否有端口配置（实际是HTTP端口，但字段名仍为rpc_port）
            return bool(agent.rpc_port)
        except:
            return False

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)


class ServerTestSerializer(serializers.Serializer):
    """服务器连接测试序列化器"""
    host = serializers.CharField()
    port = serializers.IntegerField(default=22)
    username = serializers.CharField()
    password = serializers.CharField(required=False, allow_blank=True)
    private_key = serializers.CharField(required=False, allow_blank=True)

