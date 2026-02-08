import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { SettingsShell } from './settings-shell'
import { useCallSession } from '@/context/call-session-context'

export function SettingsDiagnosticsPage() {
  const { conn, transcript, sendText, clearEventLog } = useCallSession()
  const [textInput, setTextInput] = useState('')

  const onSend = () => {
    const ok = sendText(textInput)
    if (ok) setTextInput('')
  }

  return (
    <SettingsShell title="调试诊断" description="手动输入、日志与原始文本视图。默认折叠，避免干扰主界面。">
      <div className="space-y-4">
        <div className="rounded-xl border border-border/70 bg-background/75 p-4">
          <div className="text-sm font-medium">手动 input.text</div>
          <div className="mt-3 flex gap-2">
            <Input
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder="输入测试文本"
              disabled={conn.status !== 'connected'}
              data-testid="text-input"
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSend()
              }}
            />
            <Button onClick={onSend} disabled={conn.status !== 'connected'} data-testid="send-text">
              发送
            </Button>
          </div>
        </div>

        <details className="rounded-xl border border-border/70 bg-background/75 p-4">
          <summary className="cursor-pointer text-sm font-medium">ASR 原始文本</summary>
          <div className="mt-3 space-y-2">
            <Textarea value={transcript.asrText} readOnly className="min-h-24 font-mono text-sm" />
            <div className="text-xs text-muted-foreground">{transcript.asrIsFinal ? 'final' : 'partial'}</div>
          </div>
        </details>

        <details className="rounded-xl border border-border/70 bg-background/75 p-4">
          <summary className="cursor-pointer text-sm font-medium">助手原始流式文本</summary>
          <div className="mt-3">
            <Textarea value={transcript.assistantText} readOnly className="min-h-24 font-mono text-sm" />
          </div>
        </details>

        <details className="rounded-xl border border-border/70 bg-background/75 p-4">
          <summary className="cursor-pointer text-sm font-medium">事件日志</summary>
          <div className="mt-3 space-y-3">
            <div className="flex justify-end">
              <Button variant="outline" onClick={clearEventLog}>
                清空日志
              </Button>
            </div>
            <pre className="max-h-72 overflow-auto rounded-md bg-muted/70 p-3 text-xs" data-testid="event-log">
              {transcript.log.join('\n')}
            </pre>
          </div>
        </details>
      </div>
    </SettingsShell>
  )
}
