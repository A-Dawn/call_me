from typing import Tuple, Optional
from src.plugin_system.base.base_command import BaseCommand
from .service import call_me_service
from ..api import app

class CallMeCommand(BaseCommand):
    """Call Me 服务控制指令"""
    command_name = "call_me_command"
    command_description = "Call Me 插件服务控制 (start/stop/status)"
    command_pattern = r"^/callme\s+(start|stop|status)$"
    
    async def execute(self) -> Tuple[bool, Optional[str], int]:
        action = self.matched_groups.get("group1")  # 正则分组1
        if not action:
            # 兼容有些正则解析可能没有 group1 的情况，或者 pattern 写法不同
            # 这里 pattern 只有一个分组，通常是 group1
            # 重新在这个 message plain_text 里找
            import re
            match = re.search(self.command_pattern, self.message.plain_text)
            if match:
                action = match.group(1)
            else:
                return False, "参数错误", 0

        action = action.lower()
        
        if action == "start":
            host = self.get_config("server.host", "127.0.0.1")
            port = self.get_config("server.port", 8989)
            
            call_me_service.configure(host, port, self.plugin_config)
            
            from ..core.tts_manager import tts_manager
            tts_manager.configure(self.get_config("tts", {}))
            
            call_me_service.start(app)
            return True, "Call Me 服务已尝试启动，请查看后台日志。", 0
            
        elif action == "stop":
            call_me_service.stop()
            return True, "Call Me 服务停止指令已发送。", 0
            
        elif action == "status":
            status = call_me_service.get_status()
            return True, f"Call Me 服务状态: {status}", 0
            
        return False, f"未知操作: {action}", 0
