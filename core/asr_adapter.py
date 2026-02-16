import abc
import asyncio
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger("call_me_asr")


class BaseASR(abc.ABC):
    """ASR 适配器基类"""
    
    def __init__(self):
        self._is_listening = False
    
    @abc.abstractmethod
    async def start_stream(self):
        """开始识别流"""
        pass

    @abc.abstractmethod
    async def push_audio_chunk(self, chunk: bytes):
        """推送音频数据"""
        pass
    
    @abc.abstractmethod
    async def get_partial(self) -> str:
        """获取中间结果"""
        pass # return "" if no update
    
    @abc.abstractmethod
    async def get_final(self) -> Optional[str]:
        """获取最终结果 (如有)"""
        pass
    
    @abc.abstractmethod
    async def stop_stream(self):
        """停止识别"""
        pass

    async def on_speech_end(self):
        """
        可选钩子：在 VAD 判定语音结束时调用。
        默认 no-op，流式 ASR 可在此做 input_finished/flush。
        """
        return None

class MockASR(BaseASR):
    """Mock 实现，方便测试"""
    async def start_stream(self):
        pass
    
    async def push_audio_chunk(self, chunk: bytes):
        pass
    
    async def get_partial(self) -> str:
        return ""
    
    async def get_final(self) -> Optional[str]:
        return "测试文本: 你好麦麦 (Mock)"
    
    async def stop_stream(self):
        pass

class HTTPASR(BaseASR):
    """基于 HTTP 请求的通用 ASR (适用于 OpenAI/FunASR 非流式接口)"""
    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.audio_buffer = bytearray()
        
    async def start_stream(self):
        self.audio_buffer = bytearray()
        
    async def push_audio_chunk(self, chunk: bytes):
        self.audio_buffer.extend(chunk)
        
    async def get_partial(self) -> str:
        # HTTP 接口通常不支持实时中间结果
        return ""
        
    async def get_final(self) -> Optional[str]:
        if not self.audio_buffer:
            return None
            
        import aiohttp
        try:
            # 构造 multipart form data
            data = aiohttp.FormData()
            data.add_field('file', self.audio_buffer, filename='audio.wav', content_type='audio/wav')
            # 某些接口可能需要 extra params, e.g. model="whisper-1"
            # 这里做成最通用的 file upload
            
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        # 假设返回格式 { "text": "..." } (OpenAI format)
                        return result.get("text", "")
                    else:
                        logger.warning(f"[ASR] API returned {resp.status}")
                        return None
        except Exception as e:
             logger.warning(f"[ASR] Request failed: {e}")
             return None
        finally:
             self.audio_buffer = bytearray() # Clear buffer

    async def stop_stream(self):
        self.audio_buffer = bytearray()

class SherpaASR(BaseASR):
    """基于 Sherpa-ONNX 的本地流式 ASR"""
    _shared_recognizers = {}
    _shared_lock = threading.Lock()
    _np_mod = None
    _sherpa_mod = None

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.recognizer = None
        self.stream = None
        self.sample_rate = 16000 # Default for most Sherpa models
        self.last_result = ""
        self.model_kind = str(config.get("model_kind", "transducer")).strip().lower()

        tokens = str(config.get("tokens_path", "")).strip()
        model_path = str(config.get("model_path", "")).strip()
        encoder = str(config.get("encoder_path", "")).strip()
        decoder = str(config.get("decoder_path", "")).strip()
        joiner = str(config.get("joiner_path", "")).strip()
        num_threads = int(config.get("num_threads", 1))
        provider = str(config.get("provider", "cpu"))

        if self.model_kind in ("zipformer2_ctc", "ctc"):
            if not all([tokens, model_path]):
                logger.warning("[SherpaASR] Missing tokens_path/model_path for zipformer2_ctc.")
                return
            try:
                if os.path.dirname(os.path.abspath(tokens)) != os.path.dirname(os.path.abspath(model_path)):
                    logger.warning(
                        "[SherpaASR] tokens_path and model_path are from different directories. "
                        "Ensure they belong to the same model package."
                    )
            except Exception:
                pass
            model_key = (
                "zipformer2_ctc",
                os.path.abspath(tokens),
                os.path.abspath(model_path),
                num_threads,
                provider,
                self.sample_rate,
            )
        elif self.model_kind in ("transducer", ""):
            self.model_kind = "transducer"
            if not all([tokens, encoder, decoder, joiner]):
                logger.warning("[SherpaASR] Missing tokens/encoder/decoder/joiner paths for transducer.")
                return
            model_key = (
                "transducer",
                os.path.abspath(tokens),
                os.path.abspath(encoder),
                os.path.abspath(decoder),
                os.path.abspath(joiner),
                num_threads,
                provider,
                self.sample_rate,
            )
        else:
            logger.warning(
                f"[SherpaASR] Unsupported model_kind='{self.model_kind}'. "
                "Use 'transducer' or 'zipformer2_ctc'."
            )
            return

        if not self._ensure_runtime_modules():
            logger.warning("[SherpaASR] sherpa-onnx or numpy not installed.")
            return

        self.np = SherpaASR._np_mod

        try:
            self.recognizer = self._get_or_create_shared_recognizer(model_key)
        except Exception as e:
            logger.warning(f"[SherpaASR] Failed to load model: {e}")

    @classmethod
    def _ensure_runtime_modules(cls) -> bool:
        if cls._np_mod is not None and cls._sherpa_mod is not None:
            return True
        try:
            import sherpa_onnx
            import numpy as np

            cls._np_mod = np
            cls._sherpa_mod = sherpa_onnx
            return True
        except ImportError:
            return False

    @classmethod
    def _get_or_create_shared_recognizer(cls, model_key):
        with cls._shared_lock:
            cached = cls._shared_recognizers.get(model_key)
            if cached is not None:
                logger.info("[SherpaASR] Reusing shared recognizer")
                return cached

            model_kind = model_key[0]
            if model_kind == "transducer":
                _, tokens, encoder, decoder, joiner, num_threads, provider, sample_rate = model_key
                logger.info(f"[SherpaASR] Loading transducer model from {encoder}...")
                recognizer = cls._sherpa_mod.OnlineRecognizer.from_transducer(
                    tokens=tokens,
                    encoder=encoder,
                    decoder=decoder,
                    joiner=joiner,
                    num_threads=num_threads,
                    provider=provider,
                    sample_rate=sample_rate,
                    feature_dim=80,
                )
            elif model_kind == "zipformer2_ctc":
                _, tokens, model_path, num_threads, provider, sample_rate = model_key
                logger.info(f"[SherpaASR] Loading zipformer2_ctc model from {model_path}...")
                recognizer = cls._sherpa_mod.OnlineRecognizer.from_zipformer2_ctc(
                    tokens=tokens,
                    model=model_path,
                    num_threads=num_threads,
                    provider=provider,
                    sample_rate=sample_rate,
                    feature_dim=80,
                )
            else:
                raise ValueError(f"Unsupported sherpa model kind: {model_kind}")

            cls._shared_recognizers[model_key] = recognizer
            logger.info("[SherpaASR] Shared model loaded successfully.")
            return recognizer

    async def start_stream(self):
        if self.recognizer:
            try:
                self.stream = self.recognizer.create_stream()
                self.last_result = ""
            except Exception as e:
                logger.warning(f"[SherpaASR] Failed to create stream: {e}")
                self.stream = None

    async def push_audio_chunk(self, chunk: bytes):
        if not self.recognizer or not self.stream:
            return
            
        # Convert PCM16 bytes to Float32 array
        # Assumption: Input is 16kHz, 16-bit mono. 
        # If your frontend sends 24k or 48k, you must resample before this or configure frontend.
        samples = self.np.frombuffer(chunk, dtype=self.np.int16).astype(self.np.float32) / 32768.0
        self.stream.accept_waveform(self.sample_rate, samples)
        
        try:
            while self.recognizer.is_ready(self.stream):
                self.recognizer.decode_stream(self.stream)
        except Exception as e:
            logger.warning(f"[SherpaASR] decode_stream failed: {e}")
            await self._recover_stream()

    async def _recover_stream(self):
        """Recover from stream-handle errors without crashing the WS pipeline."""
        try:
            if self.recognizer:
                self.stream = self.recognizer.create_stream()
                self.last_result = ""
        except Exception as e:
            logger.warning(f"[SherpaASR] stream recovery failed: {e}")
            self.stream = None

    async def _safe_get_result(self) -> str:
        if not self.recognizer or not self.stream:
            return ""
        try:
            return self.recognizer.get_result(self.stream)
        except IndexError as e:
            # sherpa_onnx can raise this when stream handle is stale/invalid.
            logger.warning(f"[SherpaASR] get_result invalid stream key: {e}")
            await self._recover_stream()
            return ""
        except Exception as e:
            logger.warning(f"[SherpaASR] get_result failed: {e}")
            return ""

    async def get_partial(self) -> str:
        return await self._safe_get_result()

    async def get_final(self) -> Optional[str]:
        if not self.recognizer or not self.stream:
            return None

        # Get current result (Sherpa streaming returns cumulative result usually)
        result = await self._safe_get_result()
        
        # Simple check: if result differs from last partial or just return it
        # For 'get_final', we strictly just want the text when VAD says end.
        if result:
            final_text = result
            # Reset stream for next utterance is handled by start_stream calling create_stream
            return final_text
        return None

    async def on_speech_end(self):
        if not self.recognizer or not self.stream:
            return
        try:
            # Tell sherpa this utterance has ended, so decoder can flush tail tokens.
            self.stream.input_finished()
            while self.recognizer.is_ready(self.stream):
                self.recognizer.decode_stream(self.stream)
        except Exception as e:
            logger.warning(f"[SherpaASR] on_speech_end flush failed: {e}")

    async def stop_stream(self):
        if self.stream:
            self.stream = None # release stream
        self.last_result = ""
        
    def process(self, partial_text: str) -> Optional[str]:
        # TODO: 实现防抖逻辑
        # 如果 partial_text 包含上一帧且长度增加 -> ok
        # 如果 partial_text 突变 -> wait debounce
        return partial_text
