'use client'

/**
 * Voice session UI, backed by the AssemblyAI Voice Agent API.
 *
 * This replaced LiveKitVoiceModal. The layout, visualizer and control bar are
 * unchanged — only the transport underneath is different. Turn detection,
 * barge-in and speech synthesis are all server side now, so this component is
 * mostly display: it renders whatever AssemblyAISession reports.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'

import { Radio, RefreshCw, X } from 'lucide-react'
import { toast } from 'sonner'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { useStore } from '@/store'
import { CLOSE, OPEN, type ToolPayload } from '@/lib/toolPayload'
import { BookingCard } from '../chat/ChatArea/Messages/tools/BookingCard'
import { DEFAULT_AGENT_NAME, VOICE_MODE_LABEL } from '@/lib/agentIdentity'

import { VoiceAgentControlBar } from './VoiceAgentControlBar'
import { VoiceVisualizer, type VoiceState } from './VoiceVisualizer'
import {
  AssemblyAISession,
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

export const AssemblyAIVoiceModal: React.FC<AssemblyAIVoiceModalProps> = ({
  isOpen,
  onClose,
  agentName = DEFAULT_AGENT_NAME
}) => {
  const { selectedEndpoint, setMessages } = useStore()

  const [state, setState] = useState<VoiceSessionState>('idle')
  const [turns, setTurns] = useState<Turn[]>([])
  const [isMuted, setIsMuted] = useState(false)

  const sessionRef = useRef<AssemblyAISession | null>(null)
  const transcriptEndRef = useRef<HTMLDivElement>(null)
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

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  // --- Session lifecycle --------------------------------------------------
  useEffect(() => {
    if (!isOpen) return

    const endpoint = selectedEndpoint || 'http://localhost:7777'
    const session = new AssemblyAISession({
      onStateChange: (next, message) => {
        setState(next)
        if (next === 'error' && message) toast.error(message)
      },
      onUserPartial: (text) => {
        if (!text.trim()) return
        setTurns((prev) => {
          const id = partialIdRef.current
          if (id) {
            return prev.map((t) => (t.id === id ? { ...t, text } : t))
          }
          const newId = nextId()
          partialIdRef.current = newId
          return [...prev, { id: newId, role: 'user', text, final: false }]
        })
      },
      onUserFinal: (text) => {
        const id = partialIdRef.current
        partialIdRef.current = null
        if (!text.trim()) {
          // Nothing was actually said — drop the placeholder rather than
          // leaving an empty bubble behind.
          if (id) setTurns((prev) => prev.filter((t) => t.id !== id))
          return
        }
        setTurns((prev) =>
          id
            ? prev.map((t) => (t.id === id ? { ...t, text, final: true } : t))
            : [...prev, { id: nextId(), role: 'user', text, final: true }]
        )
        appendToChat('user', text)
      },
      onAgentFinal: (text) => {
        if (!text.trim()) return
        setTurns((prev) => [
          ...prev,
          { id: nextId(), role: 'agent', text, final: true }
        ])
        appendToChat('agent', text)
      },
      onToolPayload: (payload) => {
        // Only the booking card renders in voice for now. A lead form here
        // would need the microphone to yield while someone types, which is a
        // separate interaction problem.
        if (payload.type !== 'booking') return
        let added = false
        setTurns((prev) => {
          // Asking to book twice in one session should not stack two
          // calendars; the card is a standing offer, not a running log.
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
        // Mirrored only when the modal actually showed one, so the written
        // transcript matches the session rather than gaining a second card.
        if (added) appendCardToChat('get_booking_link', payload)
      }
    })

    sessionRef.current = session
    void session.start(endpoint)

    return () => {
      session.end()
      sessionRef.current = null
      partialIdRef.current = null
    }
  }, [isOpen, selectedEndpoint, appendToChat, appendCardToChat])

  // Reset between sessions so a new conversation starts clean.
  useEffect(() => {
    if (!isOpen) {
      setTurns([])
      setState('idle')
      setIsMuted(false)
    }
  }, [isOpen])

  const toggleMute = () => {
    const session = sessionRef.current
    if (!session) return
    const next = !isMuted
    session.setMuted(next)
    setIsMuted(next)
  }

  const handleClose = () => {
    sessionRef.current?.end()
    onClose()
  }

  // The session's states map 1:1 onto the visualizer's, except 'connecting',
  // which the visualizer renders in its own way.
  const visualState: VoiceState =
    state === 'error' ? 'idle' : (state as VoiceState)

  const isConnecting = state === 'connecting'

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent
        hideCloseButton={true}
        className="max-h-[92vh] max-w-3xl overflow-hidden rounded-3xl border border-white/10 bg-[#0a0f1e] p-0 text-white shadow-2xl ring-1 ring-white/10 backdrop-blur-2xl sm:max-w-[780px] lg:max-w-[820px]"
      >
        <DialogHeader className="sr-only">
          <DialogTitle>Clyde — portfolio voice agent</DialogTitle>
          <DialogDescription>
            Interactive voice conversation session
          </DialogDescription>
        </DialogHeader>

        {isConnecting ? (
          <div className="flex h-[520px] flex-col items-center justify-center gap-4 bg-[#0a0f1e]">
            <RefreshCw className="size-8 animate-spin text-[#f48c06]" />
            <div className="font-mono text-sm font-medium text-zinc-300">
              Initializing Voice Session...
            </div>
          </div>
        ) : (
          <div className="flex h-[680px] max-h-[88vh] w-full flex-col justify-between bg-[#0a0f1e]">
            {/* Top Status Header */}
            <div className="flex items-center justify-between border-b border-white/10 bg-[#0a0f1e]/95 px-7 py-4 backdrop-blur-2xl">
              <div className="flex items-center gap-3">
                <span className="relative flex size-2.5">
                  <span className="size-full animate-ping rounded-full bg-sky-400 opacity-75" />
                  <span className="absolute inset-0 size-2.5 rounded-full bg-sky-500 shadow-[0_0_8px_#38bdf8]" />
                </span>
                <div className="flex items-center gap-2">
                  <Radio className="size-4 text-sky-400" />
                  <span className="font-mono text-xs font-medium text-zinc-200">
                    {VOICE_MODE_LABEL}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 font-mono text-[11px] text-zinc-300">
                  <span className="text-zinc-500">State:</span>
                  <span className="font-semibold uppercase text-sky-400">
                    {state}
                  </span>
                </div>

                <button
                  onClick={handleClose}
                  className="flex size-7 items-center justify-center rounded-full border border-white/10 bg-white/5 text-zinc-400 transition-all hover:border-white/20 hover:bg-white/10 hover:text-white active:scale-95"
                  title="Close Voice Assistant"
                >
                  <X className="size-3.5" />
                </button>
              </div>
            </div>

            {/* Visualizer Centerpiece */}
            <div className="relative flex flex-1 flex-col items-center justify-between overflow-hidden px-8 py-6">
              <div className="orb-fire pointer-events-none -right-24 -top-24 size-80 opacity-15" />

              <div className="flex shrink-0 flex-col items-center justify-center pt-2">
                <VoiceVisualizer
                  state={visualState}
                  barCount={15}
                  engineLabel="Live"
                />
              </div>

              {/* Live Transcript */}
              <div className="relative z-10 my-auto flex w-full max-w-xl flex-1 flex-col overflow-hidden px-2 py-2">
                {turns.length === 0 ? (
                  <div className="flex flex-1 items-center justify-center text-center">
                    <div className="rounded-2xl border border-white/5 bg-[#0f172a]/70 px-6 py-3.5 font-mono text-xs text-zinc-300 shadow-xl backdrop-blur-xl">
                      {state === 'speaking'
                        ? `${agentName} is responding...`
                        : state === 'thinking'
                          ? 'Thinking...'
                          : 'Speak naturally into your microphone...'}
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-1 flex-col gap-2.5 overflow-y-auto px-2 py-1">
                    {turns.map((turn) =>
                      turn.card?.type === 'booking' ? (
                        // Wider than a speech bubble and without its chrome:
                        // the card carries its own panel, and the calendar
                        // needs the room. Cal falls back to its mobile layout
                        // at this width, which is the right call in a modal.
                        <div key={turn.id} className="w-full">
                          <BookingCard payload={turn.card} priority />
                        </div>
                      ) : (
                        <div
                          key={turn.id}
                          className={`flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div
                            className={`max-w-[85%] rounded-2xl px-4 py-2 text-sm leading-relaxed shadow-lg backdrop-blur-xl ${
                              turn.role === 'user'
                                ? 'border border-sky-500/20 bg-sky-500/10 text-sky-50'
                                : 'border border-white/10 bg-[#0f172a]/80 text-zinc-100'
                            } ${turn.final ? '' : 'opacity-70'}`}
                          >
                            <span className="mb-0.5 block font-mono text-[10px] uppercase tracking-wide text-zinc-400">
                              {turn.role === 'user' ? 'You' : agentName}
                            </span>
                            {turn.text}
                          </div>
                        </div>
                      )
                    )}
                    <div ref={transcriptEndRef} />
                  </div>
                )}
              </div>

              <div className="h-2 shrink-0" />
            </div>

            {/* Control Bar */}
            <VoiceAgentControlBar
              isConnected={state !== 'idle' && state !== 'error'}
              isMuted={isMuted}
              onToggleMute={toggleMute}
              onDisconnect={handleClose}
              agentName={agentName}
              mode={VOICE_MODE_LABEL}
            />
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default AssemblyAIVoiceModal
