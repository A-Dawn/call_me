import asyncio
import time
import uuid
from typing import Dict, Optional
from fastapi import WebSocket
from dataclasses import dataclass, field

from .state_machine import StateMachine, CallState
from ..utils.metrics import MetricsCollector


@dataclass
class SessionContext:
    session_id: str
    websocket: WebSocket
    state: StateMachine = field(default_factory=StateMachine)
    metrics: MetricsCollector = field(default_factory=MetricsCollector)

    # 核心并发锁
    # speaking_lock: 确保在说话时不会处理新的TTS任务(除非被打断)
    speaking_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # process_lock: 确保 LLM 处理流是线性的
    process_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # 任务队列 (用于 buffer 没处理完的输入，或者 LLM 输出的 chunks)
    # audio_output_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # 取消令牌
    # 当用户打断时，创建一个新的 Event 或 Future 来通知正在运行的任务停止
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    # 对话历史 (Context Management)
    # 存储格式: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    chat_history: list = field(default_factory=list)
    _history_limit: int = 80

    # Streaming ASR incremental text cache (UI feedback)
    _last_partial_text: str = ""
    _tracked_tasks: set[asyncio.Task] = field(default_factory=set)
    _prethink_task: Optional[asyncio.Task] = None
    _prethink_job_id: int = 0
    _prethink_hint: str = ""
    _prethink_hint_ready_at: float = 0.0
    _prethink_hint_from_turn: int = 0

    def __post_init__(self):
        self.metrics.metrics["session_id"] = self.session_id

    def create_cancel_token(self):
        """重置取消信号"""
        self._cancel_event.clear()

    def cancel_current_tasks(self):
        """触发取消信号"""
        self._cancel_event.set()
        self.metrics.increment("interrupt_count")
        self.cancel_tracked_tasks()
        self.cancel_prethink_task()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def append_history(self, role: str, content: str):
        if not content:
            return
        self.chat_history.append({"role": role, "content": content})
        if len(self.chat_history) > self._history_limit:
            overflow = len(self.chat_history) - self._history_limit
            if overflow > 0:
                del self.chat_history[:overflow]

    def track_task(self, task: asyncio.Task):
        self._tracked_tasks.add(task)

        def _done_cb(done_task: asyncio.Task):
            self._tracked_tasks.discard(done_task)

        task.add_done_callback(_done_cb)

    def has_tracked_tasks(self) -> bool:
        return any(not task.done() for task in self._tracked_tasks)

    def cancel_tracked_tasks(self):
        for task in tuple(self._tracked_tasks):
            if not task.done():
                task.cancel()

    def create_prethink_job(self) -> int:
        """Create a new prethink generation job id and invalidate older results."""
        self._prethink_job_id += 1
        return self._prethink_job_id

    def set_prethink_task(self, task: asyncio.Task, job_id: int):
        """Register current prethink task. Older task (if any) is cancelled."""
        self.cancel_prethink_task()
        self._prethink_job_id = max(self._prethink_job_id, int(job_id))
        self._prethink_task = task

        def _done_cb(done_task: asyncio.Task):
            if self._prethink_task is done_task:
                self._prethink_task = None

        task.add_done_callback(_done_cb)

    def cancel_prethink_task(self):
        """Cancel in-flight prethink task only (does not clear cached hint)."""
        task = self._prethink_task
        if task and not task.done():
            task.cancel()
        self._prethink_task = None

    def store_prethink_hint(self, job_id: int, hint: str, source_turn_id: int) -> bool:
        """Store prethink result iff this task is still the latest job."""
        if not hint:
            return False
        if int(job_id) != self._prethink_job_id:
            return False
        self._prethink_hint = hint
        self._prethink_hint_ready_at = time.perf_counter()
        self._prethink_hint_from_turn = int(source_turn_id or 0)
        return True

    def consume_prethink_hint(self) -> tuple[str, Optional[float], Optional[int]]:
        """Consume hint once. Returns (hint, age_ms, source_turn_id)."""
        hint = self._prethink_hint or ""
        if not hint:
            return "", None, None
        age_ms = None
        if self._prethink_hint_ready_at > 0:
            age_ms = max(0.0, (time.perf_counter() - self._prethink_hint_ready_at) * 1000.0)
        source_turn_id = self._prethink_hint_from_turn or None

        self._prethink_hint = ""
        self._prethink_hint_ready_at = 0.0
        self._prethink_hint_from_turn = 0
        return hint, age_ms, source_turn_id

    async def wait_tracked_tasks(self, timeout: float = 0.5):
        tasks = [task for task in self._tracked_tasks if not task.done()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
        except asyncio.TimeoutError:
            # Timeout is acceptable during forced interruption.
            pass


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, SessionContext] = {}
        self._lock = asyncio.Lock()

    async def create_session(self, websocket: WebSocket) -> SessionContext:
        session_id = str(uuid.uuid4())
        session = SessionContext(session_id=session_id, websocket=websocket)
        async with self._lock:
            self._sessions[session_id] = session
        return session

    async def remove_session(self, session_id: str):
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    async def get_session(self, session_id: str) -> Optional[SessionContext]:
        async with self._lock:
            return self._sessions.get(session_id)


# Global Instance
session_manager = SessionManager()
