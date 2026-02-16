import collections
import enum
from typing import Optional

class VADMode(enum.Enum):
    WEBRTC = "webrtc"
    SILERO = "silero"
    ENERGY = "energy" #作为 fallback

class VADManager:
    """
    VAD 管理器，负责维护 VAD 状态、缓冲区和触发判定。
    """
    def __init__(self, config: dict):
        self.config = config
        
        # 参数
        self.speech_start_ms = config.get("speech_start_ms", 150)
        self.speech_end_ms = config.get("speech_end_ms", 800)
        self.min_utterance_ms = config.get("min_utterance_ms", 50)
        # Before "start" is triggered, tolerate a short silence gap so the
        # first weak syllable does not reset accumulation immediately.
        self.pre_start_silence_tolerance_ms = int(config.get("pre_start_silence_tolerance_ms", 80))
        if self.pre_start_silence_tolerance_ms < 0:
            self.pre_start_silence_tolerance_ms = 0
        self.mode = str(config.get("mode", "webrtc")).lower()
        self.energy_threshold = int(config.get("energy_threshold", 500))
        self.sample_rate = int(config.get("sample_rate", 16000))
        self.webrtc_aggressiveness = int(config.get("webrtc_aggressiveness", 2))
        if self.webrtc_aggressiveness < 0:
            self.webrtc_aggressiveness = 0
        if self.webrtc_aggressiveness > 3:
            self.webrtc_aggressiveness = 3

        self._webrtc_vad = None
        if self.mode == VADMode.WEBRTC.value:
            try:
                import webrtcvad

                self._webrtc_vad = webrtcvad.Vad(self.webrtc_aggressiveness)
            except Exception:
                # Fallback to energy mode if webrtcvad is unavailable.
                self.mode = VADMode.ENERGY.value
        
        # 状态
        self.is_speech_active = False
        self.speech_duration_ms = 0
        self.silence_duration_ms = 0
        
        # 缓冲区 (Frame level)
        # 假设每帧 20ms or 30ms，根据实际 audio chunk 大小决定
        # 这里仅作逻辑状态维护，具体的 audio processing 在外部循环调用 process
        
    def reset(self):
        self.is_speech_active = False
        self.speech_duration_ms = 0
        self.silence_duration_ms = 0

    def process(self, audio_chunk: bytes, chunk_duration_ms: int) -> bool:
        """
        处理一个音频块，返回**当前的** VAD 状态 (True=Speech, False=Silence)。
        注意：这只是瞬时判定，还需要结合平滑逻辑 (speech_start_ms 等) 判定是否触发事件。
        """
        if self.mode == VADMode.WEBRTC.value and self._webrtc_vad is not None:
            return self._webrtc_process(audio_chunk, chunk_duration_ms)

        # Silero 未接入时，回退到能量 VAD。
        return self._energy_vad(audio_chunk, self.energy_threshold)

    def _webrtc_process(self, audio_chunk: bytes, chunk_duration_ms: int) -> bool:
        # WebRTC VAD 仅支持 10/20/30ms 帧。
        if chunk_duration_ms not in (10, 20, 30):
            return self._energy_vad(audio_chunk, self.energy_threshold)

        expected_len = int(self.sample_rate * (chunk_duration_ms / 1000.0) * 2)
        if len(audio_chunk) < expected_len:
            return self._energy_vad(audio_chunk, self.energy_threshold)
        frame = audio_chunk[:expected_len]

        try:
            return bool(self._webrtc_vad.is_speech(frame, self.sample_rate))
        except Exception:
            return self._energy_vad(audio_chunk, self.energy_threshold)

    def _energy_vad(self, audio_chunk: bytes, threshold: int = 500) -> bool:
        """简单的能量 VAD (仅作示例/Fallback)"""
        if not audio_chunk:
            return False
        # 简易计算：抽样判断
        # production 应该用 numpy 或 audioop.rms
        import audioop
        try:
            rms = audioop.rms(audio_chunk, 2) # width=2 for PCM16
        except:
            rms = 0
        return rms > threshold

    def update_state(self, is_speech: bool, chunk_duration_ms: int) -> Optional[str]:
        """
        更新状态机，返回触发的事件: 'start' | 'end' | None
        """
        result = None
        
        if is_speech:
            self.silence_duration_ms = 0
            self.speech_duration_ms += chunk_duration_ms
            
            if not self.is_speech_active:
                if self.speech_duration_ms >= self.speech_start_ms:
                    self.is_speech_active = True
                    result = "start"
        else:
            # Silence
            if self.is_speech_active:
                self.silence_duration_ms += chunk_duration_ms
                if self.silence_duration_ms >= self.speech_end_ms:
                    if self.speech_duration_ms >= self.min_utterance_ms:
                        result = "end"
                    else:
                        # 说话时间太短，视为误触，不发送 end，直接 reset 状态
                        # 或者视为 short_utterance，逻辑由外部决定
                        pass
                    self.is_speech_active = False
                    self.speech_duration_ms = 0
                    self.silence_duration_ms = 0
            else:
                if self.speech_duration_ms > 0:
                    # Pre-start hangover: keep the already accumulated speech
                    # for a short silence window, then reset.
                    self.silence_duration_ms += chunk_duration_ms
                    if self.silence_duration_ms > self.pre_start_silence_tolerance_ms:
                        self.speech_duration_ms = 0
                        self.silence_duration_ms = 0
                else:
                    self.silence_duration_ms = 0
                
        return result
