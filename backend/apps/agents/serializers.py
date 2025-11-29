from rest_framework import serializers
from .models import Agent


class AgentSerializer(serializers.ModelSerializer):
    """Agent序列化器"""
    server_name = serializers.CharField(source='server.name', read_only=True)
    server_host = serializers.CharField(source='server.host', read_only=True)

    class Meta:
        model = Agent
        fields = [
            'id', 'server', 'server_name', 'server_host',
            'token', 'status', 'version', 'last_heartbeat',
            'registered_at', 'updated_at'
        ]
        read_only_fields = ['id', 'token', 'secret_key', 'status', 'version', 'last_heartbeat', 'registered_at', 'updated_at']


class AgentRegisterSerializer(serializers.Serializer):
    """Agent注册序列化器"""
    server_token = serializers.UUIDField()
    version = serializers.CharField(required=False)
    hostname = serializers.CharField(required=False)
    os = serializers.CharField(required=False)


class AgentHeartbeatSerializer(serializers.Serializer):
    """Agent心跳序列化器"""
    status = serializers.CharField(required=False)
    version = serializers.CharField(required=False)


class AgentCommandSerializer(serializers.Serializer):
    """Agent命令序列化器"""
    command = serializers.CharField()
    args = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    timeout = serializers.IntegerField(required=False, default=300)

