export type AsrSourceItem = {
  source_id: string
  repo: string
  enabled: boolean
  channels: string[]
  file_patterns: string[]
  sha256_map: Record<string, string>
  license_spdx: string
  license_url: string
  extract_layout: string
  source_type: 'builtin' | 'custom' | string
}

export type AsrModelCandidate = {
  candidate_id: string
  source_id: string
  repo: string
  channel: string
  release_tag: string
  artifact_name: string
  artifact_key: string
  download_url: string
  size_bytes: number
  sha256: string
  license_spdx: string
  license_url: string
  downloadable: boolean
  blocked_reason: string
}

export type AsrInstalledModel = {
  install_id: string
  source_id: string
  artifact_key: string
  artifact_name: string
  channel: string
  download_url: string
  sha256: string
  install_dir: string
  manifest: Record<string, unknown>
  created_at: string | null
}
