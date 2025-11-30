from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from .serializers import UserSerializer, LoginSerializer


@api_view(['GET'])
@permission_classes([AllowAny])
def csrf_token(request):
    """获取 CSRF token"""
    token = get_token(request)
    return Response({'csrfToken': token})


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """用户登录"""
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        login(request, user)
        return Response({
            'message': '登录成功',
            'user': UserSerializer(user).data
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """用户登出"""
    logout(request)
    return Response({'message': '登出成功'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_info(request):
    """获取当前用户信息"""
    return Response(UserSerializer(request.user).data)


@api_view(['PUT', 'PATCH'])
@permission_classes([IsAuthenticated])
def update_user(request):
    """更新当前用户信息"""
    from .serializers import UserUpdateSerializer
    serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response({
            'message': '用户信息更新成功',
            'user': UserSerializer(request.user).data
        })
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    """修改密码"""
    old_password = request.data.get('old_password')
    new_password = request.data.get('new_password')
    
    if not old_password or not new_password:
        return Response({'error': '请提供旧密码和新密码'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 验证旧密码
    if not request.user.check_password(old_password):
        return Response({'error': '旧密码错误'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 验证新密码长度
    if len(new_password) < 8:
        return Response({'error': '新密码长度至少为8位'}, status=status.HTTP_400_BAD_REQUEST)
    
    # 设置新密码
    request.user.set_password(new_password)
    request.user.save()
    
    return Response({'message': '密码修改成功'})

