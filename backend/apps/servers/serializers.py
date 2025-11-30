from rest_framework import serializers
from .models import Server


class ServerSerializer(serializers.ModelSerializer):
    """服务器序列化器"""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Server
        fields = [
            'id', 'name', 'host', 'port', 'username',
            'password', 'private_key', 'connection_method', 'deployment_target',
            'agent_connect_host', 'agent_connect_port',
            'status', 'last_check', 'save_password', 'enable_ssh_key',
            'created_at', 'updated_at', 'created_by', 'created_by_username'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'private_key': {'write_only': True, 'required': False},
        }

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

