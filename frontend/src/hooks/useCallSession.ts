import { useAtom, useAtomValue } from 'jotai'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  audioPlaybackAtom,
  connectionAtom,
  httpBaseUrlAtom,
  transcriptAtom,
  wsUrlAtom,
} from '@/state/call'
import { base64ToBytes, bytesToBase64, downsampleFloat32, float32ToPcm16 } from '@/lib/audio'
import type { Emotion } from '@/types/avatar'
export type { Emotion } from '@/types/avatar'

export type MicMode = 'hands_free' | 'push_to_talk'

export type DialogueTurn = {
  id: string
  user: string
  assistant: string
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function getString(v: unknown): string | null {
  return typeof v === 'string' ? v : null
}

function getBoolean(v: unknown): boolean | null {
  return typeof v === 'boolean' ? v : null
}

function getNumber(v: unknown): number | null {
  return typeof v === 'number' ? v : null
}

function getInt(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? Math.trunc(v) : null
}

function getMessageType(msg: unknown): string | null {
  if (!isRecord(msg)) return null
  return getString(msg.type)
}

function toExactArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  return copy.buffer
}

function normalizeEmotion(value: string | null | undefined): Emotion {
  const raw = (value || '').trim().toLowerCase()
  if (raw === 'happy') return 'happy'
  if (raw === 'sad') return 'sad'
  if (raw === 'angry') return 'angry'
  if (raw === 'shy') return 'shy'
  if (raw === 'surprised') return 'surprised'
  return 'neutral'
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  const tag = target.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  if (target.hasAttribute('contenteditable')) return true
  if (target.closest('[contenteditable="true"]')) return true
  return false
}

export function useCallSessionController() {
  const [conn, setConn] = useAtom(connectionAtom)
  const [transcript, setTranscript] = useAtom(transcriptAtom)
  const [, setPlayback] = useAtom(audioPlaybackAtom)
  const [health, setHealth] = useState<string | null>(null)
  const [micMode, setMicMode] = useState<MicMode>('push_to_talk')
  const [activeEmotion, setActiveEmotion] = useState<Emotion>('neutral')
  const [speechEnergy, setSpeechEnergy] = useState(0)
  const [dialogueTurns, setDialogueTurns] = useState<DialogueTurn[]>([])
  const [callDurationSec, setCallDurationSec] = useState(0)
  const httpBaseUrl = useAtomValue(httpBaseUrlAtom)
  const wsUrl = useAtomValue(wsUrlAtom)

  const wsRef = useRef<WebSocket | null>(null)
  const micStreamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const procRef = useRef<ScriptProcessorNode | null>(null)
  const floatBufRef = useRef<Float32Array>(new Float32Array(0))
  const pttKeyDownRef = useRef(false)
  const turnSeqRef = useRef(0)
  const activeTurnIdRef = useRef<string | null>(null)
  const playbackCtxRef = useRef<AudioContext | null>(null)
  const playbackChainRef = useRef<Promise<void>>(Promise.resolve())
  const playbackNextStartRef = useRef(0)
  const playbackSourcesRef = useRef<Set<AudioBufferSourceNode>>(new Set())
  const playbackGenerationRef = useRef(0)
  const playbackStartedRef = useRef(false)
  const playbackOutputNodeRef = useRef<AudioNode | null>(null)
  const playbackAnalyserRef = useRef<AnalyserNode | null>(null)
  const playbackAnalyserDataRef = useRef<Uint8Array<ArrayBuffer> | null>(null)
  const speechEnergyRef = useRef(0)
  const playbackStartupBuffersRef = useRef<AudioBuffer[]>([])
  const playbackStartupDurationRef = useRef(0)
  const playbackStartupTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const playbackStartupBufferMsRef = useRef(120)
  const playbackStartupMaxWaitMsRef = useRef(120)
  const playbackScheduleLeadMsRef = useRef(30)
  const pendingTtsTextBySeqRef = useRef<Map<number, string>>(new Map())
  const flushedTtsSeqRef = useRef<Set<number>>(new Set())
  const pendingTtsTextQueueRef = useRef<string[]>([])

  const appendLog = useCallback((line: string) => {
    setTranscript((prev) => ({
      ...prev,
      log: [...prev.log, `${new Date().toLocaleTimeString()}  ${line}`].slice(-400),
    }))
  }, [setTranscript])

  const createTurnId = useCallback(() => {
    turnSeqRef.current += 1
    return `turn-${Date.now()}-${turnSeqRef.current}`
  }, [])

  const pushUserTurn = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    const id = createTurnId()
    activeTurnIdRef.current = id
    setDialogueTurns((prev) => [...prev, { id, user: trimmed, assistant: '' }].slice(-6))
  }, [createTurnId])

  const appendAssistantTurn = useCallback((text: string) => {
    const chunk = text.trim()
    if (!chunk) return

    setDialogueTurns((prev) => {
      const next = [...prev]
      const turnId = activeTurnIdRef.current
      const idx = turnId ? next.findIndex((it) => it.id === turnId) : -1

      if (idx >= 0) {
        const item = next[idx]
        next[idx] = { ...item, assistant: `${item.assistant}${chunk}`.trimStart() }
      } else {
        const id = createTurnId()
        activeTurnIdRef.current = id
        next.push({ id, user: '', assistant: chunk })
      }
      return next.slice(-6)
    })
  }, [createTurnId])

  const appendAssistantText = useCallback((text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    appendAssistantTurn(trimmed)
    setTranscript((x) => ({ ...x, assistantText: (x.assistantText + trimmed).slice(-8000) }))
  }, [appendAssistantTurn, setTranscript])

  const clearPendingTtsText = useCallback(() => {
    pendingTtsTextBySeqRef.current.clear()
    flushedTtsSeqRef.current.clear()
    pendingTtsTextQueueRef.current = []
  }, [])

  const flushPendingTtsTextForSeq = useCallback((seq: number | null) => {
    let text = ''
    if (seq !== null) {
      if (!flushedTtsSeqRef.current.has(seq)) {
        text = pendingTtsTextBySeqRef.current.get(seq) || ''
        if (text) {
          pendingTtsTextBySeqRef.current.delete(seq)
          flushedTtsSeqRef.current.add(seq)
        }
      }
    }
    if (!text && pendingTtsTextQueueRef.current.length > 0) {
      text = pendingTtsTextQueueRef.current.shift() || ''
    }
    if (text) appendAssistantText(text)
  }, [appendAssistantText])

  const dequeuePlaybackMarker = useCallback(() => {
    setPlayback((p) => {
      if (p.queue.length === 0) return p
      return { ...p, queue: p.queue.slice(1), audioEl: null }
    })
  }, [setPlayback])

  const clearPlaybackStartupTimer = useCallback(() => {
    if (playbackStartupTimerRef.current !== null) {
      clearTimeout(playbackStartupTimerRef.current)
      playbackStartupTimerRef.current = null
    }
  }, [])

  const scheduleDecodedBuffer = useCallback((ctx: AudioContext, decoded: AudioBuffer) => {
    const leadSeconds = Math.max(0, playbackScheduleLeadMsRef.current) / 1000
    const now = ctx.currentTime
    if (playbackNextStartRef.current < now + leadSeconds) {
      playbackNextStartRef.current = now + leadSeconds
    }
    const startAt = playbackNextStartRef.current
    playbackNextStartRef.current += decoded.duration

    const source = ctx.createBufferSource()
    source.buffer = decoded
    source.connect(playbackOutputNodeRef.current ?? ctx.destination)
    playbackSourcesRef.current.add(source)
    source.onended = () => {
      playbackSourcesRef.current.delete(source)
      dequeuePlaybackMarker()
    }
    source.start(startAt)
  }, [dequeuePlaybackMarker])

  const flushStartupBuffers = useCallback((force: boolean) => {
    const startupBufferSeconds = Math.max(0, playbackStartupBufferMsRef.current) / 1000
    const ctx = playbackCtxRef.current
    if (!ctx || ctx.state === 'closed') return
    if (playbackStartupBuffersRef.current.length === 0) return
    if (!force && playbackStartupDurationRef.current < startupBufferSeconds) return

    clearPlaybackStartupTimer()
    const pending = playbackStartupBuffersRef.current
    playbackStartupBuffersRef.current = []
    playbackStartupDurationRef.current = 0
    playbackStartedRef.current = true

    for (const decoded of pending) {
      scheduleDecodedBuffer(ctx, decoded)
    }
  }, [clearPlaybackStartupTimer, scheduleDecodedBuffer])

  const stopPlayback = useCallback(() => {
    playbackGenerationRef.current += 1
    playbackNextStartRef.current = 0
    playbackChainRef.current = Promise.resolve()
    playbackStartedRef.current = false
    playbackStartupBuffersRef.current = []
    playbackStartupDurationRef.current = 0
    clearPlaybackStartupTimer()

    for (const source of playbackSourcesRef.current) {
      try {
        source.stop()
      } catch {
        // ignore
      }
      try {
        source.disconnect()
      } catch {
        // ignore
      }
    }
    playbackSourcesRef.current.clear()

    const ctx = playbackCtxRef.current
    playbackCtxRef.current = null
    playbackOutputNodeRef.current = null
    playbackAnalyserRef.current = null
    playbackAnalyserDataRef.current = null
    speechEnergyRef.current = 0
    setSpeechEnergy(0)
    if (ctx) {
      void ctx.close().catch(() => {})
    }

    clearPendingTtsText()
    setPlayback((p) => ({ ...p, queue: [], audioEl: null }))
  }, [clearPendingTtsText, clearPlaybackStartupTimer, setPlayback])

  const enqueueAndPlay = useCallback((wavBytes: Uint8Array) => {
    const generation = playbackGenerationRef.current
    const marker = `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const wavBuffer = toExactArrayBuffer(wavBytes)

    setPlayback((p) => ({ ...p, queue: [...p.queue, marker], audioEl: null }))

    playbackChainRef.current = playbackChainRef.current
      .then(async () => {
        if (generation !== playbackGenerationRef.current) {
          dequeuePlaybackMarker()
          return
        }

        let ctx = playbackCtxRef.current
        if (!ctx || ctx.state === 'closed') {
          ctx = new AudioContext()
          playbackCtxRef.current = ctx
          const outputGain = ctx.createGain()
          const analyser = ctx.createAnalyser()
          analyser.fftSize = 1024
          outputGain.connect(analyser)
          analyser.connect(ctx.destination)
          playbackOutputNodeRef.current = outputGain
          playbackAnalyserRef.current = analyser
          playbackAnalyserDataRef.current = new Uint8Array(new ArrayBuffer(analyser.fftSize))
          speechEnergyRef.current = 0
          setSpeechEnergy(0)
          playbackNextStartRef.current = 0
          playbackStartedRef.current = false
          playbackStartupBuffersRef.current = []
          playbackStartupDurationRef.current = 0
          clearPlaybackStartupTimer()
        }
        if (ctx.state === 'suspended') {
          try {
            await ctx.resume()
          } catch {
            // ignore
          }
        }

        let decoded: AudioBuffer
        try {
          decoded = await ctx.decodeAudioData(wavBuffer.slice(0))
        } catch {
          dequeuePlaybackMarker()
          return
        }
        if (generation !== playbackGenerationRef.current) {
          dequeuePlaybackMarker()
          return
        }

        if (!playbackStartedRef.current) {
          playbackStartupBuffersRef.current.push(decoded)
          playbackStartupDurationRef.current += decoded.duration

          if (playbackStartupTimerRef.current === null) {
            const startupMaxWaitMs = Math.max(0, playbackStartupMaxWaitMsRef.current)
            playbackStartupTimerRef.current = setTimeout(() => {
              playbackStartupTimerRef.current = null
              playbackChainRef.current = playbackChainRef.current.then(() => {
                if (generation !== playbackGenerationRef.current) return
                flushStartupBuffers(true)
              })
            }, startupMaxWaitMs)
          }

          flushStartupBuffers(false)
          return
        }

        scheduleDecodedBuffer(ctx, decoded)
      })
      .catch(() => {
        dequeuePlaybackMarker()
      })
  }, [clearPlaybackStartupTimer, dequeuePlaybackMarker, flushStartupBuffers, scheduleDecodedBuffer, setPlayback])

  const stopMic = useCallback(() => {
    if (procRef.current) {
      try {
        procRef.current.disconnect()
      } catch {
        // ignore
      }
      procRef.current = null
    }

    if (audioCtxRef.current) {
      void audioCtxRef.current.close().catch(() => {})
      audioCtxRef.current = null
    }

    if (micStreamRef.current) {
      for (const track of micStreamRef.current.getTracks()) track.stop()
      micStreamRef.current = null
    }
    floatBufRef.current = new Float32Array(0)
    setConn((c) => ({ ...c, mic: 'off' }))
  }, [setConn])

  const connect = useCallback(() => {
    if (wsRef.current) return
    setConn((c) => ({ ...c, status: 'connecting' }))

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setConn((c) => ({ ...c, status: 'connected' }))
      appendLog(`WS open: ${wsUrl}`)
      ws.send(JSON.stringify({ type: 'client.hello' }))
    }

    ws.onmessage = (evt) => {
      let msg: unknown
      try {
        msg = JSON.parse(String(evt.data)) as unknown
      } catch {
        appendLog('WS message (non-JSON) ignored')
        return
      }

      const type = getMessageType(msg)
      if (!type) {
        appendLog('WS message: unknown')
        return
      }

      if (type === 'server.hello') {
        const sessionId = isRecord(msg) ? getString(msg.session_id) : null
        if (sessionId) {
          setConn((c) => ({ ...c, sessionId }))
          appendLog(`server.hello session_id=${sessionId}`)
        } else {
          appendLog('server.hello missing session_id')
        }
        return
      }

      if (type === 'client.config') {
        if (isRecord(msg) && isRecord(msg.data) && isRecord(msg.data.playback)) {
          const playback = msg.data.playback
          const startupBufferMs = getInt(playback.startup_buffer_ms)
          const startupMaxWaitMs = getInt(playback.startup_max_wait_ms)
          const scheduleLeadMs = getInt(playback.schedule_lead_ms)

          if (startupBufferMs !== null) {
            playbackStartupBufferMsRef.current = Math.max(0, Math.min(1000, startupBufferMs))
          }
          if (startupMaxWaitMs !== null) {
            playbackStartupMaxWaitMsRef.current = Math.max(0, Math.min(1000, startupMaxWaitMs))
          }
          if (scheduleLeadMs !== null) {
            playbackScheduleLeadMsRef.current = Math.max(0, Math.min(300, scheduleLeadMs))
          }

          appendLog(
            `playback config: buffer=${playbackStartupBufferMsRef.current}ms wait=${playbackStartupMaxWaitMsRef.current}ms lead=${playbackScheduleLeadMsRef.current}ms`,
          )
        }
        return
      }

      if (type === 'state.update') {
        const state = isRecord(msg) ? getString(msg.state) : null
        if (state) {
          setConn((c) => ({ ...c, callState: state }))
          if (state === 'thinking') clearPendingTtsText()
          if (state === 'interrupted') stopPlayback()
          if (state === 'listening') activeTurnIdRef.current = null
        } else {
          appendLog('state.update missing state')
        }
        return
      }

      if (type === 'avatar.state') {
        const emotion = isRecord(msg) ? normalizeEmotion(getString(msg.emotion)) : 'neutral'
        const source = isRecord(msg) ? getString(msg.source) : null
        setActiveEmotion(emotion)
        appendLog(`avatar.state ${emotion}${source ? ` (${source})` : ''}`)
        return
      }

      if (type === 'input.text_update') {
        const text = isRecord(msg) ? getString(msg.text) : null
        const isFinal = isRecord(msg) ? getBoolean(msg.is_final) : null
        if (text !== null && isFinal !== null) {
          setTranscript((t) => ({
            ...t,
            asrText: text,
            asrIsFinal: isFinal,
          }))
          if (isFinal) pushUserTurn(text)
        } else {
          appendLog('input.text_update missing fields')
        }
        return
      }

      if (type === 'tts.audio') {
        const t = isRecord(msg) ? getString(msg.text) : null
        if (t) appendAssistantText(t)
        const audio = isRecord(msg) ? getString(msg.audio) : null
        if (audio) enqueueAndPlay(base64ToBytes(audio))
        return
      }

      if (type === 'tts.audio_chunk') {
        if (isRecord(msg) && isRecord(msg.data)) {
          const chunk = getString(msg.data.chunk)
          const seq = getInt(msg.seq)
          const sampleRate = getNumber(msg.data.sample_rate)
          void sampleRate
          if (chunk) {
            flushPendingTtsTextForSeq(seq)
            enqueueAndPlay(base64ToBytes(chunk))
          }
        }
        return
      }

      if (type === 'tts.text_stream') {
        if (isRecord(msg) && isRecord(msg.data)) {
          const t = getString(msg.data.text)
          if (t) {
            let seq = getInt(msg.seq)
            if (seq === null) {
              seq = getInt(msg.data.seq)
            }
            if (seq !== null) {
              const prev = pendingTtsTextBySeqRef.current.get(seq) || ''
              pendingTtsTextBySeqRef.current.set(seq, `${prev}${t}`.trim())
            } else {
              pendingTtsTextQueueRef.current.push(t)
            }
          }
        }
        return
      }

      if (type === 'error') {
        const message = isRecord(msg) ? getString(msg.message) : null
        appendLog(`error: ${message ?? 'unknown'}`)
        return
      }
    }

    ws.onclose = () => {
      appendLog('WS closed')
      wsRef.current = null
      setConn((c) => ({ ...c, status: 'disconnected', sessionId: null, callState: null }))
      setActiveEmotion('neutral')
      stopMic()
      stopPlayback()
    }

    ws.onerror = () => {
      appendLog('WS error')
    }
  }, [
    appendAssistantText,
    appendLog,
    clearPendingTtsText,
    enqueueAndPlay,
    flushPendingTtsTextForSeq,
    pushUserTurn,
    setConn,
    setTranscript,
    stopMic,
    stopPlayback,
    wsUrl,
  ])

  const disconnect = useCallback(() => {
    const ws = wsRef.current
    wsRef.current = null
    if (ws) ws.close()
    setConn((c) => ({ ...c, status: 'disconnected', sessionId: null, callState: null }))
    setActiveEmotion('neutral')
    stopMic()
    stopPlayback()
  }, [setConn, stopMic, stopPlayback])

  const startMic = useCallback(async () => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    if (conn.mic === 'on') return

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      appendLog(`mic error: ${String(e)}`)
      return
    }

    micStreamRef.current = stream
    const ctx = new AudioContext({ sampleRate: 48000 })
    audioCtxRef.current = ctx
    const source = ctx.createMediaStreamSource(stream)

    const proc = ctx.createScriptProcessor(4096, 1, 1)
    procRef.current = proc

    const targetRate = 16000
    const chunkSamples = Math.round(targetRate * 0.02)

    proc.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0)
      const down = downsampleFloat32(input, ctx.sampleRate, targetRate)

      const prev = floatBufRef.current
      const merged = new Float32Array(prev.length + down.length)
      merged.set(prev)
      merged.set(down, prev.length)

      let offset = 0
      while (merged.length - offset >= chunkSamples) {
        const slice = merged.subarray(offset, offset + chunkSamples)
        const pcm16 = float32ToPcm16(slice)
        const b64 = bytesToBase64(new Uint8Array(pcm16.buffer))
        ws.send(JSON.stringify({ type: 'input.audio_chunk', data: { chunk: b64 } }))
        offset += chunkSamples
      }

      floatBufRef.current = merged.subarray(offset)
    }

    source.connect(proc)
    proc.connect(ctx.destination)

    setConn((c) => ({ ...c, mic: 'on' }))
    appendLog('mic on (sending 16kHz PCM16 @ 20ms)')
  }, [appendLog, conn.mic, setConn])

  const sendText = useCallback((rawText: string) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return false
    const trimmed = rawText.trim()
    if (!trimmed) return false

    pushUserTurn(trimmed)
    setTranscript((t) => ({ ...t, assistantText: '', asrText: '', asrIsFinal: false }))
    stopPlayback()
    ws.send(JSON.stringify({ type: 'input.text', data: { text: trimmed } }))
    appendLog(`input.text ${trimmed.slice(0, 40)}`)
    return true
  }, [appendLog, pushUserTurn, setTranscript, stopPlayback])

  const interrupt = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'control.interrupt' }))
    appendLog('control.interrupt')
    stopPlayback()
  }, [appendLog, stopPlayback])

  const pingHealth = useCallback(async () => {
    try {
      const res = await fetch('/health')
      const json = (await res.json()) as unknown
      setHealth(JSON.stringify(json, null, 2))
    } catch (e) {
      setHealth(String(e))
    }
  }, [])

  const clearEventLog = useCallback(() => {
    setTranscript((t) => ({ ...t, log: [] }))
  }, [setTranscript])

  useEffect(() => {
    let rafId = 0
    const tick = () => {
      const analyser = playbackAnalyserRef.current
      const data = playbackAnalyserDataRef.current
      if (analyser && data) {
        analyser.getByteTimeDomainData(data)
        let sum = 0
        for (let i = 0; i < data.length; i++) {
          const x = (data[i] - 128) / 128
          sum += x * x
        }
        const rms = Math.sqrt(sum / data.length)
        const normalized = Math.max(0, Math.min(1, (rms - 0.01) / 0.18))
        const smoothed = speechEnergyRef.current * 0.8 + normalized * 0.2
        speechEnergyRef.current = smoothed
      } else {
        speechEnergyRef.current = speechEnergyRef.current * 0.86
        if (speechEnergyRef.current < 0.001) speechEnergyRef.current = 0
      }
      setSpeechEnergy((prev) => {
        if (Math.abs(prev - speechEnergyRef.current) < 0.01) return prev
        return speechEnergyRef.current
      })
      rafId = window.requestAnimationFrame(tick)
    }
    rafId = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(rafId)
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (micMode !== 'push_to_talk') return
      if (event.code !== 'Space') return
      if (conn.status !== 'connected') return
      if (isEditableTarget(event.target)) return
      event.preventDefault()
      if (pttKeyDownRef.current) return
      pttKeyDownRef.current = true
      void startMic()
    }

    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code !== 'Space') return
      if (!pttKeyDownRef.current) return
      event.preventDefault()
      pttKeyDownRef.current = false
      stopMic()
    }

    const onWindowBlur = () => {
      pttKeyDownRef.current = false
      stopMic()
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onWindowBlur)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onWindowBlur)
    }
  }, [conn.status, micMode, startMic, stopMic])

  useEffect(() => () => disconnect(), [disconnect])

  useEffect(() => {
    if (conn.status !== 'connected') {
      setCallDurationSec(0)
      return
    }
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      setCallDurationSec(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)))
    }, 1000)
    return () => window.clearInterval(timer)
  }, [conn.sessionId, conn.status])

  return {
    conn,
    transcript,
    health,
    micMode,
    activeEmotion,
    speechEnergy,
    dialogueTurns,
    callDurationSec,
    httpBaseUrl,
    wsUrl,
    setMicMode,
    connect,
    disconnect,
    startMic,
    stopMic,
    sendText,
    interrupt,
    pingHealth,
    clearEventLog,
  }
}
