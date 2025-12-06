from rest_framework import serializers
from .models import Agent


class AgentRegisterSerializer(serializers.Serializer):
    """Agent注册序列化器"""
    # server_token 可以是 UUID 字符串或整数 ID
    server_token = serializers.CharField()
    version = serializers.CharField(required=False)
    hostname = serializers.CharField(required=False)
    os = serializers.CharField(required=False)


class AgentCommandSerializer(serializers.Serializer):
    """Agent命令序列化器"""
    command = serializers.CharField()
    args = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    timeout = serializers.IntegerField(required=False, default=300)



