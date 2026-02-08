import re
from typing import Generator, List, Tuple

class TextChunker:
    """
    文本分句器，负责将流式文本切分为用于 TTS 的片段。
    支持符号切分、长度切分。
    """
    
    # 强切分符号 (立即切分)
    STRONG_DELIMITERS = r"[。！？!?\n~～…—]+"
    # 弱切分符号 (长度够了才切)
    WEAK_DELIMITERS = r"[，,；;：:]+"
    
    def __init__(self, min_chunk_size: int = 10, max_chunk_size: int = 50):
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size
        self.buffer = ""
        self.seq_id = 0
    
    def reset(self):
        self.buffer = ""
        self.seq_id = 0

    def process(self, text_stream: str) -> Generator[Tuple[int, str, bool], None, None]:
        """
        处理流入的文本，生成 (seq, text, is_final)
        is_final: 是否是根据强逻辑切分的完整句子 (影响前端显示或停顿)
        """
        for char in text_stream:
            self.buffer += char
            
            # 检查强切分
            if re.search(self.STRONG_DELIMITERS, char):
                if self.buffer.strip():
                    yield self.seq_id, self.buffer.strip(), True
                    self.seq_id += 1
                    self.buffer = ""
                continue
            
            # 检查长度限制 (强制切分)
            if len(self.buffer) >= self.max_chunk_size:
                 # 尝试在之前的弱切分点切断（如果有）
                 # 这里简化处理：直接切分，实际可以优选最近的标点
                yield self.seq_id, self.buffer.strip(), False
                self.seq_id += 1
                self.buffer = ""
                continue

            # 检查弱切分
            if re.search(self.WEAK_DELIMITERS, char):
                if len(self.buffer) > self.min_chunk_size:
                    yield self.seq_id, self.buffer.strip(), False
                    self.seq_id += 1
                    self.buffer = ""
    
    def flush(self) -> Generator[Tuple[int, str, bool], None, None]:
        """刷新剩余缓冲区"""
        if self.buffer.strip():
            yield self.seq_id, self.buffer.strip(), True
            self.seq_id += 1
        self.buffer = ""
