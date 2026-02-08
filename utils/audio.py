import base64
import io

# 尝试导入 soundfile 或 wave 用于处理 WAV
# 这里仅实现基础转换逻辑

def pcm16_to_wav_bytes(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """
    将 PCM16 裸数据封装为 WAV 格式
    """
    import wave
    
    with io.BytesIO() as wav_buffer:
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2) # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        
        return wav_buffer.getvalue()

def encode_wav_to_b64(wav_bytes: bytes) -> str:
    """Base64 编码"""
    return base64.b64encode(wav_bytes).decode("utf-8")

def decode_b64_to_bytes(b64_str: str) -> bytes:
    """Base64 解码"""
    return base64.b64decode(b64_str)
