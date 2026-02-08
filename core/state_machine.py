from enum import Enum

class CallState(Enum):
    IDLE = "idle"         # 空闲，等待唤醒
    LISTENING = "listening" # 正在听 (ASR Active)
    THINKING = "thinking" # 思考中 (LLM Generating)
    SPEAKING = "speaking" # 正在说 (TTS Playing)
    INTERRUPTED = "interrupted" # 被打断

class StateMachine:
    def __init__(self):
        self._current_state = CallState.IDLE
    
    @property
    def current(self) -> CallState:
        return self._current_state
    
    def transition_to(self, new_state: CallState) -> bool:
        """
        尝试流转到新状态。
        这里可以添加非法流转检测逻辑。
        """
        # old_state = self._current_state
        # logger.debug(f"[StateMachine] {old_state} -> {new_state}")
        self._current_state = new_state
        return True
