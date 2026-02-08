from typing import List, Tuple, Type

from src.plugin_system import BasePlugin, register_plugin, ComponentInfo
from src.common.logger import get_logger

from .config import PLUGIN_CONFIG_SCHEMA
from .api import app

logger = get_logger("call_me")

@register_plugin
class CallMePlugin(BasePlugin):
    """Call Me 插件 - 实时语音通话服务"""

    plugin_name = "call_me"
    enable_plugin = True # 默认值，加载配置后会被覆盖
    dependencies = []
    python_dependencies = [
        "fastapi",
        "uvicorn",
        "sqlalchemy",
        "aiosqlite",
        "aiohttp",
        "python-multipart",
    ]
    config_file_name = "config.toml"
    config_schema = PLUGIN_CONFIG_SCHEMA

    config_section_descriptions = {
        "plugin": "插件基本运行控制",
        "server": "FastAPI HTTP/WebSocket 服务配置",
        "vad": "实时语音活动检测(VAD)参数",
        "audio": "音频输出流格式配置",
        "tts": "语音合成(TTS)配置",
        "asr": "语音识别(ASR)配置",
        "sherpa": "Sherpa 本地 ASR 模型配置",
        "llm": "大语言模型生成配置",
        "prethink": "预思考配置（异步预测下一轮用户意图）"
    }
    
    # _server_thread 等属性已移至 CallMeService，此处可清理
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        from .core.handlers import CallMeStartHandler, CallMeStopHandler
        from .core.commands import CallMeCommand
        
        return [
            (CallMeStartHandler.get_handler_info(), CallMeStartHandler),
            (CallMeStopHandler.get_handler_info(), CallMeStopHandler),
            (CallMeCommand.get_command_info(), CallMeCommand)
        ]

    # on_load 和 on_unload 不再需要手动管理线程，交由 Event Handlers 处理
    def on_load(self):
        """插件加载时逻辑"""
        logger.info("[CallMe] 插件已加载，后台服务将由 ON_START 事件或手动指令启动")

    def on_unload(self):
        """插件卸载时逻辑"""
        # 如果是在运行中卸载插件，也尝试停止服务
        from .core.service import call_me_service
        call_me_service.stop()
        


