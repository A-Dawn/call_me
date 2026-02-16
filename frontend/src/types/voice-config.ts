export type ProviderType = 'doubao_ws' | 'sovits' | 'cosyvoice_http' | 'mock'

export type ConfigIssue = {
  code: string
  field: string
  message: string
}

export type ValidationResult = {
  ok: boolean
  errors: ConfigIssue[]
  warnings: ConfigIssue[]
  fix_hints: ConfigIssue[]
  normalized?: Record<string, unknown>
}

export type ConnectivityResult = {
  ok: boolean
  checks: {
    tts: { ok: boolean; message: string; type?: string }
    asr: { ok: boolean; message: string; type?: string }
  }
}

export type ApplyResult = {
  saved: boolean
  restarted: boolean
  health_ok: boolean
  rollback_used: boolean
  status: string
  config_path?: string
  backup_path?: string | null
}

export type VoiceSchema = {
  sections: Record<string, unknown>
  wizard: {
    tts_provider_options: Array<{ value: ProviderType; label: string }>
    tts_templates: Record<string, Array<{ id: string; label: string; defaults: Record<string, unknown> }>>
    steps: string[]
  }
}
