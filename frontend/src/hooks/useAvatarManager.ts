import { useAtomValue } from 'jotai'
import { useCallback, useState } from 'react'
import { httpBaseUrlAtom } from '@/state/call'
import {
  EMOTIONS,
  type AvatarActiveResponse,
  type AvatarCharacterConfigV1,
  type AvatarCharacterDetail,
  type AvatarCharacterSummary,
  type AvatarCharactersListResponse,
  type Emotion,
} from '@/types/avatar'

type AssetItem = {
  asset_id?: string
  path?: string
  url?: string
  emotion?: string
  tags_json?: string
}

type AvatarMapEntry = {
  asset_id?: string
  url?: string | null
  path?: string
}

type BoundAvatar = { assetId: string; url: string }
type UploadAssetOptions = { kind?: string; tags?: unknown; ownerId?: string }

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function getString(v: unknown): string | null {
  return typeof v === 'string' ? v : null
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

function parseEmotionFromTags(tagsJson: string | undefined): Emotion | null {
  if (!tagsJson) return null
  try {
    const data = JSON.parse(tagsJson) as unknown
    if (Array.isArray(data)) {
      for (const item of data) {
        if (typeof item === 'string') {
          const x = item.toLowerCase()
          if (x.startsWith('emotion:')) return normalizeEmotion(x.split(':', 2)[1])
          if (x.startsWith('emo:')) return normalizeEmotion(x.split(':', 2)[1])
        }
        if (isRecord(item)) {
          const e = getString(item.emotion)
          if (e) return normalizeEmotion(e)
        }
      }
    }
    if (isRecord(data)) {
      const e = getString(data.emotion)
      if (e) return normalizeEmotion(e)
    }
  } catch {
    return null
  }
  return null
}

function makeEmptyAvatarMap(): Record<Emotion, string> {
  return {
    neutral: '',
    happy: '',
    sad: '',
    angry: '',
    shy: '',
    surprised: '',
  }
}

function makeEmptyAvatarEntries(): Record<Emotion, BoundAvatar | null> {
  return {
    neutral: null,
    happy: null,
    sad: null,
    angry: null,
    shy: null,
    surprised: null,
  }
}

function resolveUrl(base: string, urlOrPath: string): string {
  if (urlOrPath.startsWith('http://') || urlOrPath.startsWith('https://')) return urlOrPath
  if (urlOrPath.startsWith('/')) return new URL(urlOrPath, base).toString()
  return new URL(`/${urlOrPath}`, base).toString()
}

function normalizeCharacterSummary(v: unknown): AvatarCharacterSummary | null {
  if (!isRecord(v)) return null
  const characterId = getString(v.character_id)
  const name = getString(v.name)
  const rendererKind = getString(v.renderer_kind)
  const schemaVersion = getString(v.schema_version)
  if (!characterId || !name || !rendererKind || !schemaVersion) return null
  return {
    character_id: characterId,
    owner_id: getString(v.owner_id) || '',
    name,
    renderer_kind: rendererKind,
    schema_version: schemaVersion,
    created_at: getString(v.created_at),
    updated_at: getString(v.updated_at),
  }
}

function normalizeCharacterDetail(v: unknown): AvatarCharacterDetail | null {
  if (!isRecord(v)) return null
  const summary = normalizeCharacterSummary(v)
  if (!summary) return null
  if (!isRecord(v.config)) return null
  const cfg = v.config as AvatarCharacterConfigV1
  const resolved = isRecord(v.resolved) ? (v.resolved as AvatarCharacterDetail['resolved']) : undefined
  return { ...summary, config: cfg, resolved }
}

export function useAvatarManager() {
  const httpBaseUrl = useAtomValue(httpBaseUrlAtom)
  const [avatarMap, setAvatarMap] = useState<Record<Emotion, string>>(makeEmptyAvatarMap)
  const [avatarEntries, setAvatarEntries] = useState<Record<Emotion, BoundAvatar | null>>(makeEmptyAvatarEntries)
  const [characters, setCharacters] = useState<AvatarCharacterSummary[]>([])
  const [activeCharacterId, setActiveCharacterId] = useState<string | null>(null)
  const [activeCharacter, setActiveCharacterState] = useState<AvatarCharacterDetail | null>(null)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const [avatarErr, setAvatarErr] = useState<string | null>(null)

  const applyCharacterResolvedToMap = useCallback(
    (character: AvatarCharacterDetail | null) => {
      if (!character?.resolved?.fullMap) return
      const next = makeEmptyAvatarMap()
      const nextEntries = makeEmptyAvatarEntries()
      for (const emo of EMOTIONS) {
        const entry = character.resolved.fullMap[emo]
        if (!entry?.url) continue
        const resolved = resolveUrl(httpBaseUrl, entry.url)
        next[emo] = resolved
        if (entry.asset_id) nextEntries[emo] = { assetId: entry.asset_id, url: resolved }
      }
      setAvatarMap(next)
      setAvatarEntries(nextEntries)
    },
    [httpBaseUrl],
  )

  const loadAvatarMap = useCallback(async () => {
    setAvatarErr(null)
    try {
      const next = makeEmptyAvatarMap()
      const nextEntries = makeEmptyAvatarEntries()

      let loadedFromPersistent = false
      const mapRes = await fetch('/api/avatar-map/active')
      if (mapRes.ok) {
        const mapJson = (await mapRes.json()) as unknown
        if (isRecord(mapJson) && isRecord(mapJson.mapping)) {
          for (const emo of EMOTIONS) {
            const entryRaw = mapJson.mapping[emo]
            if (!isRecord(entryRaw)) continue
            const entry = entryRaw as AvatarMapEntry
            const assetId = getString(entry.asset_id)
            const u = typeof entry.url === 'string' ? entry.url : null
            const p = getString(entry.path)
            if (u) {
              const resolved = resolveUrl(httpBaseUrl, u)
              next[emo] = resolved
              if (assetId) nextEntries[emo] = { assetId, url: resolved }
              loadedFromPersistent = true
            } else if (p) {
              const resolved = resolveUrl(httpBaseUrl, p)
              next[emo] = resolved
              if (assetId) nextEntries[emo] = { assetId, url: resolved }
              loadedFromPersistent = true
            }
          }
        }
      }

      if (!loadedFromPersistent) {
        const res = await fetch('/api/assets/?kind=avatar&page=1&page_size=300')
        const json = (await res.json()) as unknown
        if (Array.isArray(json)) {
          for (const row of json) {
            if (!isRecord(row)) continue
            const item = row as AssetItem
            const emo = normalizeEmotion(item.emotion || parseEmotionFromTags(item.tags_json))
            const url = getString(item.url)
            const path = getString(item.path)
            let resolved = ''
            if (url) {
              resolved = resolveUrl(httpBaseUrl, url)
            } else if (path) {
              resolved = resolveUrl(httpBaseUrl, path)
            }
            if (!resolved) continue
            if (!next[emo]) {
              next[emo] = resolved
              const assetId = getString(item.asset_id)
              if (assetId) nextEntries[emo] = { assetId, url: resolved }
            }
          }
        }
      }

      setAvatarMap(next)
      setAvatarEntries(nextEntries)
    } catch (e) {
      setAvatarErr(String(e))
    }
  }, [httpBaseUrl])

  const loadCharacterList = useCallback(async () => {
    const res = await fetch('/api/avatar-characters/')
    if (!res.ok) {
      throw new Error(`load characters failed: ${res.status}`)
    }
    const json = (await res.json()) as AvatarCharactersListResponse
    setActiveCharacterId(json.active_character_id || null)
    const list = Array.isArray(json.items) ? json.items.map(normalizeCharacterSummary).filter(Boolean) : []
    setCharacters(list as AvatarCharacterSummary[])
    return json
  }, [])

  const loadActiveCharacter = useCallback(async () => {
    const res = await fetch('/api/avatar-characters/active')
    if (!res.ok) {
      throw new Error(`load active character failed: ${res.status}`)
    }
    const json = (await res.json()) as AvatarActiveResponse
    setActiveCharacterId(json.active_character_id || null)
    const detail = normalizeCharacterDetail(json.character)
    setActiveCharacterState(detail)
    applyCharacterResolvedToMap(detail)
    return json
  }, [applyCharacterResolvedToMap])

  const loadCharacter = useCallback(async (characterId: string) => {
    const res = await fetch(`/api/avatar-characters/${characterId}`)
    if (!res.ok) throw new Error(`load character failed: ${res.status}`)
    const json = (await res.json()) as unknown
    return normalizeCharacterDetail(json)
  }, [])

  const loadAvatarSystem = useCallback(async () => {
    setAvatarErr(null)
    try {
      await loadCharacterList()
      await loadActiveCharacter()
      await loadAvatarMap()
    } catch (e) {
      setAvatarErr(String(e))
    }
  }, [loadAvatarMap, loadCharacterList, loadActiveCharacter])

  const uploadAsset = useCallback(
    async (file: File, options: UploadAssetOptions = {}) => {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('kind', options.kind || 'avatar')
      fd.append('tags', JSON.stringify(options.tags ?? []))
      if (options.ownerId) fd.append('owner_id', options.ownerId)
      const res = await fetch('/api/assets/upload', {
        method: 'POST',
        body: fd,
      })
      if (!res.ok) throw new Error(`upload failed: ${res.status}`)
      const uploaded = (await res.json()) as unknown
      const uploadedId = isRecord(uploaded) ? getString(uploaded.asset_id) : null
      if (!uploadedId) throw new Error('upload returned empty asset_id')
      return {
        asset_id: uploadedId,
        url: isRecord(uploaded) ? getString(uploaded.url) : null,
      }
    },
    [],
  )

  const bindEmotion = useCallback(
    async (emotion: Emotion, assetId: string) => {
      const bindRes = await fetch('/api/avatar-map/bind', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ emotion, asset_id: assetId }),
      })
      if (!bindRes.ok) throw new Error(`bind failed: ${bindRes.status}`)
    },
    [],
  )

  const uploadAvatar = useCallback(
    async (emotion: Emotion, file: File) => {
      setAvatarBusy(true)
      setAvatarErr(null)
      try {
        const uploaded = await uploadAsset(file, { kind: 'avatar', tags: [`emotion:${emotion}`] })
        await bindEmotion(emotion, uploaded.asset_id)
        await Promise.all([loadAvatarMap(), loadActiveCharacter()])
        return true
      } catch (e) {
        setAvatarErr(String(e))
        return false
      } finally {
        setAvatarBusy(false)
      }
    },
    [bindEmotion, loadActiveCharacter, loadAvatarMap, uploadAsset],
  )

  const deleteAvatar = useCallback(
    async (emotion: Emotion) => {
      setAvatarBusy(true)
      setAvatarErr(null)
      try {
        const entry = avatarEntries[emotion]
        const unbindRes = await fetch(`/api/avatar-map/bind/${emotion}`, { method: 'DELETE' })
        if (!unbindRes.ok) throw new Error(`unbind failed: ${unbindRes.status}`)
        if (entry?.assetId) {
          await fetch(`/api/assets/${entry.assetId}`, { method: 'DELETE' })
        }
        await Promise.all([loadAvatarMap(), loadActiveCharacter()])
        return true
      } catch (e) {
        setAvatarErr(String(e))
        return false
      } finally {
        setAvatarBusy(false)
      }
    },
    [avatarEntries, loadActiveCharacter, loadAvatarMap],
  )

  const createCharacter = useCallback(
    async (name: string, seedFromLegacy = true) => {
      setAvatarBusy(true)
      setAvatarErr(null)
      try {
        const res = await fetch('/api/avatar-characters/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, seed_from_legacy: seedFromLegacy }),
        })
        if (!res.ok) throw new Error(`create character failed: ${res.status}`)
        await Promise.all([loadCharacterList(), loadActiveCharacter()])
        return true
      } catch (e) {
        setAvatarErr(String(e))
        return false
      } finally {
        setAvatarBusy(false)
      }
    },
    [loadActiveCharacter, loadCharacterList],
  )

  const setActiveCharacter = useCallback(
    async (characterId: string) => {
      setAvatarBusy(true)
      setAvatarErr(null)
      try {
        const res = await fetch('/api/avatar-characters/active', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ character_id: characterId }),
        })
        if (!res.ok) throw new Error(`set active character failed: ${res.status}`)
        await Promise.all([loadCharacterList(), loadActiveCharacter(), loadAvatarMap()])
        return true
      } catch (e) {
        setAvatarErr(String(e))
        return false
      } finally {
        setAvatarBusy(false)
      }
    },
    [loadActiveCharacter, loadAvatarMap, loadCharacterList],
  )

  const deleteCharacter = useCallback(
    async (characterId: string) => {
      setAvatarBusy(true)
      setAvatarErr(null)
      try {
        const res = await fetch(`/api/avatar-characters/${characterId}`, { method: 'DELETE' })
        if (!res.ok) throw new Error(`delete character failed: ${res.status}`)
        await Promise.all([loadCharacterList(), loadActiveCharacter(), loadAvatarMap()])
        return true
      } catch (e) {
        setAvatarErr(String(e))
        return false
      } finally {
        setAvatarBusy(false)
      }
    },
    [loadActiveCharacter, loadAvatarMap, loadCharacterList],
  )

  const saveCharacterConfig = useCallback(
    async (characterId: string, config: AvatarCharacterConfigV1) => {
      setAvatarBusy(true)
      setAvatarErr(null)
      try {
        const res = await fetch(`/api/avatar-characters/${characterId}/config`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ config }),
        })
        if (!res.ok) throw new Error(`save character config failed: ${res.status}`)
        await Promise.all([loadCharacterList(), loadActiveCharacter(), loadAvatarMap()])
        return true
      } catch (e) {
        setAvatarErr(String(e))
        return false
      } finally {
        setAvatarBusy(false)
      }
    },
    [loadActiveCharacter, loadAvatarMap, loadCharacterList],
  )

  return {
    avatarMap,
    avatarEntries,
    avatarBusy,
    avatarErr,
    characters,
    activeCharacterId,
    activeCharacter,
    loadAvatarMap,
    loadAvatarSystem,
    loadCharacterList,
    loadActiveCharacter,
    loadCharacter,
    uploadAsset,
    bindEmotion,
    uploadAvatar,
    deleteAvatar,
    createCharacter,
    setActiveCharacter,
    deleteCharacter,
    saveCharacterConfig,
  }
}

export { EMOTIONS }
