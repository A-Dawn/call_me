import asyncio
import json
import logging
import re
import time
from collections import deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .core.asr_adapter import MockASR
from .core.emotion import infer_emotion, normalize_emotion, strip_leading_emotion_tag
from .core.llm_adapter import LLMAdapter
from .core.prethink import build_prethink_injection_block, build_prethink_prompt, sanitize_prethink_result
from .core.prompt_builder import build_system_prompt
from .core.session_manager import session_manager
from .core.state_machine import CallState
from .core.text_chunker import TextChunker
from .core.tts_manager import tts_manager
from .core.vad import VADManager
from .utils.audio import decode_b64_to_bytes, encode_wav_to_b64, pcm16_to_wav_bytes

logger = logging.getLogger("call_me_ws")
router = APIRouter()

CHUNK_DURATION_MS = 20
MEANINGFUL_TTS_TEXT_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7a3]")

_PRETHINK_DEFAULTS = {
    "enabled": False,
    "model_name": "",
    "timeout_ms": 600,
    "max_history_messages": 10,
    "max_output_chars": 220,
    "min_user_text_chars": 2,
}

_PLAYBACK_DEFAULTS = {
    "startup_buffer_ms": 120,
    "startup_max_wait_ms": 120,
    "schedule_lead_ms": 30,
}


def _resolve_prethink_config(plugin_config: dict | None) -> dict:
    cfg = {}
    if isinstance(plugin_config, dict):
        maybe = plugin_config.get("prethink", {})
        if isinstance(maybe, dict):
            cfg = maybe

    enabled = bool(cfg.get("enabled", _PRETHINK_DEFAULTS["enabled"]))
    model_name = str(cfg.get("model_name", _PRETHINK_DEFAULTS["model_name"]) or "").strip()
    timeout_ms = max(100, int(cfg.get("timeout_ms", _PRETHINK_DEFAULTS["timeout_ms"])))
    max_history_messages = max(2, int(cfg.get("max_history_messages", _PRETHINK_DEFAULTS["max_history_messages"])))
    max_output_chars = max(60, int(cfg.get("max_output_chars", _PRETHINK_DEFAULTS["max_output_chars"])))
    min_user_text_chars = max(1, int(cfg.get("min_user_text_chars", _PRETHINK_DEFAULTS["min_user_text_chars"])))

    return {
        "enabled": enabled,
        "model_name": model_name,
        "timeout_ms": timeout_ms,
        "max_history_messages": max_history_messages,
        "max_output_chars": max_output_chars,
        "min_user_text_chars": min_user_text_chars,
    }


def _resolve_playback_config(plugin_config: dict | None) -> dict:
    audio_cfg = {}
    if isinstance(plugin_config, dict):
        maybe = plugin_config.get("audio", {})
        if isinstance(maybe, dict):
            audio_cfg = maybe

    startup_buffer_ms = int(audio_cfg.get("playback_startup_buffer_ms", _PLAYBACK_DEFAULTS["startup_buffer_ms"]))
    startup_max_wait_ms = int(audio_cfg.get("playback_startup_max_wait_ms", _PLAYBACK_DEFAULTS["startup_max_wait_ms"]))
    schedule_lead_ms = int(audio_cfg.get("playback_schedule_lead_ms", _PLAYBACK_DEFAULTS["schedule_lead_ms"]))

    startup_buffer_ms = max(0, min(1000, startup_buffer_ms))
    startup_max_wait_ms = max(0, min(1000, startup_max_wait_ms))
    schedule_lead_ms = max(0, min(300, schedule_lead_ms))

    return {
        "startup_buffer_ms": startup_buffer_ms,
        "startup_max_wait_ms": startup_max_wait_ms,
        "schedule_lead_ms": schedule_lead_ms,
    }


def _pick_last_user_text(chat_history: list[dict]) -> str:
    for msg in reversed(chat_history):
        if msg.get("role") == "user":
            return str(msg.get("content", "")).strip()
    return ""


def _sanitize_tts_text(text: str) -> str:
    if not text:
        return ""
    cleaned = text.strip()
    # Drop leaked leading emotion tags to avoid sending control tokens to TTS.
    _, stripped = strip_leading_emotion_tag(cleaned)
    cleaned = stripped.strip() if stripped is not None else cleaned
    return cleaned


def _is_meaningful_tts_text(text: str) -> bool:
    return bool(MEANINGFUL_TTS_TEXT_RE.search(text or ""))


def _is_wav_bytes(payload: bytes) -> bool:
    return len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WAVE"


def _extract_wav_sample_rate(payload: bytes) -> int | None:
    if not _is_wav_bytes(payload) or len(payload) < 28:
        return None
    try:
        sample_rate = int.from_bytes(payload[24:28], byteorder="little", signed=False)
    except Exception:
        return None
    if sample_rate <= 0:
        return None
    return sample_rate


def _strip_empty_wav_header_prefix(payload: bytes) -> tuple[bytes, bool]:
    """
    GPT-SoVITS streaming wav can emit a header-only first frame (44 bytes),
    and transport chunking may concatenate that header with following raw PCM.
    Strip this synthetic header so trailing bytes can be handled as PCM16.
    """
    if not _is_wav_bytes(payload) or len(payload) < 44:
        return payload, False
    riff_size = int.from_bytes(payload[4:8], byteorder="little", signed=False)
    data_size = int.from_bytes(payload[40:44], byteorder="little", signed=False)
    if riff_size == 36 and data_size == 0:
        return payload[44:], True
    return payload, False


def _to_playable_wav_chunk(
    chunk_bytes: bytes, sample_rate: int, channels: int = 1, pcm_carry: bytes = b""
) -> tuple[bytes, bytes]:
    """
    Normalize stream chunks so each outbound payload is independently playable WAV.
    - If chunk is already WAV, pass through.
    - If chunk is raw PCM16, wrap into WAV (keeping odd-byte carry across chunks).
    """
    if not chunk_bytes:
        return b"", pcm_carry

    normalized_bytes, stripped_empty_header = _strip_empty_wav_header_prefix(chunk_bytes)
    if stripped_empty_header:
        chunk_bytes = normalized_bytes
        if not chunk_bytes:
            return b"", b""
    elif _is_wav_bytes(chunk_bytes):
        return chunk_bytes, b""

    pcm_bytes = (pcm_carry or b"") + chunk_bytes
    if len(pcm_bytes) < 2:
        return b"", pcm_bytes

    next_carry = b""
    if len(pcm_bytes) % 2 == 1:
        next_carry = pcm_bytes[-1:]
        pcm_bytes = pcm_bytes[:-1]

    if not pcm_bytes:
        return b"", next_carry

    return pcm16_to_wav_bytes(pcm_bytes, sample_rate=sample_rate, channels=channels), next_carry


def _resolve_leading_emotion_prefix(prefix: str) -> tuple[str, str | None, str]:
    """
    Resolve a possible leading emotion tag from streamed LLM prefix.
    Returns:
      - ("resolved", emotion, cleaned_text): found a valid leading tag.
      - ("need_more", None, ""): looks like an incomplete leading tag.
      - ("no_tag", None, original_text): no usable leading tag.
    """
    if not prefix:
        return "need_more", None, ""

    tag_emotion, cleaned = strip_leading_emotion_tag(prefix)
    if tag_emotion:
        return "resolved", tag_emotion, cleaned

    stripped = prefix.lstrip()
    if not stripped:
        return "need_more", None, ""

    # Wait for split chunks when model starts with a tag such as:
    # <emo:happy> / [emotion:happy] / 【情绪:开心】
    if (stripped.startswith("<emo") or stripped.startswith("<emotion")) and ">" not in stripped:
        return "need_more", None, ""
    if (stripped.startswith("[emo") or stripped.startswith("[emotion")) and "]" not in stripped:
        return "need_more", None, ""
    if (stripped.startswith("【情绪") or stripped.startswith("【emotion")) and "】" not in stripped:
        return "need_more", None, ""

    return "no_tag", None, prefix


async def _run_process_turn_locked(session, llm, text, plugin_config, timing_ctx):
    # Ensure one process_turn pipeline is active per session.
    async with session.process_lock:
        if session.is_cancelled:
            return
        await process_turn(session, llm, None, text, plugin_config, timing_ctx)


def _spawn_turn_task(session, llm, text, plugin_config, timing_ctx):
    task = asyncio.create_task(
        _run_process_turn_locked(session, llm, text, plugin_config, timing_ctx),
        name=f"call_me_turn_{session.session_id}_{timing_ctx.get('turn_id', 'n/a')}",
    )
    session.track_task(task)
    return task


async def _run_prethink_job(session, llm, model_name: str, prompt: str, timeout_ms: int, max_output_chars: int, job_id: int, source_turn_id: int):
    started = time.perf_counter()
    local_cancel = asyncio.Event()
    logger.info(
        f"[Prethink] prethink_start session={session.session_id} job={job_id} "
        f"source_turn={source_turn_id} model={model_name} timeout_ms={timeout_ms}"
    )

    async def _collect_stream() -> str:
        chunks: list[str] = []
        total_len = 0
        async for chunk in llm.generate_stream(prompt, model_name, local_cancel):
            if not chunk:
                continue
            chunks.append(chunk)
            total_len += len(chunk)
            if total_len >= max_output_chars * 3:
                break
        return "".join(chunks)

    try:
        raw = await asyncio.wait_for(_collect_stream(), timeout=timeout_ms / 1000.0)
        hint = sanitize_prethink_result(raw, max_chars=max_output_chars)
        if not hint:
            logger.info(
                f"[Prethink] prethink_miss session={session.session_id} job={job_id} reason=empty"
            )
            return

        if session.store_prethink_hint(job_id, hint, source_turn_id):
            latency_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                f"[Prethink] prethink_ready session={session.session_id} job={job_id} "
                f"latency_ms={latency_ms:.1f} chars={len(hint)}"
            )
        else:
            logger.info(
                f"[Prethink] prethink_miss session={session.session_id} job={job_id} reason=stale"
            )
    except asyncio.TimeoutError:
        logger.info(f"[Prethink] prethink_timeout session={session.session_id} job={job_id}")
    except asyncio.CancelledError:
        local_cancel.set()
        logger.info(f"[Prethink] prethink_cancelled session={session.session_id} job={job_id}")
        raise
    except Exception as e:
        logger.warning(f"[Prethink] prethink_error session={session.session_id} job={job_id}: {e}")


def _spawn_prethink_task(session, llm, plugin_config, source_turn_id: int):
    prethink_cfg = _resolve_prethink_config(plugin_config)
    if not prethink_cfg["enabled"]:
        return None

    chat_history = session.chat_history
    if not chat_history:
        return None

    last_user_text = _pick_last_user_text(chat_history)
    if len(last_user_text) < prethink_cfg["min_user_text_chars"]:
        logger.info(
            f"[Prethink] prethink_miss session={session.session_id} reason=user_text_too_short"
        )
        return None

    recent_history = chat_history[-prethink_cfg["max_history_messages"] :]
    prompt = build_prethink_prompt(recent_history)

    llm_cfg = plugin_config.get("llm", {}) if isinstance(plugin_config, dict) else {}
    fallback_model_name = llm_cfg.get("model_name", "replyer") if isinstance(llm_cfg, dict) else "replyer"
    model_name = prethink_cfg["model_name"] or fallback_model_name

    job_id = session.create_prethink_job()
    task = asyncio.create_task(
        _run_prethink_job(
            session=session,
            llm=llm,
            model_name=model_name,
            prompt=prompt,
            timeout_ms=prethink_cfg["timeout_ms"],
            max_output_chars=prethink_cfg["max_output_chars"],
            job_id=job_id,
            source_turn_id=int(source_turn_id or 0),
        ),
        name=f"call_me_prethink_{session.session_id}_{job_id}",
    )
    session.set_prethink_task(task, job_id=job_id)
    return task


@router.websocket("/ws/call")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session = None

    # 初始化组件
    from .core.service import call_me_service

    plugin_config = getattr(call_me_service, "config", {})
    asr_config = plugin_config.get("asr", {}) if isinstance(plugin_config, dict) else {}
    if not isinstance(asr_config, dict):
        asr_config = {}
    asr_final_delay_ms = max(0, min(1000, int(asr_config.get("final_delay_ms", 80))))

    # 动态实例化 ASR
    asr_type = asr_config.get("type", "mock")
    if asr_type == "mock":
        asr = MockASR()
    elif asr_type == "sherpa":
        try:
            from .core.asr_adapter import SherpaASR

            sherpa_config = plugin_config.get("sherpa", {})
            asr = SherpaASR(sherpa_config)
            # Fall back if recognizer is unavailable (OOM/model load failure).
            if getattr(asr, "recognizer", None) is None:
                logger.warning("[WS] SherpaASR recognizer not available; falling back to MockASR")
                asr = MockASR()
        except Exception as e:
            logger.warning(f"[WS] Failed to init SherpaASR ({e}); falling back to MockASR")
            asr = MockASR()
    else:
        # HTTP ASR (FunASR/OpenAI)
        from .core.asr_adapter import HTTPASR

        api_url = asr_config.get("api_url", "http://127.0.0.1:10095")
        asr = HTTPASR(api_url)

    # Configure TTS from plugin_config (standalone uvicorn needs this too)
    try:
        if isinstance(plugin_config, dict):
            tts_manager.configure(plugin_config.get("tts", {}) or {})
    except Exception as e:
        logger.warning(f"[WS] Failed to configure TTS manager: {e}")

    # VAD config
    vad_config = plugin_config.get("vad", {}) if isinstance(plugin_config, dict) else {}
    if not isinstance(vad_config, dict):
        vad_config = {}
    if not vad_config.get("mode"):
        vad_config = {**vad_config, "mode": "energy"}
    vad = VADManager(vad_config)

    # Keep preroll to avoid clipping utterance head before VAD "start".
    # WebRTC VAD can start late for weak first syllables, so default is longer.
    pre_roll_ms = int(vad_config.get("pre_roll_ms", max(int(vad_config.get("speech_start_ms", 150)) + 120, 420)))
    pre_roll_frames = max(1, min(80, (pre_roll_ms // CHUNK_DURATION_MS) + 1))
    pre_roll_audio = deque(maxlen=pre_roll_frames)
    logger.info(f"[WS] VAD preroll configured: pre_roll_ms={pre_roll_ms} frames={pre_roll_frames}")

    llm = LLMAdapter()
    await asr.start_stream()
    playback_cfg = _resolve_playback_config(plugin_config if isinstance(plugin_config, dict) else {})

    try:
        session = await session_manager.create_session(websocket)
        logger.info(f"[WS] Session created: {session.session_id}")

        async def schedule_turn(user_text: str, source: str, asr_final_ms: float | None):
            if not user_text:
                return
            session.cancel_prethink_task()
            session.create_prethink_job()

            # New turn: cancel previous tasks and wait briefly for cleanup.
            if session.state.current in (CallState.THINKING, CallState.SPEAKING) or session.has_tracked_tasks():
                session.cancel_current_tasks()
                await session.wait_tracked_tasks(timeout=0.5)
            session.create_cancel_token()

            session.state.transition_to(CallState.THINKING)
            await websocket.send_json({"type": "state.update", "state": "thinking"})

            session.append_history("user", user_text)

            turn_id = getattr(session, "_turn_seq", 0) + 1
            session._turn_seq = turn_id
            prethink_hint, prethink_age_ms, prethink_source_turn_id = session.consume_prethink_hint()
            prethink_hit = 1 if prethink_hint else 0
            timing_ctx = {
                "turn_id": turn_id,
                "source": source,
                "turn_start_at": time.perf_counter(),
                "asr_final_ms": asr_final_ms,
                "prethink_hint": prethink_hint,
                "prethink_hit": prethink_hit,
                "prethink_age_ms": prethink_age_ms,
                "prethink_source_turn_id": prethink_source_turn_id,
            }
            if asr_final_ms is not None:
                logger.info(
                    f"[Perf][{session.session_id}][turn={turn_id}] "
                    f"asr_final_ms={asr_final_ms:.1f} text_len={len(user_text)}"
                )
            logger.info(
                f"[Prethink] {'prethink_hit' if prethink_hit else 'prethink_miss'} "
                f"session={session.session_id} turn={turn_id} "
                f"age_ms={prethink_age_ms if prethink_age_ms is not None else 'n/a'} "
                f"source_turn={prethink_source_turn_id if prethink_source_turn_id is not None else 'n/a'}"
            )
            _spawn_turn_task(session, llm, user_text, plugin_config, timing_ctx)

        while True:
            # 协议定义:
            # { "type": "client.hello" | "input.audio_chunk" | "input.text" | ... , "data": ... }
            message = await websocket.receive_json()
            msg_type = message.get("type")
            data = message.get("data", {})

            if msg_type == "client.hello":
                await websocket.send_json({"type": "server.hello", "session_id": session.session_id})
                await websocket.send_json({"type": "client.config", "data": {"playback": playback_cfg}})
                await websocket.send_json({"type": "avatar.state", "emotion": "neutral", "source": "system"})
                continue

            if msg_type == "input.audio_chunk":
                try:
                    b64_audio = data.get("chunk", "")
                    if not b64_audio:
                        continue

                    audio_bytes = decode_b64_to_bytes(b64_audio)
                    pre_roll_audio.append(audio_bytes)

                    # 1) VAD on current chunk
                    is_speech = vad.process(audio_bytes, CHUNK_DURATION_MS)
                    event = vad.update_state(is_speech, CHUNK_DURATION_MS)

                    if event == "start":
                        logger.info("[WS] Speech started")
                        await asr.start_stream()
                        session._last_partial_text = ""

                        # Feed preroll to ASR to avoid clipping speech head.
                        for frame in pre_roll_audio:
                            await asr.push_audio_chunk(frame)
                        pre_roll_audio.clear()

                        # Barge-in if assistant is speaking.
                        if session.state.current == CallState.SPEAKING:
                            session.cancel_current_tasks()
                            session.state.transition_to(CallState.INTERRUPTED)
                            try:
                                await websocket.send_json({"type": "state.update", "state": "interrupted"})
                            except Exception:
                                pass
                            await session.wait_tracked_tasks(timeout=0.3)
                    elif vad.is_speech_active:
                        # During active speech, feed current chunk.
                        await asr.push_audio_chunk(audio_bytes)

                    # 2) Partial ASR feedback (streaming ASR only)
                    if vad.is_speech_active:
                        partial_text = await asr.get_partial()
                        if partial_text:
                            last_text = getattr(session, "_last_partial_text", "")
                            if partial_text != last_text:
                                await websocket.send_json(
                                    {"type": "input.text_update", "text": partial_text, "is_final": False}
                                )
                                session._last_partial_text = partial_text

                    # 3) End-of-utterance -> ASR final -> schedule LLM/TTS
                    if event == "end":
                        logger.info("[WS] Speech ended")
                        try:
                            await asr.on_speech_end()
                        except Exception:
                            pass
                        if asr_final_delay_ms > 0:
                            await asyncio.sleep(asr_final_delay_ms / 1000.0)
                        asr_final_t0 = time.perf_counter()
                        final_text = await asr.get_final()
                        asr_final_ms = (time.perf_counter() - asr_final_t0) * 1000.0
                        pre_roll_audio.clear()

                        if not final_text:
                            logger.warning("[WS] ASR recognized nothing or failed")
                            continue

                        await websocket.send_json({"type": "input.text_update", "text": final_text, "is_final": True})
                        session._last_partial_text = ""
                        await schedule_turn(final_text, "audio", asr_final_ms)
                except Exception as e:
                    logger.error(f"[WS] Error processing audio chunk: {e}", exc_info=True)
                continue

            if msg_type == "input.text":
                text = str(data.get("text", "")).strip()
                if not text:
                    continue
                await schedule_turn(text, "text", None)
                continue

            if msg_type == "control.interrupt":
                session.cancel_current_tasks()
                session.state.transition_to(CallState.INTERRUPTED)
                try:
                    await websocket.send_json({"type": "state.update", "state": "interrupted"})
                except Exception:
                    pass
                await session.wait_tracked_tasks(timeout=0.3)
                continue

            logger.debug(f"[WS] Unknown msg type: {msg_type}")

    except WebSocketDisconnect:
        if session:
            logger.info(f"[WS] Disconnected: {session.session_id}")
    except json.JSONDecodeError as e:
        logger.warning(f"[WS] Received non-JSON frame, closing: {e}")
        try:
            await websocket.close(code=1003)
        except Exception:
            pass
    except Exception as e:
        logger.error(f"[WS] Error: {e}", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        try:
            await asr.stop_stream()
        except Exception:
            pass
        if session:
            session.cancel_current_tasks()
            await session.wait_tracked_tasks(timeout=0.5)
            await session_manager.remove_session(session.session_id)


async def process_turn(session, llm, chunker, text, plugin_config=None, timing_ctx=None):
    """
    处理一轮对话：LLM -> Chunker -> TTS -> Send Audio
    """
    logger.info(f"[ProcessTurn] Start processing text: {text[:20]}...")
    session.state.transition_to(CallState.THINKING)

    system_prompt = build_system_prompt()
    llm_cfg = plugin_config.get("llm", {}) if isinstance(plugin_config, dict) else {}
    history_window_messages = 12
    if isinstance(llm_cfg, dict):
        try:
            history_window_messages = int(llm_cfg.get("history_window_messages", 12))
        except Exception:
            history_window_messages = 12
    history_window_messages = max(2, min(120, history_window_messages))
    recent_history = session.chat_history[-history_window_messages:]
    prethink_hint = str((timing_ctx or {}).get("prethink_hint", "") or "").strip()

    # 构造 Full Prompt
    full_prompt = f"{system_prompt}\n\n"
    if prethink_hint:
        injection_block = build_prethink_injection_block(prethink_hint)
        if injection_block:
            full_prompt += f"{injection_block}\n\n"
    for msg in recent_history:
        role = "用户" if msg["role"] == "user" else "MaiBot"
        full_prompt += f"{role}: {msg['content']}\n"

    full_prompt += "MaiBot: "

    full_response_text = ""
    turn_chunker = TextChunker()
    output_sample_rate = 24000
    if isinstance(plugin_config, dict):
        audio_cfg = plugin_config.get("audio", {})
        if isinstance(audio_cfg, dict):
            output_sample_rate = int(audio_cfg.get("sample_rate", 24000))
        tts_cfg = plugin_config.get("tts", {})
        if isinstance(tts_cfg, dict) and str(tts_cfg.get("type", "")).strip() == "cosyvoice_http":
            output_sample_rate = int(tts_cfg.get("cosyvoice_sample_rate", output_sample_rate))

    model_config_name = "replyer"
    if isinstance(llm_cfg, dict):
        model_config_name = llm_cfg.get("model_name", "replyer")

    logger.info(f"[ProcessTurn] Calling LLM generate_stream with model_name='{model_config_name}'...")
    try:
        turn_id = (timing_ctx or {}).get("turn_id", "n/a")
        try:
            numeric_turn_id = int(turn_id)
        except Exception:
            numeric_turn_id = 0
        turn_source = (timing_ctx or {}).get("source", "unknown")
        turn_start_at = float((timing_ctx or {}).get("turn_start_at", time.perf_counter()))
        asr_final_ms = (timing_ctx or {}).get("asr_final_ms")
        prethink_hit = int((timing_ctx or {}).get("prethink_hit", 1 if prethink_hint else 0))
        prethink_age_ms = (timing_ctx or {}).get("prethink_age_ms")
        prethink_source_turn_id = (timing_ctx or {}).get("prethink_source_turn_id")
        llm_start_at = time.perf_counter()
        first_llm_token_at = None
        first_tts_request_at = None
        first_tts_audio_at = None
        tts_audio_chunks_sent = 0
        tts_segment_count = 0

        tts_queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        first_response_emotion: str | None = None
        current_response_emotion: str | None = None
        pending_leading_prefix = ""
        awaiting_leading_emotion = True
        leading_prefix_chunks = 0

        async def send_speaking_state_once():
            if session.state.current != CallState.SPEAKING:
                session.state.transition_to(CallState.SPEAKING)
                try:
                    await session.websocket.send_json({"type": "state.update", "state": "speaking"})
                except Exception:
                    pass

        async def send_avatar_state(emotion: str, source: str):
            nonlocal current_response_emotion
            emotion = normalize_emotion(emotion, default="neutral")
            if current_response_emotion == emotion:
                return
            current_response_emotion = emotion
            try:
                await session.websocket.send_json(
                    {"type": "avatar.state", "emotion": emotion, "source": source, "turn_id": turn_id}
                )
            except Exception:
                pass

        async def synthesize_and_send(seq_id: int, chunk_text: str, is_final: bool):
            nonlocal first_tts_request_at, first_tts_audio_at, tts_audio_chunks_sent, tts_segment_count
            chunk_text = _sanitize_tts_text(chunk_text)
            if not _is_meaningful_tts_text(chunk_text):
                logger.debug(f"[ProcessTurn] Skip non-meaningful TTS chunk: seq={seq_id}")
                return

            logger.debug(f"[ProcessTurn] Synthesizing chunk {seq_id}: {chunk_text[:20]}...")
            tts_segment_count += 1
            if first_tts_request_at is None:
                first_tts_request_at = time.perf_counter()
            sent_stream_audio = False
            sent_stream_text = False
            pending_audio = bytearray()
            emit_size = 16384
            pcm_carry = b""
            stream_sample_rate = output_sample_rate
            stream_sample_rate_locked = False

            async def send_text_stream_once():
                nonlocal sent_stream_text
                if sent_stream_text:
                    return
                try:
                    await session.websocket.send_json(
                        {"type": "tts.text_stream", "seq": seq_id, "data": {"seq": seq_id, "text": chunk_text}}
                    )
                except Exception:
                    pass
                sent_stream_text = True

            async for audio_part in tts_manager.synthesize_stream(chunk_text, "voice_id"):
                if session.is_cancelled:
                    break

                pending_audio.extend(audio_part)
                if len(pending_audio) < emit_size:
                    continue

                sent_stream_audio = True
                await send_speaking_state_once()
                raw_chunk = bytes(pending_audio)
                if not stream_sample_rate_locked:
                    detected_sr = _extract_wav_sample_rate(raw_chunk)
                    if detected_sr is not None:
                        stream_sample_rate = detected_sr
                        stream_sample_rate_locked = True
                wav_chunk, pcm_carry = _to_playable_wav_chunk(
                    raw_chunk, sample_rate=stream_sample_rate, channels=1, pcm_carry=pcm_carry
                )
                pending_audio.clear()
                emit_size = 65536
                if not wav_chunk:
                    continue
                await send_text_stream_once()
                b64_audio = encode_wav_to_b64(wav_chunk)
                try:
                    await session.websocket.send_json(
                        {
                            "type": "tts.audio_chunk",
                            "seq": seq_id,
                            "is_final": is_final,
                            "data": {"chunk": b64_audio, "sample_rate": stream_sample_rate},
                        }
                    )
                    tts_audio_chunks_sent += 1
                    if first_tts_audio_at is None:
                        first_tts_audio_at = time.perf_counter()
                except Exception as e:
                    logger.warning(f"[ProcessTurn] Failed to send streaming TTS chunk: {e}")
                    return

            if pending_audio and not session.is_cancelled:
                sent_stream_audio = True
                await send_speaking_state_once()
                raw_chunk = bytes(pending_audio)
                if not stream_sample_rate_locked:
                    detected_sr = _extract_wav_sample_rate(raw_chunk)
                    if detected_sr is not None:
                        stream_sample_rate = detected_sr
                        stream_sample_rate_locked = True
                wav_chunk, pcm_carry = _to_playable_wav_chunk(
                    raw_chunk, sample_rate=stream_sample_rate, channels=1, pcm_carry=pcm_carry
                )
                if not wav_chunk:
                    return
                await send_text_stream_once()
                b64_audio = encode_wav_to_b64(wav_chunk)
                try:
                    await session.websocket.send_json(
                        {
                            "type": "tts.audio_chunk",
                            "seq": seq_id,
                            "is_final": is_final,
                            "data": {"chunk": b64_audio, "sample_rate": stream_sample_rate},
                        }
                    )
                    tts_audio_chunks_sent += 1
                    if first_tts_audio_at is None:
                        first_tts_audio_at = time.perf_counter()
                except Exception as e:
                    logger.warning(f"[ProcessTurn] Failed to send final streaming TTS chunk: {e}")
                    return

            if pcm_carry:
                logger.debug(f"[ProcessTurn] Dropping trailing odd PCM byte for seq={seq_id}")

            if sent_stream_audio or session.is_cancelled:
                return

            if getattr(tts_manager, "type", "") == "doubao_ws":
                raise RuntimeError("[TTS] Doubao stream returned no audio; fallback synthesize() is disabled")

            wav_bytes = await tts_manager.synthesize(chunk_text, "voice_id")
            if wav_bytes:
                await send_speaking_state_once()
                b64_wav = encode_wav_to_b64(wav_bytes)
                try:
                    await session.websocket.send_json(
                        {"type": "tts.audio", "seq": seq_id, "text": chunk_text, "audio": b64_wav, "is_final": is_final}
                    )
                    tts_audio_chunks_sent += 1
                    if first_tts_audio_at is None:
                        first_tts_audio_at = time.perf_counter()
                except Exception as e:
                    logger.warning(f"[ProcessTurn] Failed to send fallback TTS audio: {e}")
            else:
                logger.warning(f"[ProcessTurn] TTS failed for chunk {seq_id}")

        async def tts_worker():
            while True:
                item = await tts_queue.get()
                if item is None:
                    break
                seq_id, chunk_text, is_final = item
                if session.is_cancelled:
                    continue
                await synthesize_and_send(seq_id, chunk_text, is_final)

        worker_task = asyncio.create_task(tts_worker())
        try:
            async for partial_text in llm.generate_stream(full_prompt, model_config_name, session._cancel_event):
                logger.debug(f"[ProcessTurn] Received LLM chunk: {partial_text[:20]}...")
                if session.is_cancelled:
                    logger.info("[ProcessTurn] Session cancelled during LLM gen.")
                    break
                if first_llm_token_at is None:
                    first_llm_token_at = time.perf_counter()
                chunk_text = partial_text
                if awaiting_leading_emotion:
                    pending_leading_prefix += chunk_text
                    leading_prefix_chunks += 1
                    status, tag_emotion, resolved_text = _resolve_leading_emotion_prefix(pending_leading_prefix)

                    # Avoid waiting indefinitely on malformed prefix.
                    if status == "need_more" and (leading_prefix_chunks >= 6 or len(pending_leading_prefix) >= 80):
                        status = "no_tag"
                        resolved_text = pending_leading_prefix

                    if status == "need_more":
                        continue

                    awaiting_leading_emotion = False
                    pending_leading_prefix = ""
                    chunk_text = resolved_text
                    if status == "resolved" and tag_emotion:
                        first_response_emotion = tag_emotion
                        await send_avatar_state(tag_emotion, source="llm_tag")

                if chunk_text:
                    full_response_text += chunk_text

                if first_response_emotion is None and full_response_text:
                    # 若模型未输出显式标签，回退为文本启发式判定。
                    first_response_emotion = infer_emotion(full_response_text, default="neutral")
                    await send_avatar_state(first_response_emotion, source="heuristic")
                elif full_response_text and len(full_response_text) % 60 < len(chunk_text):
                    # 长回复过程中允许按内容更新表情。
                    inferred = infer_emotion(full_response_text, default=current_response_emotion or "neutral")
                    await send_avatar_state(inferred, source="heuristic_update")

                for seq_id, chunk_text, is_final in turn_chunker.process(chunk_text):
                    if session.is_cancelled:
                        break
                    cleaned = _sanitize_tts_text(chunk_text)
                    if not _is_meaningful_tts_text(cleaned):
                        continue
                    await tts_queue.put((seq_id, cleaned, is_final))

            for seq_id, chunk_text, is_final in turn_chunker.flush():
                if session.is_cancelled:
                    break
                cleaned = _sanitize_tts_text(chunk_text)
                if not _is_meaningful_tts_text(cleaned):
                    continue
                await tts_queue.put((seq_id, cleaned, is_final))

            if not session.is_cancelled and current_response_emotion is None:
                # 没有任何可判定输出时仍回传默认表情，避免前端悬空。
                fallback = infer_emotion(text or full_response_text, default="neutral")
                await send_avatar_state(fallback, source="fallback")
        finally:
            try:
                tts_queue.put_nowait(None)
            except asyncio.QueueFull:
                while True:
                    try:
                        tts_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                tts_queue.put_nowait(None)
            try:
                await worker_task
            except asyncio.CancelledError:
                raise

        if not session.is_cancelled:
            logger.info("[ProcessTurn] Finished, resetting to LISTENING.")

            if full_response_text:
                session.append_history("assistant", full_response_text)

            session.state.transition_to(CallState.LISTENING)
            try:
                await session.websocket.send_json({"type": "state.update", "state": "listening"})
            except Exception:
                pass

            turn_end_at = time.perf_counter()
            asr_str = "n/a" if asr_final_ms is None else f"{asr_final_ms:.1f}"
            llm_first_ms = -1.0 if first_llm_token_at is None else (first_llm_token_at - llm_start_at) * 1000.0
            tts_first_req_ms = -1.0 if first_tts_request_at is None else (first_tts_request_at - llm_start_at) * 1000.0
            tts_first_audio_ms = -1.0 if first_tts_audio_at is None else (first_tts_audio_at - llm_start_at) * 1000.0
            turn_total_ms = (turn_end_at - turn_start_at) * 1000.0
            logger.info(
                f"[Perf][{session.session_id}][turn={turn_id}] "
                f"source={turn_source} asr_final_ms={asr_str} "
                f"llm_first_token_ms={llm_first_ms:.1f} "
                f"tts_first_request_ms={tts_first_req_ms:.1f} "
                f"tts_first_audio_ms={tts_first_audio_ms:.1f} "
                f"tts_segments={tts_segment_count} tts_audio_chunks={tts_audio_chunks_sent} "
                f"prethink_hit={prethink_hit} "
                f"prethink_age_ms={f'{prethink_age_ms:.1f}' if isinstance(prethink_age_ms, (int, float)) else 'n/a'} "
                f"prethink_source_turn={prethink_source_turn_id if prethink_source_turn_id is not None else 'n/a'} "
                f"turn_total_ms={turn_total_ms:.1f}"
            )

            _spawn_prethink_task(session, llm, plugin_config or {}, source_turn_id=numeric_turn_id)

    except asyncio.CancelledError:
        logger.info("[ProcessTurn] Cancelled")
        raise
    except Exception as e:
        logger.error(f"[ProcessTurn] Exception: {e}", exc_info=True)
        try:
            await session.websocket.send_json({"type": "error", "message": str(e)})
            session.state.transition_to(CallState.LISTENING)
            await session.websocket.send_json({"type": "state.update", "state": "listening"})
        except Exception:
            pass
