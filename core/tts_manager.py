import copy
import json
import logging
import uuid
from typing import AsyncGenerator, Dict, Optional

import aiohttp

from ..models import TTSProvider as TTSProviderModel  # DB Model
from .volc_tts_protocol import (
    EventType,
    MessageType,
    ProtocolMessage,
    build_finish_connection,
    build_finish_session,
    build_start_connection,
    build_start_session,
    build_task_request,
    decode_message,
)

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

    @staticmethod
    def _as_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            norm = value.strip().lower()
            if norm in ("1", "true", "yes", "on"):
                return True
            if norm in ("0", "false", "no", "off"):
                return False
        if value is None:
            return default
        return bool(value)
    
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
        self._config_error: Optional[str] = None

        # Doubao/Volcengine bidirectional streaming config
        self.doubao_app_key = str(config.get("doubao_app_key", "") or "").strip()
        self.doubao_access_key = str(config.get("doubao_access_key", "") or "").strip()
        self.doubao_resource_id = str(config.get("doubao_resource_id", "") or "").strip()
        self.doubao_voice_type = str(config.get("doubao_voice_type", "") or "").strip()
        self.doubao_namespace = str(config.get("doubao_namespace", "BidirectionalTTS") or "BidirectionalTTS").strip()
        self.doubao_audio_format = str(config.get("doubao_audio_format", "pcm") or "pcm").strip().lower()
        self.doubao_sample_rate = max(8000, int(config.get("doubao_sample_rate", 24000)))
        self.doubao_enable_timestamp = self._as_bool(config.get("doubao_enable_timestamp", False), False)
        self.doubao_disable_markdown_filter = self._as_bool(config.get("doubao_disable_markdown_filter", False), False)

        if self.type == "doubao_ws":
            missing = []
            if not self.api_url:
                missing.append("api_url")
            if not self.doubao_app_key:
                missing.append("doubao_app_key")
            if not self.doubao_access_key:
                missing.append("doubao_access_key")
            if not self.doubao_resource_id:
                missing.append("doubao_resource_id")
            if not self.doubao_voice_type:
                missing.append("doubao_voice_type")
            if missing:
                self._config_error = f"missing required doubao config fields: {', '.join(missing)}"
            if self.doubao_audio_format != "pcm":
                self._config_error = "doubao_audio_format must be 'pcm' in current implementation"

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

        if self.type == "sovits":
            async for chunk in self._synthesize_stream_sovits(text):
                yield chunk
            return

        if self.type == "doubao_ws":
            if self._config_error:
                raise RuntimeError(f"[TTS] Doubao config invalid: {self._config_error}")
            async for chunk in self._synthesize_stream_doubao(text):
                yield chunk
            return

        logger.warning(f"[TTS] Unsupported provider type: {self.type}")
        return

    async def _synthesize_stream_sovits(self, text: str) -> AsyncGenerator[bytes, None]:
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

    def _build_doubao_headers(self) -> Dict[str, str]:
        return {
            "X-Api-App-Key": self.doubao_app_key,
            "X-Api-Access-Key": self.doubao_access_key,
            "X-Api-Resource-Id": self.doubao_resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

    def _build_doubao_request_base(self) -> Dict:
        return {
            "user": {"uid": str(uuid.uuid4())},
            "namespace": self.doubao_namespace,
            "req_params": {
                "speaker": self.doubao_voice_type,
                "audio_params": {
                    "format": self.doubao_audio_format,
                    "sample_rate": self.doubao_sample_rate,
                    "enable_timestamp": self.doubao_enable_timestamp,
                },
                "additions": json.dumps(
                    {"disable_markdown_filter": self.doubao_disable_markdown_filter},
                    ensure_ascii=False,
                ),
            },
        }

    async def _receive_doubao_message(self, ws: aiohttp.ClientWebSocketResponse) -> ProtocolMessage:
        while True:
            frame = await ws.receive()
            if frame.type == aiohttp.WSMsgType.BINARY:
                return decode_message(bytes(frame.data))
            if frame.type == aiohttp.WSMsgType.CLOSE:
                raise RuntimeError("[TTS] Doubao websocket closed by server")
            if frame.type == aiohttp.WSMsgType.CLOSED:
                raise RuntimeError("[TTS] Doubao websocket is closed")
            if frame.type == aiohttp.WSMsgType.ERROR:
                raise RuntimeError(f"[TTS] Doubao websocket error: {ws.exception()}")
            if frame.type == aiohttp.WSMsgType.TEXT:
                text = str(frame.data or "")
                raise RuntimeError(f"[TTS] Doubao websocket returned unexpected text frame: {text[:200]}")
            # Ignore ping/pong/continuation frames.

    @staticmethod
    def _payload_to_text(payload: bytes) -> str:
        if not payload:
            return ""
        text = payload.decode("utf-8", errors="ignore")
        if not text:
            return ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                msg = parsed.get("message") or parsed.get("msg") or parsed.get("error")
                if msg:
                    return f"{msg} ({text})"
        except Exception:
            pass
        return text

    def _format_protocol_error(self, stage: str, message: ProtocolMessage) -> str:
        payload_text = self._payload_to_text(message.payload)
        details = (
            f"[TTS] Doubao {stage} failed: "
            f"type={int(message.msg_type)} event={int(message.event)} error_code={int(message.error_code)}"
        )
        if payload_text:
            details += f" payload={payload_text}"
        return details

    async def _expect_doubao_event(
        self, ws: aiohttp.ClientWebSocketResponse, expected_event: EventType, stage: str
    ) -> ProtocolMessage:
        message = await self._receive_doubao_message(ws)
        if message.msg_type == MessageType.ERROR:
            raise RuntimeError(self._format_protocol_error(stage, message))
        if message.msg_type != MessageType.FULL_SERVER_RESPONSE:
            raise RuntimeError(
                f"[TTS] Doubao {stage} unexpected message type: "
                f"type={int(message.msg_type)} event={int(message.event)}"
            )
        if int(message.event) == int(expected_event):
            return message
        if int(message.event) in (int(EventType.CONNECTION_FAILED), int(EventType.SESSION_FAILED)):
            raise RuntimeError(self._format_protocol_error(stage, message))
        raise RuntimeError(
            f"[TTS] Doubao {stage} unexpected event: got={int(message.event)} expected={int(expected_event)}"
        )

    async def _synthesize_stream_doubao(self, text: str) -> AsyncGenerator[bytes, None]:
        session = await self.get_session()
        headers = self._build_doubao_headers()
        session_id = str(uuid.uuid4())
        audio_received = False
        ws: Optional[aiohttp.ClientWebSocketResponse] = None

        try:
            ws = await session.ws_connect(self.api_url, headers=headers, heartbeat=20, autoping=True)
            await ws.send_bytes(build_start_connection())
            await self._expect_doubao_event(ws, EventType.CONNECTION_STARTED, "start_connection")

            base_request = self._build_doubao_request_base()
            start_session_payload = copy.deepcopy(base_request)
            start_session_payload["event"] = int(EventType.START_SESSION)
            await ws.send_bytes(
                build_start_session(
                    session_id=session_id,
                    payload=json.dumps(start_session_payload, ensure_ascii=False).encode("utf-8"),
                )
            )
            await self._expect_doubao_event(ws, EventType.SESSION_STARTED, "start_session")

            task_payload = copy.deepcopy(base_request)
            task_payload["event"] = int(EventType.TASK_REQUEST)
            req_params = dict(task_payload.get("req_params") or {})
            req_params["text"] = text
            task_payload["req_params"] = req_params
            await ws.send_bytes(
                build_task_request(
                    session_id=session_id,
                    payload=json.dumps(task_payload, ensure_ascii=False).encode("utf-8"),
                )
            )
            await ws.send_bytes(build_finish_session(session_id=session_id))

            while True:
                message = await self._receive_doubao_message(ws)
                if message.msg_type == MessageType.AUDIO_ONLY_SERVER:
                    if message.payload:
                        audio_received = True
                        yield bytes(message.payload)
                    continue
                if message.msg_type == MessageType.ERROR:
                    raise RuntimeError(self._format_protocol_error("streaming", message))
                if message.msg_type != MessageType.FULL_SERVER_RESPONSE:
                    logger.debug(
                        f"[TTS] Doubao ignore frame type={int(message.msg_type)} event={int(message.event)}"
                    )
                    continue
                if int(message.event) == int(EventType.SESSION_FINISHED):
                    break
                if int(message.event) in (int(EventType.SESSION_FAILED), int(EventType.CONNECTION_FAILED)):
                    raise RuntimeError(self._format_protocol_error("streaming", message))
                logger.debug(
                    f"[TTS] Doubao non-terminal event type={int(message.msg_type)} event={int(message.event)}"
                )

            if not audio_received:
                raise RuntimeError("[TTS] Doubao stream returned no audio payload")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"[TTS] Doubao stream request failed: {e}") from e
        finally:
            if ws is not None and not ws.closed:
                try:
                    await ws.send_bytes(build_finish_connection())
                except Exception:
                    pass
                try:
                    await ws.close()
                except Exception:
                    pass
    
    async def synthesize(self, text: str, voice_id: str = None, provider_id: str = "default") -> Optional[bytes]:
        """
        合成语音
        """
        if not hasattr(self, "type"):
            self.configure({"type": "mock"})

        if self.type == "mock":
            return None 

        if self.type == "doubao_ws":
            logger.warning("[TTS] Doubao provider only supports streaming synthesize_stream()")
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
