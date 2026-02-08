import aiohttp
import logging
from typing import AsyncGenerator, Dict, Optional
from ..models import TTSProvider as TTSProviderModel  # DB Model

logger = logging.getLogger("call_me_tts")


class TTSManager:
    """
    TTS 管理器，负责路由 TTS 请求到不同的 Provider。
    """
    
    def __init__(self):
        # 缓存 providers 配置
        self._providers: Dict[str, TTSProviderModel] = {}
        # HTTP Session
        self._http_session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self.total_timeout_sec,
                connect=self.connect_timeout_sec,
                sock_read=self.read_timeout_sec,
            )
            connector = aiohttp.TCPConnector(limit=self.conn_limit)
            self._http_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self._http_session
        
    def configure(self, config: Dict):
        """配置 TTS Manager"""
        self.config = config
        self.type = config.get("type", "mock")
        self.api_url = config.get("api_url", "http://127.0.0.1:9880")
        self.default_voice_id = config.get("voice_id", "default")
        self.connect_timeout_sec = max(0.2, float(config.get("connect_timeout_sec", 3.0)))
        self.read_timeout_sec = max(0.5, float(config.get("read_timeout_sec", 20.0)))
        total_timeout = config.get("total_timeout_sec", None)
        try:
            total_timeout_val = float(total_timeout) if total_timeout is not None else None
        except Exception:
            total_timeout_val = None
        self.total_timeout_sec = None if (total_timeout_val is None or total_timeout_val <= 0) else total_timeout_val
        self.conn_limit = max(4, int(config.get("conn_limit", 32)))

    def _build_sovits_params(self, text: str, streaming_mode: bool) -> Dict:
        return {
            "text": text,
            "text_lang": self.config.get("text_lang", "zh"),
            "ref_audio_path": self.config.get("ref_audio_path", ""),
            "prompt_text": self.config.get("prompt_text", ""),
            "prompt_lang": self.config.get("prompt_lang", "zh"),
            "text_split_method": self.config.get("text_split_method", "cut5"),
            "streaming_mode": "true" if streaming_mode else "false",
            "media_type": "wav",
        }

    async def synthesize_stream(
        self, text: str, voice_id: str = None, provider_id: str = "default"
    ) -> AsyncGenerator[bytes, None]:
        """
        流式合成语音，尽早返回首包音频。
        """
        if not hasattr(self, "type"):
            self.configure({"type": "mock"})

        if self.type == "mock":
            return

        if self.type != "sovits":
            return

        endpoint = f"{self.api_url.rstrip('/')}/tts"
        params = self._build_sovits_params(text, streaming_mode=True)
        chunk_size = int(self.config.get("stream_chunk_size", 8192))
        if chunk_size < 1024:
            chunk_size = 1024

        try:
            session = await self.get_session()
            async with session.get(endpoint, params=params) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.warning(f"[TTS] SoVITS stream returned {resp.status}: {error_text}")
                    return

                async for chunk in resp.content.iter_chunked(chunk_size):
                    if chunk:
                        yield bytes(chunk)
        except Exception as e:
            logger.warning(f"[TTS] Streaming request failed: {e}")
            return
    
    async def synthesize(self, text: str, voice_id: str = None, provider_id: str = "default") -> Optional[bytes]:
        """
        合成语音
        """
        if not hasattr(self, "type"):
            self.configure({"type": "mock"})

        if self.type == "mock":
            return None 

        if self.type == "sovits":
            endpoint = f"{self.api_url.rstrip('/')}/tts"
            params = self._build_sovits_params(text, streaming_mode=False)

            try:
                session = await self.get_session()
                async with session.get(endpoint, params=params) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        error_text = await resp.text()
                        logger.warning(f"[TTS] SoVITS returned {resp.status}: {error_text}")
                        return None
            except Exception as e:
                logger.warning(f"[TTS] Request failed: {e}")
                return None
        
        return None

    async def close(self):
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

tts_manager = TTSManager()
