"""
Agent命令队列管理
"""
from django.utils import timezone
from .models import Agent, AgentCommand


class CommandQueue:
    """命令队列管理器"""
    
    @staticmethod
    def add_command(agent: Agent, command: str, args: list = None, timeout: int = 300):
        """添加命令到队列"""
        if args is None:
            args = []
        
        cmd = AgentCommand.objects.create(
            agent=agent,
            command=command,
            args=args,
            timeout=timeout,
            status='pending'
        )
        return cmd
    
    @staticmethod
    def get_pending_commands(agent: Agent):
        """获取待执行的命令"""
        commands = AgentCommand.objects.filter(
            agent=agent,
            status='pending'
        ).order_by('created_at')[:10]  # 每次最多返回10个命令
        
        result = []
        for cmd in commands:
            # 标记为执行中
            cmd.status = 'running'
            cmd.started_at = timezone.now()
            cmd.save()
            
            result.append({
                'id': cmd.id,
                'command': cmd.command,
                'args': cmd.args if cmd.args else [],
                'timeout': cmd.timeout
            })
        
        return result
    
    @staticmethod
    def update_command_result(command_id: int, success: bool, result: str = None, error: str = None):
        """更新命令执行结果"""
        try:
            cmd = AgentCommand.objects.get(id=command_id)
            cmd.status = 'success' if success else 'failed'
            cmd.result = result
            cmd.error = error
            cmd.completed_at = timezone.now()
            cmd.save()
        except AgentCommand.DoesNotExist:
            pass

