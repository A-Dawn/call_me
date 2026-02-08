import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useRef } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AvatarStage } from '@/components/avatar/AvatarStage'
import { useCallSession } from '@/context/call-session-context'
import { useAvatarManagerContext } from '@/context/avatar-manager-context'
import { cn } from '@/lib/utils'

function formatDuration(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60).toString().padStart(2, '0')
  const s = (totalSeconds % 60).toString().padStart(2, '0')
  return `${m}:${s}`
}

export function IndexPage() {
  const {
    conn,
    micMode,
    activeEmotion,
    speechEnergy,
    dialogueTurns,
    transcript,
    callDurationSec,
    setMicMode,
    connect,
    disconnect,
    startMic,
    stopMic,
    interrupt,
  } = useCallSession()
  const { avatarMap, activeCharacter } = useAvatarManagerContext()
  const dialogueScrollRef = useRef<HTMLDivElement | null>(null)

  const holdToTalkHint = conn.mic === 'on' ? '松开结束录音（空格同效）' : '按住说话（空格同效）'

  const statusText = useMemo(() => {
    if (conn.status === 'connected') return '已接通'
    if (conn.status === 'connecting') return '连接中'
    return '未连接'
  }, [conn.status])

  const dialogueLines = useMemo(() => {
    const lines: Array<{ id: string; role: 'user' | 'assistant'; text: string }> = []
    for (const turn of dialogueTurns) {
      if (turn.user) lines.push({ id: `${turn.id}-u`, role: 'user', text: turn.user })
      if (turn.assistant) lines.push({ id: `${turn.id}-a`, role: 'assistant', text: turn.assistant })
    }
    return lines.slice(-6)
  }, [dialogueTurns])

  const isActiveAudioState = conn.mic === 'on' || conn.callState === 'speaking'
  const callDurationText = formatDuration(callDurationSec)

  useEffect(() => {
    const el = dialogueScrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [dialogueLines])

  return (
    <div className="relative min-h-[calc(100dvh-7.5rem)] overflow-hidden rounded-3xl border border-border/60 bg-[radial-gradient(circle_at_20%_20%,rgba(36,142,255,0.16),transparent_46%),radial-gradient(circle_at_80%_5%,rgba(32,201,151,0.12),transparent_38%),linear-gradient(180deg,rgba(248,252,255,0.92),rgba(235,244,255,0.88))] p-3 sm:p-5">
      <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.22),rgba(255,255,255,0)_45%)]" />

      <div className="relative z-10 flex h-full min-h-[calc(100dvh-10rem)] flex-col gap-3">
        <section className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-border/60 bg-background/70 px-3 py-2 backdrop-blur">
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{statusText}</Badge>
            {conn.callState ? <Badge variant="secondary">{conn.callState}</Badge> : null}
            <Badge variant="outline">emotion: {activeEmotion}</Badge>
            <Badge variant="outline">{conn.mic === 'on' ? 'mic:on' : 'mic:off'}</Badge>
            {conn.status === 'connected' ? <Badge variant="outline">通话时长 {callDurationText}</Badge> : null}
          </div>
          <div className="flex items-center gap-2">
            <Link
              to="/settings"
              className="rounded-full border border-border/70 bg-background/75 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              设置
            </Link>
          </div>
        </section>

        <section className="grid flex-1 gap-3 lg:grid-cols-[1fr_360px]">
          <div className="relative overflow-hidden rounded-2xl border border-border/60 bg-background/55 backdrop-blur-sm">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_6%,rgba(56,189,248,0.18),transparent_42%)]" />
            <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(0,0,0,0)_35%,rgba(8,17,30,0.44)_100%)]" />
            <AvatarStage
              activeEmotion={activeEmotion}
              callState={conn.callState}
              speechEnergy={speechEnergy}
              character={activeCharacter}
              fallbackAvatarMap={avatarMap}
              className="relative min-h-[38vh]"
            />

            <div className="absolute inset-x-0 bottom-0 p-3">
              <div className="rounded-xl border border-white/20 bg-black/35 p-3 text-white backdrop-blur">
                <div className="flex items-center justify-between gap-2 text-[11px] uppercase tracking-wide text-white/70">
                  <span>实时字幕</span>
                  <span className="inline-flex items-center gap-1">
                    <span className={cn('h-2 w-2 rounded-full', isActiveAudioState ? 'bg-emerald-400 animate-pulse' : 'bg-white/40')} />
                    {isActiveAudioState ? 'voice active' : 'idle'}
                  </span>
                </div>
                <div className="mt-1 line-clamp-2 min-h-8 text-sm">
                  {transcript.asrText || '等待你的声音…'}
                </div>
                <div className="mt-1 flex items-center justify-between text-[11px] text-white/70">
                  <span>{transcript.asrIsFinal ? 'final' : 'partial'}</span>
                  <span>触摸立绘可触发微动作反馈</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex min-h-[38vh] flex-col rounded-2xl border border-border/60 bg-background/80 p-3 backdrop-blur sm:p-4">
            <div className="text-sm font-medium">通话对话</div>
            <div ref={dialogueScrollRef} className="mt-3 flex-1 space-y-2 overflow-auto">
              {dialogueLines.length ? (
                dialogueLines.map((item) => (
                  <div key={item.id} className={`flex ${item.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                    <div
                      className={`max-w-[92%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                        item.role === 'user'
                          ? 'bg-primary/90 text-primary-foreground'
                          : 'border border-border/70 bg-card/85 text-foreground'
                      }`}
                    >
                      {item.text}
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">等待开始对话…</div>
              )}
            </div>

            <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
              <div className="flex flex-wrap gap-2">
                {conn.status !== 'connected' ? (
                  <Button onClick={connect} data-testid="ws-connect">
                    接通
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={disconnect}>
                    挂断
                  </Button>
                )}

                <Button variant={micMode === 'push_to_talk' ? 'default' : 'outline'} onClick={() => setMicMode('push_to_talk')}>
                  按住说话
                </Button>
                <Button variant={micMode === 'hands_free' ? 'default' : 'outline'} onClick={() => setMicMode('hands_free')}>
                  持续监听
                </Button>
              </div>

              <div className="flex flex-wrap gap-2">
                {micMode === 'hands_free' ? (
                  <Button
                    variant={conn.mic === 'on' ? 'destructive' : 'secondary'}
                    onClick={conn.mic === 'on' ? stopMic : startMic}
                    disabled={conn.status !== 'connected'}
                  >
                    {conn.mic === 'on' ? '停止麦克风' : '开启麦克风'}
                  </Button>
                ) : (
                  <Button
                    variant={conn.mic === 'on' ? 'destructive' : 'secondary'}
                    disabled={conn.status !== 'connected'}
                    onPointerDown={() => {
                      void startMic()
                    }}
                    onPointerUp={stopMic}
                    onPointerLeave={stopMic}
                    onPointerCancel={stopMic}
                  >
                    {holdToTalkHint}
                  </Button>
                )}

                <Button variant="outline" onClick={interrupt} disabled={conn.status !== 'connected'}>
                  打断
                </Button>
              </div>
              {micMode === 'push_to_talk' ? (
                <div className="text-xs text-muted-foreground">快捷键：按住空格开始录音，松开结束。输入框聚焦时自动禁用。</div>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
