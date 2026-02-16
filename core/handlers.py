from typing import Tuple, Optional
from src.plugin_system.base.base_events_handler import BaseEventHandler
from src.plugin_system.base.component_types import EventType, MaiMessages, CustomEventHandlerResult
from src.common.logger import get_logger
from .service import call_me_service
from ..api import app

logger = get_logger("call_me_handlers")

class CallMeStartHandler(BaseEventHandler):
    """Bot启动时自动启动 CallMe 服务"""
    handler_name = "call_me_start_handler"
    event_type = EventType.ON_START
    
    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, Optional[str], Optional[CustomEventHandlerResult], Optional[MaiMessages]]:
        # 读取配置并配置服务
        host = self.get_config("server.host", "127.0.0.1")
        port = self.get_config("server.port", 8989)
        
        # 传递完整配置给 Service
        call_me_service.configure(host, port, self.plugin_config)
        
        # 配置 TTS Manager
        from ..core.tts_manager import tts_manager
        tts_manager.configure(self.get_config("tts", {}))
        
        if self.get_config("plugin.enabled", True):
            call_me_service.start(app)
        else:
            logger.info("[CallMe] 插件已禁用，不自动启动服务")

        return True, True, None, None, None

class CallMeStopHandler(BaseEventHandler):
    """Bot停止时自动停止 CallMe 服务"""
    handler_name = "call_me_stop_handler"
    event_type = EventType.ON_STOP
    
    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, Optional[str], Optional[CustomEventHandlerResult], Optional[MaiMessages]]:
        call_me_service.stop()
        return True, True, None, None, None
