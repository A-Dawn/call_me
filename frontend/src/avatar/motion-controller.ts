import type { AvatarCharacterConfigV1, AvatarReaction } from '@/types/avatar'

export type MotionState = 'idle' | 'speaking' | 'touch_reaction'

export type MotionFrame = {
  state: MotionState
  blinkClosed: boolean
  mouthLevel: 0 | 1 | 2
  reactionId: string | null
  globalTransform: {
    translateX: number
    translateY: number
    rotateDeg: number
    scale: number
  }
}

type MotionInput = {
  nowMs: number
  config: AvatarCharacterConfigV1
  speaking: boolean
  speechEnergy: number
}

const DEFAULT_FRAME: MotionFrame = {
  state: 'idle',
  blinkClosed: false,
  mouthLevel: 0,
  reactionId: null,
  globalTransform: {
    translateX: 0,
    translateY: 0,
    rotateDeg: 0,
    scale: 1,
  },
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function normalizeEnergy(value: number): number {
  if (!Number.isFinite(value)) return 0
  if (value < 0) return 0
  if (value > 1) return 1
  return value
}

function pickReactionById(config: AvatarCharacterConfigV1, reactionId: string): AvatarReaction | null {
  for (const item of config.reactions) {
    if (item.id === reactionId) return item
  }
  return null
}

export class AvatarMotionController {
  private nextBlinkAt = 0
  private blinkUntil = 0
  private activeReaction: AvatarReaction | null = null
  private activeReactionStartAt = 0
  private reactionCooldownUntil = new Map<string, number>()
  private smoothedSpeech = 0
  private phaseOffset = Math.random() * Math.PI * 2

  private scheduleNextBlink(nowMs: number, config: AvatarCharacterConfigV1) {
    const blink = config.motions.idle_blink
    const minGap = Math.max(400, blink.min_gap_ms)
    const maxGap = Math.max(minGap, blink.max_gap_ms)
    const gap = minGap + Math.random() * (maxGap - minGap)
    this.nextBlinkAt = nowMs + gap
  }

  private evaluateReactionValue(
    reaction: AvatarReaction,
    prop: 'translateX' | 'translateY' | 'rotateDeg' | 'scale',
    elapsedMs: number,
  ): number {
    const points = reaction.timeline.filter((x) => x.target === 'global' && x.prop === prop).sort((a, b) => a.t - b.t)
    if (points.length === 0) {
      if (prop === 'scale') return 1
      return 0
    }
    if (elapsedMs <= points[0].t) return points[0].v
    const last = points[points.length - 1]
    if (elapsedMs >= last.t) return last.v
    for (let i = 0; i < points.length - 1; i++) {
      const a = points[i]
      const b = points[i + 1]
      if (elapsedMs >= a.t && elapsedMs <= b.t) {
        const span = b.t - a.t
        if (span <= 0) return b.v
        const t = (elapsedMs - a.t) / span
        return lerp(a.v, b.v, t)
      }
    }
    return prop === 'scale' ? 1 : 0
  }

  triggerReaction(config: AvatarCharacterConfigV1, reactionId: string, nowMs: number): boolean {
    const reaction = pickReactionById(config, reactionId)
    if (!reaction) return false
    const cooldownUntil = this.reactionCooldownUntil.get(reaction.id) || 0
    if (nowMs < cooldownUntil) return false
    this.activeReaction = reaction
    this.activeReactionStartAt = nowMs
    this.reactionCooldownUntil.set(reaction.id, nowMs + Math.max(0, reaction.cooldown_ms))
    return true
  }

  update(input: MotionInput): MotionFrame {
    const { nowMs, config, speaking } = input
    const frame: MotionFrame = {
      ...DEFAULT_FRAME,
      globalTransform: { ...DEFAULT_FRAME.globalTransform },
    }

    const blinkCfg = config.motions.idle_blink
    if (blinkCfg.enabled) {
      if (this.nextBlinkAt <= 0) {
        this.scheduleNextBlink(nowMs, config)
      }
      if (nowMs >= this.nextBlinkAt && this.blinkUntil <= nowMs) {
        this.blinkUntil = nowMs + Math.max(40, blinkCfg.close_ms)
        this.scheduleNextBlink(nowMs, config)
      }
      frame.blinkClosed = nowMs < this.blinkUntil
    }

    if (config.motions.idle_breath.enabled) {
      const period = Math.max(200, config.motions.idle_breath.period_ms)
      const amp = Math.max(0, config.motions.idle_breath.amp_px)
      frame.globalTransform.translateY += Math.sin((nowMs / period) * Math.PI * 2 + this.phaseOffset) * amp
    }

    if (config.motions.idle_sway.enabled) {
      const period = Math.max(200, config.motions.idle_sway.period_ms)
      const deg = Math.max(0, config.motions.idle_sway.deg)
      frame.globalTransform.rotateDeg += Math.sin((nowMs / period) * Math.PI * 2 + this.phaseOffset * 0.37) * deg
    }

    const lipsync = config.motions.speaking_lipsync
    const targetEnergy = speaking && lipsync.enabled ? normalizeEnergy(input.speechEnergy) : 0
    const smooth = Math.max(0, lipsync.smooth_ms)
    const alpha = smooth <= 0 ? 1 : Math.min(1, 16 / smooth)
    this.smoothedSpeech = this.smoothedSpeech * (1 - alpha) + targetEnergy * alpha

    const mouthEnergy = normalizeEnergy(this.smoothedSpeech * Math.max(0.1, lipsync.sensitivity))
    if (mouthEnergy >= 0.66) frame.mouthLevel = 2
    else if (mouthEnergy >= 0.33) frame.mouthLevel = 1
    else frame.mouthLevel = 0

    if (this.activeReaction) {
      const elapsed = nowMs - this.activeReactionStartAt
      const timeline = this.activeReaction.timeline
      const duration = timeline.length ? timeline.reduce((acc, x) => Math.max(acc, x.t), 0) : 0
      if (elapsed > duration) {
        this.activeReaction = null
        frame.reactionId = null
      } else {
        frame.reactionId = this.activeReaction.id
        frame.globalTransform.translateX += this.evaluateReactionValue(this.activeReaction, 'translateX', elapsed)
        frame.globalTransform.translateY += this.evaluateReactionValue(this.activeReaction, 'translateY', elapsed)
        frame.globalTransform.rotateDeg += this.evaluateReactionValue(this.activeReaction, 'rotateDeg', elapsed)
        frame.globalTransform.scale *= this.evaluateReactionValue(this.activeReaction, 'scale', elapsed)
      }
    }

    if (frame.reactionId) {
      frame.state = 'touch_reaction'
    } else if (speaking) {
      frame.state = 'speaking'
    } else {
      frame.state = 'idle'
    }
    return frame
  }

  reset() {
    this.nextBlinkAt = 0
    this.blinkUntil = 0
    this.activeReaction = null
    this.activeReactionStartAt = 0
    this.reactionCooldownUntil.clear()
    this.smoothedSpeech = 0
  }
}
