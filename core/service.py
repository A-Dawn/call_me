import threading
import uvicorn
import time
from typing import Optional
from src.common.logger import get_logger

logger = get_logger("call_me_service")

class CallMeService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CallMeService, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self._server_thread: Optional[threading.Thread] = None
        self._server_instance: Optional[uvicorn.Server] = None
        self._is_running = False
        self._host = "127.0.0.1"
        self._port = 8989
        self._initialized = True

    def configure(self, host: str, port: int, config: dict = None):
        self._host = host
        self._port = port
        self.config = config or {}

    def start(self, app):
        """启动服务"""
        if self._is_running:
            logger.info("[CallMe] 服务已经在运行中")
            return

        logger.info(f"[CallMe] 正在启动后台服务 ({self._host}:{self._port})...")
        
        self._server_thread = threading.Thread(
            target=self._run_uvicorn,
            args=(app, self._host, self._port),
            daemon=True,
            name="CallMe-Uvicorn"
        )
        self._server_thread.start()
        self._is_running = True

    def stop(self):
        """停止服务"""
        if not self._is_running:
            logger.info("[CallMe] 服务未运行")
            return

        logger.info("[CallMe] 正在停止后台服务...")
        
        if self._server_instance:
            self._server_instance.should_exit = True
            # 等待线程结束? 由于是 daemon 线程，且 shutdown 也是为了 graceful exit
            # 这里我们简单标记停止
        
        self._is_running = False
        self._server_instance = None
        logger.info("[CallMe] 服务停止指令已下达")

    def get_status(self) -> str:
        if self._is_running:
            return f"运行中 (http://{self._host}:{self._port})"
        return "已停止"

    def _run_uvicorn(self, app, host: str, port: int):
        """在独立线程中运行 Uvicorn"""
        config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_level="info",
            loop="asyncio"
        )
        self._server_instance = uvicorn.Server(config)
        
        logger.info(f"[CallMe Uvicorn] Starting on {host}:{port}")
        try:
            self._server_instance.run()
        except Exception as e:
            logger.error(f"[CallMe Uvicorn] Error: {e}")
        finally:
            self._is_running = False
            logger.info("[CallMe Uvicorn] Stopped.")

# Global instance
call_me_service = CallMeService()
