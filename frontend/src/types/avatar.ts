export type Emotion = 'neutral' | 'happy' | 'sad' | 'angry' | 'shy' | 'surprised'
export type PartEmotion = Emotion | 'all'

export const EMOTIONS: Emotion[] = ['neutral', 'happy', 'sad', 'angry', 'shy', 'surprised']

export const PART_SLOTS = [
  'body_base',
  'eyes_open',
  'eyes_closed',
  'mouth_closed',
  'mouth_half',
  'mouth_open',
  'brow_neutral',
  'brow_happy',
  'brow_sad',
  'brow_angry',
  'fx_blush',
  'fx_sweat',
] as const

export type PartSlot = (typeof PART_SLOTS)[number]

export type AvatarPart = {
  part_id: string
  slot: PartSlot
  emotion: PartEmotion
  asset_id: string
  z: number
  anchor_x: number
  anchor_y: number
  offset_x: number
  offset_y: number
  scale: number
  rotate_deg: number
  opacity: number
  enabled: boolean
}

export type AvatarHitArea = {
  id: string
  label: string
  shape: 'rect'
  x: number
  y: number
  w: number
  h: number
  reaction_id: string
  enabled: boolean
}

export type AvatarReactionStep = {
  target: 'global'
  prop: 'translateX' | 'translateY' | 'rotateDeg' | 'scale'
  t: number
  v: number
}

export type AvatarReaction = {
  id: string
  label: string
  cooldown_ms: number
  timeline: AvatarReactionStep[]
}

export type AvatarMotionConfig = {
  idle_blink: { enabled: boolean; min_gap_ms: number; max_gap_ms: number; close_ms: number }
  idle_breath: { enabled: boolean; amp_px: number; period_ms: number }
  idle_sway: { enabled: boolean; deg: number; period_ms: number }
  speaking_lipsync: { enabled: boolean; sensitivity: number; smooth_ms: number }
}

export type AvatarCharacterConfigV1 = {
  version: '1.0'
  canvas: { width: number; height: number }
  fullMap: Record<Emotion, string | null>
  parts: AvatarPart[]
  hitAreas: AvatarHitArea[]
  reactions: AvatarReaction[]
  motions: AvatarMotionConfig
}

export type ResolvedAsset = {
  asset_id: string
  url: string | null
  path: string | null
  exists: boolean
}

export type ResolvedMap = Record<Emotion, ResolvedAsset | null>
export type ResolvedPart = AvatarPart & { url: string | null; path: string | null; exists: boolean }

export type AvatarResolvedData = {
  fullMap: ResolvedMap
  parts: ResolvedPart[]
}

export type AvatarCharacterSummary = {
  character_id: string
  owner_id: string
  name: string
  renderer_kind: string
  schema_version: string
  created_at: string | null
  updated_at: string | null
}

export type AvatarCharacterDetail = AvatarCharacterSummary & {
  config: AvatarCharacterConfigV1
  resolved?: AvatarResolvedData
}

export type AvatarCharactersListResponse = {
  active_character_id: string | null
  items: AvatarCharacterSummary[]
}

export type AvatarActiveResponse = {
  active_character_id: string | null
  character: AvatarCharacterDetail | null
}
