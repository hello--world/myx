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
    def update_command_result(command_id: int, success: bool, result: str = None, error: str = None, append: bool = False):
        """更新命令执行结果
        
        Args:
            command_id: 命令ID
            success: 是否成功
            result: 执行结果
            error: 错误信息
            append: 是否追加到现有结果（用于实时上报）
        """
        try:
            cmd = AgentCommand.objects.get(id=command_id)
            if append:
                # 增量更新：追加到现有结果
                if result:
                    cmd.result = (cmd.result or '') + result
                if error:
                    cmd.error = (cmd.error or '') + error
            else:
                # 最终结果：替换
                if success is not None:
                    cmd.status = 'success' if success else 'failed'
                if result is not None:
                    cmd.result = result
                if error is not None:
                    cmd.error = error
                if success is not None:
                    cmd.completed_at = timezone.now()
            cmd.save()
        except AgentCommand.DoesNotExist:
            pass

