'use client'

/**
 * Voice session UI, backed by the AssemblyAI Voice Agent API.
 *
 * A full-screen sheet below `lg` and a centred modal above it. The session
 * starts from the Start talking tap (iOS only lets audio start inside a tap),
 * an audio-reactive aura shows who is talking, and every failure ends on a
 * screen with a way out: reconnect after a drop, help when the microphone is
 * blocked, or back to typing.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'

import {
  Keyboard,
  Mic,
  MicOff,
  PhoneOff,
  Radio,
  RefreshCw,
  Sparkles,
  X
} from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle
} from '@/components/ui/dialog'
import { useStore } from '@/store'
import { CLOSE, OPEN, type ToolPayload } from '@/lib/toolPayload'
import { DEFAULT_AGENT_NAME, VOICE_MODE_LABEL } from '@/lib/agentIdentity'
import { cn } from '@/lib/utils'
import { StickToBottom } from 'use-stick-to-bottom'
import { BookingCard } from '../chat/ChatArea/Messages/tools/BookingCard'
import ScrollToBottom from '../chat/ChatArea/ScrollToBottom'

import { VoiceAura, type AuraState } from './VoiceAura'
import { VoiceDock } from './VoiceDock'
import {
  AssemblyAISession,
  type VoiceErrorKind,
  type VoiceSessionState
} from '@/lib/voice/AssemblyAISession'

interface AssemblyAIVoiceModalProps {
  isOpen: boolean
  onClose: () => void
  agentName?: string
}

interface Turn {
  id: string
  role: 'user' | 'agent'
  text: string
  final: boolean
  /**
   * A component this turn renders instead of text, such as the booking card.
   *
   * Spoken words and rendered components share one ordered transcript, so a
   * card appears where it happened in the conversation rather than pinned
   * somewhere separate.
   */
  card?: ToolPayload
}

/** Wash colour per aura state; matches the ring's colours in VoiceAura. */
const AURA_TINT: Record<AuraState, string> = {
  idle: '#f48c06',
  connecting: '#f48c06',
  listening: '#38bdf8',
  thinking: '#a78bfa',
  speaking: '#f48c06',
  muted: '#64748b',
  dropped: '#f43f5e',
  error: '#f43f5e'
}

export const AssemblyAIVoiceModal: React.FC<AssemblyAIVoiceModalProps> = ({
  isOpen,
  onClose,
  agentName = DEFAULT_AGENT_NAME
}) => {
  const { selectedEndpoint, setMessages, chatInputRef } = useStore()

  const [state, setState] = useState<VoiceSessionState>('idle')
  const [turns, setTurns] = useState<Turn[]>([])
  const [isMuted, setIsMuted] = useState(false)
  const [error, setError] = useState<{
    message: string
    kind: VoiceErrorKind
  } | null>(null)
  /** Clyde's latest finished reply, announced once to screen readers. */
  const [lastReply, setLastReply] = useState('')
  const [elapsed, setElapsed] = useState(0)

  const sessionRef = useRef<AssemblyAISession | null>(null)
  /** Id of the in-flight user turn, so partials update in place. */
  const partialIdRef = useRef<string | null>(null)
  const turnSeq = useRef(0)

  const nextId = () => `turn-${++turnSeq.current}`

  // --- Mirror finalized turns into the main chat panel --------------------
  // A voice session should leave behind a readable conversation, the same way
  // the LiveKit path did. Only final turns are written, so a partial never
  // lands in the transcript.
  const appendToChat = useCallback(
    (role: 'user' | 'agent', text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      setMessages((prev) => [
        ...prev,
        { role, content: trimmed, created_at: Date.now() }
      ])
    },
    [setMessages]
  )

  /**
   * Mirror a rendered component into the main chat panel.
   *
   * The spoken turns are already mirrored, so leaving the card behind makes
   * the written record disagree with what happened: the agent offers a booking
   * and no booking is in sight. The chat draws its cards from
   * `tool_calls[].result`, so the payload is written back in the same marker
   * form a text-mode tool would have produced, and the existing ToolCards path
   * renders it with no special case for voice.
   */
  const appendCardToChat = useCallback(
    (toolName: string, payload: ToolPayload) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'agent',
          content: '',
          created_at: Date.now(),
          tool_calls: [
            {
              role: 'tool' as const,
              content: null,
              tool_call_id: `voice-${toolName}-${Date.now()}`,
              tool_name: toolName,
              tool_args: {},
              tool_call_error: false,
              metrics: { time: 0 },
              created_at: Math.floor(Date.now() / 1000),
              result: `${OPEN}${JSON.stringify(payload)}${CLOSE}`
            }
          ]
        }
      ])
    },
    [setMessages]
  )

  // --- Session lifecycle --------------------------------------------------

  /** Tear down the current session, if any. */
  const stopSession = useCallback(() => {
    sessionRef.current?.end()
    sessionRef.current = null
    partialIdRef.current = null
  }, [])

  /**
   * Start a session. Must run synchronously inside the click handler: the
   * session creates its AudioContext before its first await.
   */
  const startSession = () => {
    stopSession()
    setError(null)
    setIsMuted(false)
    setElapsed(0)
    const session = new AssemblyAISession({
      onStateChange: (next, message, kind) => {
        if (sessionRef.current !== session) return
        setState(next)
        if (next === 'error') {
          setError({
            message: message ?? 'Something went wrong. Please try again.',
            kind: kind ?? 'other'
          })
        }
      },
      onUserPartial: (text) => {
        if (!text.trim()) return
        // Decide the id OUTSIDE the state updater: React runs updaters twice
        // in development, and a ref written inside one made the second run
        // drop the visitor's words entirely.
        const existing = partialIdRef.current
        const id = existing ?? nextId()
        partialIdRef.current = id
        setTurns((prev) =>
          prev.some((t) => t.id === id)
            ? prev.map((t) => (t.id === id ? { ...t, text } : t))
            : [...prev, { id, role: 'user', text, final: false }]
        )
      },
      onUserFinal: (text) => {
        const id = partialIdRef.current
        partialIdRef.current = null
        if (!text.trim()) {
          if (id) setTurns((prev) => prev.filter((t) => t.id !== id))
          return
        }
        const finalId = id ?? nextId()
        setTurns((prev) =>
          prev.some((t) => t.id === finalId)
            ? prev.map((t) =>
                t.id === finalId ? { ...t, text, final: true } : t
              )
            : [...prev, { id: finalId, role: 'user', text, final: true }]
        )
        appendToChat('user', text)
      },
      onAgentFinal: (text) => {
        if (!text.trim()) return
        setTurns((prev) => [
          ...prev,
          { id: nextId(), role: 'agent', text, final: true }
        ])
        setLastReply(text)
        appendToChat('agent', text)
      },
      onToolPayload: (payload) => {
        if (payload.type !== 'booking') return
        let added = false
        setTurns((prev) => {
          if (prev.some((t) => t.card?.type === 'booking')) return prev
          added = true
          return [
            ...prev,
            {
              id: nextId(),
              role: 'agent',
              text: '',
              final: true,
              card: payload
            }
          ]
        })
        if (added) appendCardToChat('get_booking_link', payload)
      }
    })
    sessionRef.current = session
    void session.start(selectedEndpoint)
  }

  // Closing the sheet always ends the session and resets the view.
  useEffect(() => {
    if (isOpen) return
    stopSession()
    setTurns([])
    setState('idle')
    setIsMuted(false)
    setError(null)
    setLastReply('')
  }, [isOpen, stopSession])

  useEffect(() => stopSession, [stopSession])

  const isLive =
    state === 'listening' || state === 'thinking' || state === 'speaking'

  // Call timer, only while connected.
  useEffect(() => {
    if (!isLive) return
    const id = window.setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => window.clearInterval(id)
  }, [isLive])

  const toggleMute = useCallback(() => {
    const session = sessionRef.current
    if (!session) return
    const next = !session.isMuted
    session.setMuted(next)
    setIsMuted(next)
  }, [])

  const handleClose = () => {
    stopSession()
    onClose()
  }

  const typeInstead = () => {
    handleClose()
    requestAnimationFrame(() => chatInputRef?.current?.focus())
  }

  // `M` toggles the mic on keyboards; Esc is handled by the dialog (ends).
  useEffect(() => {
    if (!isOpen || !isLive) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'm' && e.key !== 'M') return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target as HTMLElement | null
      if (el?.closest('input, textarea, [contenteditable="true"]')) return
      e.preventDefault()
      toggleMute()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, isLive, toggleMute])

  const getLevel = useCallback(() => {
    const session = sessionRef.current
    if (!session) return 0
    return state === 'speaking'
      ? session.getReplyLevel()
      : session.getMicLevel()
  }, [state])

  // --- View ---------------------------------------------------------------

  const auraState: AuraState = isLive && isMuted ? 'muted' : state

  const status = (() => {
    if (state === 'connecting')
      return {
        label: 'Connecting…',
        sub: 'Setting up the microphone and a secure voice line.',
        color: 'text-accentGold'
      }
    if (isMuted && isLive)
      return {
        label: 'Your mic is off',
        sub: `${agentName} can’t hear you. Tap the mic to talk again.`,
        color: 'text-secondary'
      }
    if (state === 'listening')
      return {
        label: 'Listening',
        sub: 'Go ahead — interrupt any time.',
        color: 'text-voice-listening'
      }
    if (state === 'thinking')
      return {
        label: 'Thinking…',
        sub: 'Looking through his work.',
        color: 'text-voice-thinking'
      }
    if (state === 'speaking')
      return {
        label: `${agentName} is speaking`,
        sub: 'Start talking to interrupt.',
        color: 'text-voice-speaking'
      }
    return null
  })()

  // The newest spoken turn is the live caption; everything before it is
  // history. Booking links always stay in history.
  let liveIndex = -1
  for (let i = turns.length - 1; i >= 0; i--) {
    if (!turns[i].card) {
      liveIndex = i
      break
    }
  }
  const live = liveIndex >= 0 ? turns[liveIndex] : undefined
  const history = turns.filter((_, i) => i !== liveIndex)

  const timer = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`
  const chip =
    state === 'dropped'
      ? 'Disconnected'
      : state === 'error'
        ? 'Not connected'
        : isLive
          ? `${agentName} · Live ${timer}`
          : agentName
  const canClose = !isLive && state !== 'connecting'

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent
        hideCloseButton
        aria-describedby="voice-sheet-description"
        className={cn(
          'top-0 left-0 flex h-dvh max-h-none w-screen max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-0 bg-background p-0 text-white',
          'lg:top-1/2 lg:left-1/2 lg:h-[760px] lg:max-h-[90vh] lg:w-[820px] lg:max-w-[calc(100vw-48px)] lg:-translate-x-1/2 lg:-translate-y-1/2 lg:rounded-3xl lg:border lg:border-white/10 lg:shadow-2xl lg:ring-1 lg:ring-white/10'
        )}
      >
        <DialogTitle className="sr-only">
          Voice conversation with {agentName}
        </DialogTitle>
        <DialogDescription id="voice-sheet-description" className="sr-only">
          Talk to {agentName} out loud. End returns you to the chat.
        </DialogDescription>
        <div className="sr-only" aria-live="polite">
          {lastReply}
        </div>

        {/* Desktop header: identity left, plain-words state and close right */}
        <div className="hidden shrink-0 items-center justify-between border-b border-white/10 bg-background/95 px-7 py-4 backdrop-blur-2xl lg:flex pointer-coarse:backdrop-blur-none">
          <div className="flex items-center gap-3">
            <span className="relative flex size-2.5" aria-hidden="true">
              {isLive && !isMuted && (
                <span className="absolute size-full animate-ping rounded-full bg-voice-listening opacity-75" />
              )}
              <span
                className={cn(
                  'relative size-2.5 rounded-full',
                  isLive
                    ? isMuted
                      ? 'bg-voice-muted'
                      : 'bg-voice-listening'
                    : state === 'dropped' || state === 'error'
                      ? 'bg-voice-error'
                      : 'bg-accentGold'
                )}
              />
            </span>
            <Radio className="size-4 text-voice-listening" aria-hidden="true" />
            <span className="font-mono text-xs font-medium text-zinc-200">
              {VOICE_MODE_LABEL}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 font-mono text-xs text-faint">
              {isLive ? `Live ${timer} · ` : ''}
              <span
                className={cn(
                  'font-semibold',
                  status?.color ?? 'text-zinc-300'
                )}
              >
                {status?.label ?? (state === 'idle' ? 'Ready' : chip)}
              </span>
            </span>
            <button
              type="button"
              onClick={handleClose}
              aria-label={isLive ? 'End call and close' : 'Close voice'}
              className="grid size-9 place-items-center rounded-full border border-white/10 bg-white/5 text-muted hover:border-white/20 hover:text-white focus-visible:outline-2 focus-visible:outline-accentGold"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Phone top: status chip, close only when no call is running */}
        <div className="relative flex shrink-0 items-center justify-center px-4 pt-[max(1rem,env(safe-area-inset-top))] pb-2 lg:hidden">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/6 px-3.5 py-1.5 font-mono text-xs tracking-wide shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] backdrop-blur-md pointer-coarse:backdrop-blur-none">
            <span
              className={cn(
                'size-[7px] rounded-full',
                isLive
                  ? isMuted
                    ? 'bg-voice-muted'
                    : 'bg-voice-listening shadow-[0_0_10px_#38bdf8]'
                  : state === 'dropped' || state === 'error'
                    ? 'bg-voice-error'
                    : 'bg-accentGold'
              )}
              aria-hidden="true"
            />
            {chip}
          </span>
          {canClose && (
            <button
              type="button"
              onClick={handleClose}
              aria-label="Close voice"
              className="absolute top-[max(0.5rem,env(safe-area-inset-top))] right-3 grid size-11 place-items-center rounded-2xl border border-white/10 bg-white/5 text-muted hover:text-white focus-visible:outline-2 focus-visible:outline-accentGold"
            >
              <X className="size-[18px]" aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Body: aura + words. Side by side at lg+ and on short screens. */}
        <div className="relative grid min-h-0 flex-1 grid-rows-[1fr] [@media(max-height:500px)]:grid-cols-2 [@media(max-height:500px)]:grid-rows-1">
          {/* Ambient wash: the card's background takes the aura's colour
              (cyan listening, ember speaking, violet thinking) and eases
              between them. Colour transitions on the element; the soft
              shape comes from the mask. */}
          <div
            className="pointer-events-none absolute -inset-x-px -top-px h-[78%] [mask-image:radial-gradient(ellipse_75%_70%_at_50%_30%,black,transparent_72%)] opacity-30 transition-colors duration-700 motion-reduce:transition-none"
            style={{ backgroundColor: AURA_TINT[auraState] }}
            aria-hidden="true"
          />
          {/* Aura is a free-floating light layer behind everything: large,
              unclipped by layout, and the conversation scrolls over it. */}
          <div
            className="pointer-events-none absolute inset-x-0 top-0 flex justify-center [@media(max-height:500px)]:inset-x-auto [@media(max-height:500px)]:left-0 [@media(max-height:500px)]:w-1/2"
            aria-hidden="true"
          >
            <VoiceAura
              state={auraState}
              getLevel={getLevel}
              className="aspect-square w-[min(115vw,62dvh)] -translate-y-[12%] lg:w-[620px] [@media(max-height:500px)]:w-[min(55vw,95dvh)]"
            />
          </div>

          <div className="relative z-10 flex min-h-0 flex-col px-6 pb-3 lg:mx-auto lg:w-full lg:max-w-xl [@media(max-height:500px)]:col-start-2">
            {state === 'idle' && (
              <div className="m-auto max-w-sm text-center">
                <h2 className="font-large text-[26px] font-extrabold tracking-tight">
                  Talk to {agentName}
                </h2>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">
                  Ask about Gichogu’s work or book a call — out loud. Your
                  browser will ask for the microphone.
                </p>
                <button
                  type="button"
                  onClick={startSession}
                  autoFocus
                  className="mt-6 inline-flex min-h-[52px] items-center gap-2 rounded-full bg-gradient-to-br from-brand to-accentGold px-7 font-large text-base font-bold text-background shadow-[0_10px_30px_rgba(232,93,4,0.35)] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold active:brightness-90"
                >
                  <Mic className="size-5" aria-hidden="true" />
                  Start talking
                </button>
              </div>
            )}

            {state === 'dropped' && (
              <div className="m-auto max-w-sm text-center" role="alert">
                <h2 className="font-large text-[22px] font-extrabold">
                  The call dropped
                </h2>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">
                  The connection paused, often because the screen locked. What
                  you said so far is saved in the chat.
                </p>
                <div className="mt-5 flex flex-col items-center gap-2.5">
                  <button
                    type="button"
                    onClick={startSession}
                    autoFocus
                    className="inline-flex min-h-[52px] items-center gap-2 rounded-full bg-gradient-to-br from-brand to-accentGold px-7 font-large text-base font-bold text-background focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold active:brightness-90"
                  >
                    <RefreshCw className="size-[18px]" aria-hidden="true" />
                    Reconnect
                  </button>
                  <button
                    type="button"
                    onClick={handleClose}
                    className="inline-flex min-h-[52px] items-center rounded-full border border-white/15 bg-white/6 px-7 font-large text-base font-bold focus-visible:outline-2 focus-visible:outline-accentGold"
                  >
                    Back to chat
                  </button>
                </div>
              </div>
            )}

            {state === 'error' && error && (
              <div className="m-auto max-w-sm text-center" role="alert">
                <h2 className="font-large text-[22px] font-extrabold">
                  {error.kind === 'mic-blocked'
                    ? 'I can’t hear you yet'
                    : 'Voice didn’t start'}
                </h2>
                <p className="mt-2 text-[15px] leading-relaxed text-muted">
                  {error.kind === 'mic-blocked' ? micHelp() : error.message}
                </p>
                <div className="mt-5 flex flex-col items-center gap-2.5">
                  <button
                    type="button"
                    onClick={startSession}
                    autoFocus
                    className="inline-flex min-h-[52px] items-center gap-2 rounded-full bg-gradient-to-br from-brand to-accentGold px-7 font-large text-base font-bold text-background focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold active:brightness-90"
                  >
                    Try again
                  </button>
                  <button
                    type="button"
                    onClick={
                      error.kind === 'mic-blocked' ? typeInstead : handleClose
                    }
                    className="inline-flex min-h-[52px] items-center gap-2 rounded-full border border-white/15 bg-white/6 px-7 font-large text-base font-bold focus-visible:outline-2 focus-visible:outline-accentGold"
                  >
                    {error.kind === 'mic-blocked' ? (
                      <>
                        <Keyboard className="size-[18px]" aria-hidden="true" />
                        Type instead
                      </>
                    ) : (
                      'Back to chat'
                    )}
                  </button>
                </div>
              </div>
            )}

            {status && (
              <>
                {/* History: earlier turns as small bubbles, newest at the
                    bottom; follows while at the bottom (sticky scroll). */}
                <StickToBottom
                  className="relative min-h-0 flex-1 [mask-image:linear-gradient(to_bottom,transparent,black_48px)]"
                  resize="smooth"
                  initial="instant"
                >
                  <StickToBottom.Content
                    className="flex min-h-full flex-col justify-end gap-2 pt-[26dvh] pb-2 lg:pt-[240px] [@media(max-height:500px)]:pt-2"
                    scrollClassName="overscroll-contain"
                    aria-live="off"
                  >
                    {history.map((turn) =>
                      turn.card?.type === 'booking' ? (
                        <div key={turn.id} className="w-full">
                          <BookingCard payload={turn.card} priority />
                        </div>
                      ) : (
                        <div
                          key={turn.id}
                          className={cn(
                            'flex',
                            turn.role === 'user'
                              ? 'justify-end'
                              : 'justify-start'
                          )}
                        >
                          <div
                            className={cn(
                              'voice-bubble-in max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed text-zinc-200 backdrop-blur-md pointer-coarse:backdrop-blur-none',
                              turn.role === 'user'
                                ? 'rounded-tr-md border border-voice-listening/25 bg-[#0c2233]/80'
                                : 'rounded-tl-md border border-white/10 bg-background-secondary/80'
                            )}
                          >
                            <span className="mb-0.5 block font-mono text-[11px] tracking-wide text-faint uppercase">
                              {turn.role === 'user' ? 'You' : agentName}
                            </span>
                            {turn.text}
                          </div>
                        </div>
                      )
                    )}
                  </StickToBottom.Content>
                  <ScrollToBottom />
                </StickToBottom>

                {/* Live caption: the current turn, large, words easing in as
                    they arrive (Gemini-style). */}
                <div className="shrink-0 border-t border-white/8 pt-2 pb-1">
                  <div className="shrink-0 pb-1 text-center">
                    <div
                      role="status"
                      className={cn(
                        'font-mono text-xs tracking-[0.14em] uppercase',
                        status.color
                      )}
                    >
                      {status.label}
                    </div>
                  </div>

                  {live ? (
                    <LiveCaption
                      key={live.id}
                      final={live.final}
                      who={live.role === 'user' ? 'You' : agentName}
                      text={live.text}
                      tone={live.role === 'user' ? 'user' : 'agent'}
                    />
                  ) : (
                    <p className="text-center text-sm text-faint">
                      {status.sub}
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {/* Desktop footer: identity left, compact controls right */}
        {(isLive || state === 'connecting') && (
          <div className="hidden shrink-0 items-center justify-between border-t border-white/10 px-6 py-4 lg:flex">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-gradient-to-br from-brand to-accentGold">
                <Sparkles className="size-5 text-white" aria-hidden="true" />
              </span>
              <div>
                <div className="font-large text-sm font-bold">{agentName}</div>
                <div className="font-mono text-xs text-faint">
                  <kbd className="rounded border border-white/15 px-1">M</kbd>{' '}
                  mute ·{' '}
                  <kbd className="rounded border border-white/15 px-1">Esc</kbd>{' '}
                  end
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {isLive && (
                <>
                  <button
                    type="button"
                    onClick={typeInstead}
                    aria-label="Type instead"
                    className="grid size-11 place-items-center rounded-full border border-white/12 bg-white/5 text-zinc-200 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-accentGold"
                  >
                    <Keyboard className="size-[18px]" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    onClick={toggleMute}
                    aria-pressed={isMuted}
                    aria-label={
                      isMuted ? 'Unmute microphone' : 'Mute microphone'
                    }
                    className={cn(
                      'grid size-11 place-items-center rounded-full border focus-visible:outline-2 focus-visible:outline-accentGold',
                      isMuted
                        ? 'border-voice-error/50 bg-voice-error/15 text-rose-300'
                        : 'border-white/12 bg-white/5 text-zinc-200 hover:bg-white/10'
                    )}
                  >
                    {isMuted ? (
                      <MicOff className="size-[18px]" aria-hidden="true" />
                    ) : (
                      <Mic className="size-[18px]" aria-hidden="true" />
                    )}
                  </button>
                </>
              )}
              <button
                type="button"
                onClick={handleClose}
                aria-label={isLive ? 'End call' : 'Cancel'}
                className="grid size-11 place-items-center rounded-full bg-rose-600 text-white shadow-[0_8px_24px_rgba(225,29,72,0.35)] hover:bg-rose-500 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accentGold"
              >
                <PhoneOff className="size-[18px]" aria-hidden="true" />
              </button>
            </div>
          </div>
        )}

        {/* Phone dock while a call is connecting or running */}
        {(isLive || state === 'connecting') && (
          <div className="shrink-0 px-5 pt-2 pb-[max(1.25rem,env(safe-area-inset-bottom))] lg:hidden lg:px-24">
            {state === 'connecting' ? (
              <div className="flex justify-center">
                <button
                  type="button"
                  onClick={handleClose}
                  className="inline-flex h-voice-control items-center gap-2 rounded-full bg-rose-600 px-8 font-large text-[15px] font-bold focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <VoiceDock
                isMuted={isMuted}
                isListening={state === 'listening'}
                onToggleMute={toggleMute}
                onEnd={handleClose}
                onTypeInstead={typeInstead}
              />
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * The current turn in large type. Each word is its own span keyed by
 * position, so only newly arrived words mount and run the soft fade-in;
 * words already shown stay still.
 */
function LiveCaption({
  who,
  text,
  tone,
  final
}: {
  who: string
  text: string
  tone: 'user' | 'agent'
  final: boolean
}) {
  const words = text.split(/\s+/).filter(Boolean)
  return (
    <div className="max-h-28 overflow-y-auto px-1 text-center">
      <span
        className={cn(
          'block font-mono text-[11px] tracking-[0.14em] uppercase',
          tone === 'user' ? 'text-voice-listening' : 'text-voice-speaking'
        )}
      >
        {who}
      </span>
      <p className="mt-1 font-large text-sm leading-snug font-medium text-zinc-100 lg:text-[15px]">
        {words.map((w, i) => (
          <span
            key={i}
            className="voice-word"
            // Clyde's reply lands whole, so stagger it to flow in; the
            // visitor's words already arrive one at a time.
            style={
              tone === 'agent'
                ? { animationDelay: `${Math.min(i * 45, 2500)}ms` }
                : undefined
            }
          >
            {w}{' '}
          </span>
        ))}
        {/* Still being transcribed: a soft blinking caret. */}
        {!final && <span className="voice-caret" aria-hidden="true" />}
      </p>
    </div>
  )
}

/** Where to re-allow the microphone, for the browser the visitor is on. */
function micHelp(): string {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  const iOS =
    /iPad|iPhone|iPod/.test(ua) ||
    (/Macintosh/.test(ua) &&
      typeof document !== 'undefined' &&
      'ontouchend' in document)
  if (iOS)
    return 'Microphone access is blocked. Tap aA in the address bar → Website Settings → Microphone: Allow, then try again.'
  if (/Chrome|Android/.test(ua))
    return 'Microphone access is blocked. Tap the site-settings icon left of the address → Permissions → Microphone: Allow, then try again.'
  return 'Microphone access is blocked. Allow microphone access for this site in your browser settings, then try again.'
}

export default AssemblyAIVoiceModal
