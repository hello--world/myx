from rest_framework import serializers
from .models import Agent, CommandTemplate


class AgentSerializer(serializers.ModelSerializer):
    """Agent序列化器"""
    server_name = serializers.CharField(source='server.name', read_only=True)
    server_host = serializers.CharField(source='server.host', read_only=True)
    server_port = serializers.IntegerField(source='server.port', read_only=True)
    agent_connect_host = serializers.CharField(source='server.agent_connect_host', read_only=True)
    agent_connect_port = serializers.IntegerField(source='server.agent_connect_port', read_only=True)
    connection_method = serializers.CharField(source='server.connection_method', read_only=True)
    deployment_target = serializers.CharField(source='server.deployment_target', read_only=True)
    server_status = serializers.CharField(source='server.status', read_only=True)

    class Meta:
        model = Agent
        fields = [
            'id', 'server', 'server_name', 'server_host', 'server_port',
            'agent_connect_host', 'agent_connect_port',
            'connection_method', 'deployment_target', 'server_status',
            'token', 'status', 'version', 'heartbeat_mode', 'last_heartbeat', 'last_check',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'token', 'status', 'version', 'last_heartbeat', 'last_check', 'created_at', 'updated_at']


class AgentRegisterSerializer(serializers.Serializer):
    """Agent注册序列化器"""
    # server_token 可以是 UUID 字符串或整数 ID
    server_token = serializers.CharField()
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


class AgentCommandDetailSerializer(serializers.ModelSerializer):
    """Agent命令详情序列化器"""
    agent_id = serializers.IntegerField(source='agent.id', read_only=True)
    agent_server_name = serializers.CharField(source='agent.server.name', read_only=True)

    class Meta:
        from .models import AgentCommand
        model = AgentCommand
        fields = [
            'id', 'agent', 'agent_id', 'agent_server_name',
            'command', 'args', 'timeout', 'status',
            'result', 'error', 'created_at', 'started_at', 'completed_at'
        ]
        read_only_fields = ['id', 'agent', 'status', 'result', 'error', 'created_at', 'started_at', 'completed_at']


class CommandTemplateSerializer(serializers.ModelSerializer):
    """命令模板序列化器"""
    class Meta:
        model = CommandTemplate
        fields = ['id', 'name', 'description', 'command', 'args', 'timeout', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)

