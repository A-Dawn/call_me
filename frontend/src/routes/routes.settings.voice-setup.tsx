import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { SettingsShell } from './settings-shell'
import type { AsrInstalledModel, AsrModelCandidate, AsrSourceItem } from '@/types/asr-model-registry'
import type { ApplyResult, ConnectivityResult, ValidationResult, VoiceSchema } from '@/types/voice-config'

type TabKey = 'quick' | 'advanced' | 'models'

type VoiceConfigObject = Record<string, unknown>

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function asObject(value: unknown): VoiceConfigObject {
  return isRecord(value) ? { ...value } : {}
}

export function SettingsVoiceSetupPage() {
  const [tab, setTab] = useState<TabKey>('quick')
  const [schema, setSchema] = useState<VoiceSchema | null>(null)
  const [config, setConfig] = useState<VoiceConfigObject>({})
  const [busy, setBusy] = useState(false)
  const [statusText, setStatusText] = useState<string>('')

  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [connectivity, setConnectivity] = useState<ConnectivityResult | null>(null)
  const [applyResult, setApplyResult] = useState<ApplyResult | null>(null)

  const [sources, setSources] = useState<AsrSourceItem[]>([])
  const [candidates, setCandidates] = useState<AsrModelCandidate[]>([])
  const [scanErrors, setScanErrors] = useState<Array<{ source_id: string; message: string }>>([])
  const [modelSearch, setModelSearch] = useState('')
  const [scanMeta, setScanMeta] = useState<{ total: number; returned: number; truncated: boolean }>({
    total: 0,
    returned: 0,
    truncated: false,
  })
  const [installed, setInstalled] = useState<AsrInstalledModel[]>([])

  const [selectedProvider, setSelectedProvider] = useState('doubao_ws')
  const [selectedTemplateId, setSelectedTemplateId] = useState('')

  const [ttsDraft, setTtsDraft] = useState('{}')
  const [asrDraft, setAsrDraft] = useState('{}')
  const [sherpaDraft, setSherpaDraft] = useState('{}')
  const [downloaderDraft, setDownloaderDraft] = useState('{}')

  const ttsSection = useMemo(() => asObject(config.tts), [config])
  const asrSection = useMemo(() => asObject(config.asr), [config])
  const blockedStats = useMemo(() => {
    const stats: Record<string, number> = {}
    for (const item of candidates) {
      const key = item.blocked_reason || (item.downloadable ? 'DOWNLOADABLE' : 'UNKNOWN')
      stats[key] = (stats[key] || 0) + 1
    }
    return stats
  }, [candidates])
  const filteredCandidates = useMemo(() => {
    const q = modelSearch.trim().toLowerCase()
    if (!q) return candidates
    return candidates.filter((item) =>
      [
        item.artifact_name,
        item.source_id,
        item.release_tag,
        item.channel,
        item.license_spdx,
        item.blocked_reason,
      ]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [candidates, modelSearch])
  const filteredInstalled = useMemo(() => {
    const q = modelSearch.trim().toLowerCase()
    if (!q) return installed
    return installed.filter((item) =>
      [item.artifact_name, item.source_id, item.artifact_key, item.install_dir]
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [installed, modelSearch])

  const templateOptions = useMemo(() => {
    if (!schema) return []
    return schema.wizard.tts_templates[selectedProvider] || []
  }, [schema, selectedProvider])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setBusy(true)
      setStatusText('加载配置中...')
      try {
        const [schemaRes, currentRes] = await Promise.all([
          fetch('/api/config/asr-tts/schema'),
          fetch('/api/config/asr-tts/current'),
        ])
        if (!schemaRes.ok || !currentRes.ok) throw new Error('failed to load voice setup api')
        const schemaJson = (await schemaRes.json()) as VoiceSchema
        const currentJson = (await currentRes.json()) as { config?: Record<string, unknown> }
        if (cancelled) return
        setSchema(schemaJson)
        const nextCfg = asObject(currentJson.config)
        setConfig(nextCfg)

        const tts = asObject(nextCfg.tts)
        const provider = typeof tts.type === 'string' ? tts.type : 'doubao_ws'
        setSelectedProvider(provider)
        const firstTemplate = schemaJson.wizard.tts_templates[provider]?.[0]?.id || ''
        setSelectedTemplateId(firstTemplate)

        setTtsDraft(JSON.stringify(asObject(nextCfg.tts), null, 2))
        setAsrDraft(JSON.stringify(asObject(nextCfg.asr), null, 2))
        setSherpaDraft(JSON.stringify(asObject(nextCfg.sherpa), null, 2))
        setDownloaderDraft(JSON.stringify(asObject(nextCfg.model_downloader), null, 2))

        setStatusText('配置已加载')
      } catch (e) {
        if (!cancelled) setStatusText(`加载失败: ${String(e)}`)
      } finally {
        if (!cancelled) setBusy(false)
      }
    }

    void run()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const [sourcesRes, installedRes] = await Promise.all([
          fetch('/api/asr-models/sources'),
          fetch('/api/asr-models/installed'),
        ])
        if (!sourcesRes.ok || !installedRes.ok) return
        const sourcesJson = (await sourcesRes.json()) as { items?: AsrSourceItem[] }
        const installedJson = (await installedRes.json()) as { items?: AsrInstalledModel[] }
        if (cancelled) return
        setSources(Array.isArray(sourcesJson.items) ? sourcesJson.items : [])
        setInstalled(Array.isArray(installedJson.items) ? installedJson.items : [])
      } catch {
        // ignore
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [])

  const patchConfig = (section: string, key: string, value: unknown) => {
    setConfig((prev) => {
      const next = { ...prev }
      const sec = asObject(next[section])
      sec[key] = value
      next[section] = sec
      return next
    })
  }

  const applyTemplate = () => {
    const template = templateOptions.find((item) => item.id === selectedTemplateId)
    if (!template) return
    setConfig((prev) => {
      const next = { ...prev }
      next.tts = { ...asObject(next.tts), ...template.defaults }
      return next
    })
    setStatusText(`已应用模板: ${template.label}`)
  }

  const runValidate = async () => {
    setBusy(true)
    setStatusText('校验中...')
    try {
      const res = await fetch('/api/config/asr-tts/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config }),
      })
      const json = (await res.json()) as ValidationResult
      setValidation(json)
      setStatusText(json.ok ? '校验通过' : '校验存在错误')
    } catch (e) {
      setStatusText(`校验失败: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const runConnectivity = async () => {
    setBusy(true)
    setStatusText('连通性测试中...')
    try {
      const res = await fetch('/api/config/asr-tts/test-connectivity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config }),
      })
      const json = (await res.json()) as ConnectivityResult
      setConnectivity(json)
      setStatusText(json.ok ? '连通性通过' : '连通性失败')
    } catch (e) {
      setStatusText(`连通性测试失败: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const runApply = async () => {
    setBusy(true)
    setStatusText('应用配置并重启中...')
    try {
      const res = await fetch('/api/config/asr-tts/apply', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config }),
      })
      const json = (await res.json()) as ApplyResult
      setApplyResult(json)
      setStatusText(json.health_ok ? '应用成功' : '应用完成但健康检查异常')
    } catch (e) {
      setStatusText(`应用失败: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const saveAdvancedDraft = () => {
    try {
      const nextTts = JSON.parse(ttsDraft) as Record<string, unknown>
      const nextAsr = JSON.parse(asrDraft) as Record<string, unknown>
      const nextSherpa = JSON.parse(sherpaDraft) as Record<string, unknown>
      const nextDownloader = JSON.parse(downloaderDraft) as Record<string, unknown>
      setConfig((prev) => ({
        ...prev,
        tts: nextTts,
        asr: nextAsr,
        sherpa: nextSherpa,
        model_downloader: nextDownloader,
      }))
      setStatusText('高级参数草稿已写入配置')
    } catch (e) {
      setStatusText(`JSON 解析失败: ${String(e)}`)
    }
  }

  const refreshModelLists = async () => {
    const [sourcesRes, installedRes] = await Promise.all([
      fetch('/api/asr-models/sources'),
      fetch('/api/asr-models/installed'),
    ])
    if (sourcesRes.ok) {
      const json = (await sourcesRes.json()) as { items?: AsrSourceItem[] }
      setSources(Array.isArray(json.items) ? json.items : [])
    }
    if (installedRes.ok) {
      const json = (await installedRes.json()) as { items?: AsrInstalledModel[] }
      setInstalled(Array.isArray(json.items) ? json.items : [])
    }
  }

  const scanCandidates = async () => {
    setBusy(true)
    setStatusText('扫描模型中...')
    setScanErrors([])
    setScanMeta({ total: 0, returned: 0, truncated: false })
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 90000)
    try {
      const res = await fetch('/api/asr-models/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ include_disabled: false, timeout_sec: 60, max_items: 300 }),
        signal: controller.signal,
      })
      const json = (await res.json()) as {
        items?: AsrModelCandidate[]
        errors?: Array<{ source_id: string; message: string }>
        total_candidates?: number
        returned_candidates?: number
        truncated?: boolean
      }
      if (!res.ok) {
        throw new Error(JSON.stringify(json))
      }
      const nextCandidates = Array.isArray(json.items) ? json.items : []
      const nextErrors = Array.isArray(json.errors) ? json.errors : []
      const total = Number(json.total_candidates || nextCandidates.length || 0)
      const returned = Number(json.returned_candidates || nextCandidates.length || 0)
      const truncated = Boolean(json.truncated)
      setCandidates(nextCandidates)
      setScanErrors(nextErrors)
      setScanMeta({ total, returned, truncated })
      if (nextCandidates.length === 0 && nextErrors.length > 0) {
        setStatusText(`扫描完成：0 个候选，${nextErrors.length} 个来源失败（展开错误详情查看）`)
      } else if (nextCandidates.length === 0) {
        setStatusText('扫描完成：未发现候选（可能被 file_patterns 过滤或来源暂不可用）')
      } else {
        setStatusText(
          truncated
            ? `扫描完成：总计 ${total} 个候选，当前展示前 ${returned} 个（已截断）`
            : `扫描完成：${nextCandidates.length} 个候选`,
        )
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        setStatusText('扫描超时（90s），可重试或先检查网络与 GITHUB_TOKEN')
      } else {
        setStatusText(`扫描失败: ${String(e)}`)
      }
    } finally {
      window.clearTimeout(timer)
      setBusy(false)
    }
  }

  const acceptLicenseAndInstall = async (candidate: AsrModelCandidate) => {
    setBusy(true)
    setStatusText(`安装 ${candidate.artifact_name} ...`)
    try {
      if (candidate.blocked_reason === 'LICENSE_NOT_ACCEPTED') {
        await fetch('/api/asr-models/licenses/accept', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source_id: candidate.source_id, license_spdx: candidate.license_spdx }),
        })
      }

      const installRes = await fetch('/api/asr-models/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate }),
      })
      if (!installRes.ok) {
        const detail = await installRes.text()
        throw new Error(detail)
      }

      await refreshModelLists()
      setStatusText(`安装成功: ${candidate.artifact_name}`)
    } catch (e) {
      setStatusText(`安装失败: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const applyInstalled = async (installId: string) => {
    setBusy(true)
    setStatusText('应用已安装模型并重启...')
    try {
      const res = await fetch('/api/asr-models/apply-installed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ install_id: installId }),
      })
      if (!res.ok) {
        throw new Error(await res.text())
      }
      setStatusText('已应用模型并重启')
    } catch (e) {
      setStatusText(`应用失败: ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <SettingsShell title="语音配置向导" description="ASR/TTS 白痴化配置、模型巡查下载、协议确认与一键应用。">
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <Button variant={tab === 'quick' ? 'default' : 'outline'} onClick={() => setTab('quick')}>
            快速向导
          </Button>
          <Button variant={tab === 'advanced' ? 'default' : 'outline'} onClick={() => setTab('advanced')}>
            高级参数
          </Button>
          <Button variant={tab === 'models' ? 'default' : 'outline'} onClick={() => setTab('models')}>
            ASR模型管理
          </Button>
        </div>

        <div className="rounded-xl border border-border/70 bg-background/75 p-3 text-xs text-muted-foreground">{statusText}</div>

        {tab === 'quick' ? (
          <div className="space-y-4">
            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="text-sm font-medium">TTS Provider / 模板</div>
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <select
                  value={selectedProvider}
                  onChange={(e) => {
                    const provider = e.target.value
                    setSelectedProvider(provider)
                    patchConfig('tts', 'type', provider)
                    const first = (schema?.wizard.tts_templates[provider] || [])[0]
                    setSelectedTemplateId(first?.id || '')
                  }}
                  className="h-10 rounded-md border bg-background px-3 text-sm"
                >
                  {(schema?.wizard.tts_provider_options || []).map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>

                <select
                  value={selectedTemplateId}
                  onChange={(e) => setSelectedTemplateId(e.target.value)}
                  className="h-10 rounded-md border bg-background px-3 text-sm"
                >
                  {templateOptions.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>

                <Button variant="secondary" onClick={applyTemplate} disabled={!selectedTemplateId}>
                  应用模板
                </Button>
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-background/75 p-4">
              <div className="text-sm font-medium">关键字段（快速编辑）</div>
              {selectedProvider === 'doubao_ws' ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  <Input
                    value={String(ttsSection.api_url || '')}
                    onChange={(e) => patchConfig('tts', 'api_url', e.target.value)}
                    placeholder="tts.api_url"
                  />
                  <Input
                    value={String(ttsSection.doubao_resource_id || '')}
                    onChange={(e) => patchConfig('tts', 'doubao_resource_id', e.target.value)}
                    placeholder="tts.doubao_resource_id"
                  />
                  <Input
                    value={String(ttsSection.doubao_voice_type || '')}
                    onChange={(e) => patchConfig('tts', 'doubao_voice_type', e.target.value)}
                    placeholder="tts.doubao_voice_type"
                  />
                  <Input
                    value={String(ttsSection.doubao_app_key || '')}
                    onChange={(e) => patchConfig('tts', 'doubao_app_key', e.target.value)}
                    placeholder="tts.doubao_app_key"
                  />
                  <Input
                    value={String(ttsSection.doubao_access_key || '')}
                    onChange={(e) => patchConfig('tts', 'doubao_access_key', e.target.value)}
                    placeholder="tts.doubao_access_key"
                  />
                  <Input
                    value={String(asrSection.type || '')}
                    onChange={(e) => patchConfig('asr', 'type', e.target.value)}
                    placeholder="asr.type"
                  />
                </div>
              ) : null}

              {selectedProvider === 'sovits' ? (
                <>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    <Input
                      value={String(ttsSection.api_url || '')}
                      onChange={(e) => patchConfig('tts', 'api_url', e.target.value)}
                      placeholder="tts.api_url (e.g. http://127.0.0.1:9880)"
                    />
                    <Input
                      value={String(ttsSection.voice_id || '')}
                      onChange={(e) => patchConfig('tts', 'voice_id', e.target.value)}
                      placeholder="tts.voice_id"
                    />
                    <Input
                      value={String(asrSection.type || '')}
                      onChange={(e) => patchConfig('asr', 'type', e.target.value)}
                      placeholder="asr.type"
                    />
                    <Input
                      value={String(ttsSection.ref_audio_path || '')}
                      onChange={(e) => patchConfig('tts', 'ref_audio_path', e.target.value)}
                      placeholder="tts.ref_audio_path"
                    />
                    <Input
                      value={String(ttsSection.prompt_lang || '')}
                      onChange={(e) => patchConfig('tts', 'prompt_lang', e.target.value)}
                      placeholder="tts.prompt_lang"
                    />
                    <Input
                      value={String(ttsSection.text_lang || '')}
                      onChange={(e) => patchConfig('tts', 'text_lang', e.target.value)}
                      placeholder="tts.text_lang"
                    />
                    <Input
                      value={String(ttsSection.prompt_text || '')}
                      onChange={(e) => patchConfig('tts', 'prompt_text', e.target.value)}
                      placeholder="tts.prompt_text"
                    />
                    <Input
                      value={String(ttsSection.text_split_method || '')}
                      onChange={(e) => patchConfig('tts', 'text_split_method', e.target.value)}
                      placeholder="tts.text_split_method"
                    />
                    <Input
                      value={String(ttsSection.gpt_weights || '')}
                      onChange={(e) => patchConfig('tts', 'gpt_weights', e.target.value)}
                      placeholder="tts.gpt_weights (optional)"
                    />
                    <Input
                      value={String(ttsSection.sovits_weights || '')}
                      onChange={(e) => patchConfig('tts', 'sovits_weights', e.target.value)}
                      placeholder="tts.sovits_weights (optional)"
                    />
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    GPT-SoVITS 建议将 `tts.api_url` 填为服务根地址（例如 `http://127.0.0.1:9880`），系统会按 SoVITS 接口路径进行探测。若填写了 `gpt_weights/sovits_weights`，会优先尝试调用 `/set_gpt_weights` 和 `/set_sovits_weights`。
                  </div>
                </>
              ) : null}

              {selectedProvider === 'cosyvoice_http' ? (
                <>
                  <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    <Input
                      value={String(ttsSection.api_url || '')}
                      onChange={(e) => patchConfig('tts', 'api_url', e.target.value)}
                      placeholder="tts.api_url (e.g. http://127.0.0.1:50000)"
                    />
                    <select
                      value={String(ttsSection.cosyvoice_mode || 'cross_lingual')}
                      onChange={(e) => patchConfig('tts', 'cosyvoice_mode', e.target.value)}
                      className="h-10 rounded-md border bg-background px-3 text-sm"
                    >
                      <option value="cross_lingual">cross_lingual</option>
                      <option value="zero_shot">zero_shot</option>
                    </select>
                    <Input
                      value={String(ttsSection.cosyvoice_sample_rate || 22050)}
                      onChange={(e) => patchConfig('tts', 'cosyvoice_sample_rate', Number(e.target.value || 22050))}
                      placeholder="tts.cosyvoice_sample_rate"
                    />
                    <Input
                      value={String(ttsSection.cosyvoice_ref_audio_path || '')}
                      onChange={(e) => patchConfig('tts', 'cosyvoice_ref_audio_path', e.target.value)}
                      placeholder="tts.cosyvoice_ref_audio_path"
                    />
                    <Input
                      value={String(ttsSection.cosyvoice_ref_text || '')}
                      onChange={(e) => patchConfig('tts', 'cosyvoice_ref_text', e.target.value)}
                      placeholder="tts.cosyvoice_ref_text (zero_shot required)"
                    />
                    <Input
                      value={String(asrSection.type || '')}
                      onChange={(e) => patchConfig('asr', 'type', e.target.value)}
                      placeholder="asr.type"
                    />
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    CosyVoice 官方 FastAPI 协议使用 multipart/form-data 调用 `/inference_cross_lingual` 或 `/inference_zero_shot`，流式返回原始 PCM。
                  </div>
                </>
              ) : null}

              {selectedProvider === 'mock' ? (
                <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  <Input
                    value={String(asrSection.type || '')}
                    onChange={(e) => patchConfig('asr', 'type', e.target.value)}
                    placeholder="asr.type"
                  />
                </div>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void runValidate()} disabled={busy}>
                校验配置
              </Button>
              <Button variant="secondary" onClick={() => void runConnectivity()} disabled={busy}>
                连通性测试
              </Button>
              <Button variant="outline" onClick={() => void runApply()} disabled={busy}>
                保存并应用
              </Button>
            </div>

            {validation ? (
              <pre className="max-h-80 overflow-auto rounded-xl border border-border/70 bg-muted/70 p-3 text-xs">{JSON.stringify(validation, null, 2)}</pre>
            ) : null}
            {connectivity ? (
              <pre className="max-h-80 overflow-auto rounded-xl border border-border/70 bg-muted/70 p-3 text-xs">{JSON.stringify(connectivity, null, 2)}</pre>
            ) : null}
            {applyResult ? (
              <pre className="max-h-80 overflow-auto rounded-xl border border-border/70 bg-muted/70 p-3 text-xs">{JSON.stringify(applyResult, null, 2)}</pre>
            ) : null}
          </div>
        ) : null}

        {tab === 'advanced' ? (
          <div className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-2">
              <div>
                <div className="mb-1 text-xs font-medium">[tts]</div>
                <Textarea value={ttsDraft} onChange={(e) => setTtsDraft(e.target.value)} className="min-h-56 font-mono text-xs" />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium">[asr]</div>
                <Textarea value={asrDraft} onChange={(e) => setAsrDraft(e.target.value)} className="min-h-56 font-mono text-xs" />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium">[sherpa]</div>
                <Textarea value={sherpaDraft} onChange={(e) => setSherpaDraft(e.target.value)} className="min-h-56 font-mono text-xs" />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium">[model_downloader]</div>
                <Textarea value={downloaderDraft} onChange={(e) => setDownloaderDraft(e.target.value)} className="min-h-56 font-mono text-xs" />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button onClick={saveAdvancedDraft}>写入草稿到配置</Button>
              <Button variant="secondary" onClick={() => void runValidate()}>
                校验
              </Button>
              <Button variant="outline" onClick={() => void runApply()}>
                保存并应用
              </Button>
            </div>
          </div>
        ) : null}

        {tab === 'models' ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void scanCandidates()} disabled={busy}>
                扫描可用模型
              </Button>
              <Button variant="outline" onClick={() => void refreshModelLists()} disabled={busy}>
                刷新来源/已安装
              </Button>
              <Input
                value={modelSearch}
                onChange={(e) => setModelSearch(e.target.value)}
                placeholder="搜索模型名/来源/tag/状态"
                className="min-w-64"
              />
            </div>

            <div className="rounded-xl border border-border/70 bg-background/75 p-3 text-xs text-muted-foreground">
              扫描统计：候选 {scanMeta.returned || candidates.length}
              {scanMeta.total > 0 ? ` / 总量 ${scanMeta.total}` : ''}
              {' '} / 可下载 {candidates.filter((x) => x.downloadable).length} / 来源错误 {scanErrors.length}
              {Object.keys(blockedStats).length > 0 ? (
                <div className="mt-1">
                  阻断分布：{Object.entries(blockedStats).map(([k, v]) => `${k}:${v}`).join('，')}
                </div>
              ) : null}
            </div>

            <details className="rounded-xl border border-border/70 bg-background/75 p-3" open>
              <summary className="cursor-pointer text-sm font-medium">来源列表 ({sources.length})</summary>
              <pre className="mt-2 max-h-56 overflow-auto rounded bg-muted/70 p-2 text-xs">{JSON.stringify(sources, null, 2)}</pre>
            </details>

            <details className="rounded-xl border border-border/70 bg-background/75 p-3" open={scanErrors.length > 0}>
              <summary className="cursor-pointer text-sm font-medium">扫描错误详情 ({scanErrors.length})</summary>
              {scanErrors.length > 0 ? (
                <div className="mt-2 space-y-2">
                  {scanErrors.map((err, idx) => (
                    <div key={`${err.source_id}-${idx}`} className="rounded bg-muted/70 p-2 text-xs">
                      <div className="font-medium">{err.source_id}</div>
                      <div className="mt-1 break-all text-muted-foreground">{err.message}</div>
                    </div>
                  ))}
                  <div className="text-xs text-muted-foreground">
                    若错误含 `403`/`rate limit`，请设置环境变量 `GITHUB_TOKEN` 后重试扫描。
                  </div>
                </div>
              ) : (
                <div className="mt-2 text-xs text-muted-foreground">暂无扫描错误</div>
              )}
            </details>

            <div className="space-y-2">
              <div className="text-sm font-medium">候选模型 ({filteredCandidates.length}/{candidates.length})</div>
              <div className="max-h-80 space-y-2 overflow-auto">
                {filteredCandidates.map((item) => (
                  <div key={item.candidate_id} className="rounded-lg border border-border/70 bg-background/75 p-2 text-xs">
                    <div className="font-medium">{item.artifact_name}</div>
                    <div className="mt-1 text-muted-foreground">{item.source_id} / {item.channel} / {item.release_tag || '-'}</div>
                    <div className="mt-1 text-muted-foreground">license: {item.license_spdx || '-'} / blocked: {item.blocked_reason || '-'}</div>
                    <div className="mt-2 flex gap-2">
                      <Button
                        size="sm"
                        disabled={busy || (!item.downloadable && item.blocked_reason !== 'LICENSE_NOT_ACCEPTED')}
                        onClick={() => void acceptLicenseAndInstall(item)}
                      >
                        下载并安装
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">已安装模型 ({filteredInstalled.length}/{installed.length})</div>
              <div className="max-h-80 space-y-2 overflow-auto">
                {filteredInstalled.map((item) => (
                  <div key={item.install_id} className="rounded-lg border border-border/70 bg-background/75 p-2 text-xs">
                    <div className="font-medium">{item.artifact_name}</div>
                    <div className="mt-1 text-muted-foreground">{item.install_dir}</div>
                    <div className="mt-2 flex gap-2">
                      <Button size="sm" variant="secondary" disabled={busy} onClick={() => void applyInstalled(item.install_id)}>
                        设为当前并应用
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </SettingsShell>
  )
}
