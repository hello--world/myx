from rest_framework import serializers
from .models import Subscription


class SubscriptionSerializer(serializers.ModelSerializer):
    """订阅序列化器"""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    subscription_url = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            'id', 'name', 'token', 'format', 'enabled',
            'subscription_url', 'created_at', 'updated_at',
            'created_by', 'created_by_username'
        ]
        read_only_fields = ['id', 'token', 'created_at', 'updated_at', 'created_by']

    def get_subscription_url(self, obj):
        request = self.context.get('request')
        if request:
            return f"{request.scheme}://{request.get_host()}/api/subscriptions/{obj.token}/"
        return None

    def create(self, validated_data):
        validated_data['created_by'] = self.context['request'].user
        return super().create(validated_data)

