import { atom } from 'jotai'

type ConnectionStatus = 'disconnected' | 'connecting' | 'connected'
type MicStatus = 'off' | 'on'

export type ConnectionState = {
  status: ConnectionStatus
  sessionId: string | null
  callState: string | null
  mic: MicStatus
}

export const connectionAtom = atom<ConnectionState>({
  status: 'disconnected',
  sessionId: null,
  callState: null,
  mic: 'off',
})

export type TranscriptState = {
  asrText: string
  asrIsFinal: boolean
  assistantText: string
  log: string[]
}

export const transcriptAtom = atom<TranscriptState>({
  asrText: '',
  asrIsFinal: false,
  assistantText: '',
  log: [],
})

export type AudioPlaybackState = {
  queue: string[]
  audioEl: HTMLAudioElement | null
}

export const audioPlaybackAtom = atom<AudioPlaybackState>({
  queue: [],
  audioEl: null,
})

function getDefaultHttpBaseUrl(): string {
  const raw = import.meta.env.VITE_CALL_ME_BASE_URL as string | undefined
  const configured = raw?.trim()
  if (configured) return configured
  if (typeof window !== 'undefined' && window.location.origin) return window.location.origin
  return 'http://127.0.0.1:8989'
}

export const httpBaseUrlAtom = atom<string>(() => getDefaultHttpBaseUrl())

export const wsUrlAtom = atom<string>((get) => {
  const httpBase = get(httpBaseUrlAtom)
  const url = new URL(httpBase)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = '/ws/call'
  url.search = ''
  url.hash = ''
  return url.toString()
})
