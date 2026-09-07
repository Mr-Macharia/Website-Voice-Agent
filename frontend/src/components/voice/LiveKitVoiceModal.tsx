'use client'

import React, { useState, useEffect, useRef } from 'react'
import {
  LiveKitRoom,
  RoomAudioRenderer,
  useVoiceAssistant,
  useLocalParticipant,
  useRoomContext
} from '@livekit/components-react'
import { Track } from 'livekit-client'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useStore } from '@/store'
import VoiceVisualizer, { VoiceState } from './VoiceVisualizer'
import VoiceAgentControlBar from './VoiceAgentControlBar'
import {
  RefreshCw,
  Send,
  Mic,
  Copy,
  Check,
  MessageSquare,
  X,
  Radio,
  Zap,
  Sparkles
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'

interface LiveKitVoiceModalProps {
  isOpen: boolean
  onClose: () => void
  agentName?: string
}

interface ConversationTurn {
  role: 'user' | 'agent'
  text: string
  timestamp: number
}

// Inner Component that lives inside <LiveKitRoom>
const LiveKitVoiceSession: React.FC<{
  onDisconnect: () => void
  agentName: string
}> = ({ onDisconnect, agentName }) => {
  const room = useRoomContext()
  const { localParticipant } = useLocalParticipant()
  const voiceAssistant = useVoiceAssistant()
  const [isMuted, setIsMuted] = useState(false)

  const getAgentState = (): VoiceState => {
    if (!voiceAssistant) return 'idle'
    if (voiceAssistant.state === 'speaking') return 'speaking'
    if (voiceAssistant.state === 'listening') return 'listening'
    if (voiceAssistant.state === 'thinking') return 'thinking'
    return 'idle'
  }

  const agentState = getAgentState()

  const toggleMute = async () => {
    if (!localParticipant) return
    try {
      const audioTrack = localParticipant.getTrackPublication(
        Track.Source.Microphone
      )
      if (audioTrack && audioTrack.track) {
        if (isMuted) {
          await audioTrack.track.unmute()
          setIsMuted(false)
        } else {
          await audioTrack.track.mute()
          setIsMuted(true)
        }
      }
    } catch (e) {
      console.error('Failed to toggle mute:', e)
    }
  }

  return (
    <div className="flex h-[680px] max-h-[88vh] w-full flex-col justify-between bg-[#0a0f1e]">
      <RoomAudioRenderer />

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
              LiveKit WebRTC
            </span>
            <span className="rounded-full border border-sky-500/20 bg-sky-500/10 px-2.5 py-0.5 font-mono text-[10px] text-sky-300">
              {room.name || 'voice-agent-room'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 font-mono text-[11px] text-zinc-300">
            <span className="text-zinc-500">State:</span>
            <span className="font-semibold uppercase text-sky-400">
              {agentState}
            </span>
          </div>

          <button
            onClick={onDisconnect}
            className="flex size-7 items-center justify-center rounded-full border border-white/10 bg-white/5 text-zinc-400 transition-all hover:border-white/20 hover:bg-white/10 hover:text-white active:scale-95"
            title="Close Voice Assistant"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      {/* Visualizer Centerpiece */}
      <div className="relative flex flex-1 flex-col items-center justify-between overflow-hidden px-8 py-6">
        {/* Ambient Glow */}
        <div className="orb-fire pointer-events-none -right-24 -top-24 size-80 opacity-15" />

        {/* 1. Visualizer Stage */}
        <div className="flex shrink-0 flex-col items-center justify-center pt-2">
          <VoiceVisualizer
            state={agentState}
            barCount={15}
            engineLabel="LiveKit Agent"
          />
        </div>

        {/* 2. Message / Status Feed */}
        <div className="relative z-10 my-auto flex w-full max-w-xl flex-1 items-center justify-center px-4 py-2 text-center">
          <div className="rounded-2xl border border-white/5 bg-[#0f172a]/70 px-6 py-3.5 font-mono text-xs text-zinc-300 shadow-xl backdrop-blur-xl">
            {agentState === 'speaking'
              ? `${agentName} is responding...`
              : agentState === 'thinking'
                ? 'LiveKit Agent processing...'
                : 'Speak naturally into your microphone...'}
          </div>
        </div>

        {/* 3. Spacer bottom */}
        <div className="h-2 shrink-0" />
      </div>

      {/* Control Bar */}
      <VoiceAgentControlBar
        isConnected={true}
        isMuted={isMuted}
        onToggleMute={toggleMute}
        onDisconnect={onDisconnect}
        agentName={agentName}
        mode="LiveKit WebRTC"
      />
    </div>
  )
}

// Streaming Voice Bridge Session (High-Speed Direct Agno + Deepgram Single WebSocket Streaming)
const DirectVoiceSession: React.FC<{
  onDisconnect: () => void
  agentName: string
}> = ({ onDisconnect, agentName }) => {
  const { selectedEndpoint, setMessages } = useStore()
  const [voiceState, setVoiceState] = useState<VoiceState>('connecting')
  const [isMuted, setIsMuted] = useState(false)
  const [micVolume, setMicVolume] = useState(0)
  const [userTranscript, setUserTranscript] = useState('')
  const [agentText, setAgentText] = useState('')
  const [quickInput, setQuickInput] = useState('')
  const [isPushToTalk, setIsPushToTalk] = useState(false)
  const [isManualRecording, setIsManualRecording] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [copied, setCopied] = useState(false)
  const [history, setHistory] = useState<ConversationTurn[]>([])
  const [statusMessage, setStatusMessage] = useState(
    'Connecting to Deepgram Voice Bridge...'
  )

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const gainNodeRef = useRef<GainNode | null>(null)
  const nextStartTimeRef = useRef(0)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const isSpeakingRef = useRef(false)
  const silenceTimerRef = useRef<NodeJS.Timeout | null>(null)
  const animFrameRef = useRef<number | null>(null)
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([])
  const isMutedRef = useRef(false)
  const isPushToTalkRef = useRef(false)
  const isAgentSpeakingRef = useRef(false)
  const currentUserTranscriptRef = useRef('')
  const currentAgentTextRef = useRef('')
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const voiceStateRef = useRef<VoiceState>('connecting')
  const sessionIdRef = useRef<string>('')
  // Jitter & confident-speech refs (Brave + 120ms buffer tuned)
  const isFirstChunkRef = useRef(true)
  const resumePromiseRef = useRef<Promise<void> | null>(null)
  const lastTurnCompleteRef = useRef(false)
  const consecutiveVoiceFramesRef = useRef(0)
  const consecutiveSilenceFramesRef = useRef(0)
  const bargeInCooldownRef = useRef(0)
  const vadHistoryRef = useRef<boolean[]>([])
  const turnIdRef = useRef(0)
  const turnActiveRef = useRef(false)
  const lastVadLogRef = useRef(0)
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const analyserNodeRef = useRef<AnalyserNode | null>(null)
  const zeroGainRef = useRef<GainNode | null>(null)

  useEffect(() => {
    isMutedRef.current = isMuted
  }, [isMuted])

  useEffect(() => {
    isPushToTalkRef.current = isPushToTalk
  }, [isPushToTalk])

  useEffect(() => {
    isAgentSpeakingRef.current =
      voiceState === 'speaking' || activeSourcesRef.current.length > 0
    voiceStateRef.current = voiceState
  }, [voiceState])

  // Generate/persist session_id for Agno memory (sent as session_id in WS JSON)
  useEffect(() => {
    if (!sessionIdRef.current) {
      let sid = ''
      try {
        sid = localStorage.getItem('voice-bridge-session-id') || ''
      } catch {}
      if (!sid) {
        sid = `voice-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
        try {
          localStorage.setItem('voice-bridge-session-id', sid)
        } catch {}
      }
      sessionIdRef.current = sid
    }
  }, [])

  const stopAudioPlayback = () => {
    const ctx = audioCtxRef.current
    const gain = gainNodeRef.current
    // Gentle fade to avoid click/pop on barge-in (Brave renders loud pops without ramp)
    if (gain && ctx && ctx.state !== 'closed') {
      try {
        const now = ctx.currentTime
        gain.gain.cancelScheduledValues(now)
        gain.gain.setValueAtTime(gain.gain.value, now)
        gain.gain.linearRampToValueAtTime(0, now + 0.04)
      } catch {}
    }
    // Delay stop by 40ms to let fade complete, else immediate
    const sources = [...activeSourcesRef.current]
    if (gain && ctx) {
      setTimeout(() => {
        sources.forEach((src) => {
          try {
            src.stop()
            src.disconnect()
          } catch {}
        })
        // Restore gain for next turn
        try {
          if (gain && ctx && ctx.state !== 'closed') {
            gain.gain.cancelScheduledValues(ctx.currentTime)
            gain.gain.setValueAtTime(1, ctx.currentTime)
          }
        } catch {}
      }, 40)
    } else {
      sources.forEach((src) => {
        try {
          src.stop()
          src.disconnect()
        } catch {}
      })
    }
    activeSourcesRef.current = []
    nextStartTimeRef.current = 0
    isFirstChunkRef.current = true
    lastTurnCompleteRef.current = false
    isAgentSpeakingRef.current = false
    // Only interrupt when a turn is active or TTS is actually playing (avoids cancelling turn 1 on PTT press 2)
    if (
      (turnActiveRef.current || activeSourcesRef.current.length > 0) &&
      wsRef.current &&
      wsRef.current.readyState === WebSocket.OPEN
    ) {
      try {
        wsRef.current.send(JSON.stringify({ type: 'Interrupt' }))
      } catch {}
    }
  }

  const sampleBufferRef = useRef<Float32Array[]>([])
  const isRecordingAudioRef = useRef(false)
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null)

  // Encode Float32 PCM samples to 16-bit Mono WAV format (100% supported by Deepgram Nova-3)
  const encodeWavBuffer = (
    samples: Float32Array,
    sampleRate: number = 16000
  ): ArrayBuffer => {
    const buffer = new ArrayBuffer(44 + samples.length * 2)
    const view = new DataView(buffer)

    const writeStr = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i))
      }
    }

    writeStr(0, 'RIFF')
    view.setUint32(4, 36 + samples.length * 2, true)
    writeStr(8, 'WAVE')
    writeStr(12, 'fmt ')
    view.setUint32(16, 16, true) // Subchunk1Size
    view.setUint16(20, 1, true) // Linear PCM
    view.setUint16(22, 1, true) // Mono (1 channel)
    view.setUint32(24, sampleRate, true) // Sample rate
    view.setUint32(28, sampleRate * 2, true) // Byte rate (SampleRate * 1 * 16/8)
    view.setUint16(32, 2, true) // Block align (1 * 16/8)
    view.setUint16(34, 16, true) // Bits per sample (16-bit)
    writeStr(36, 'data')
    view.setUint32(40, samples.length * 2, true)

    let offset = 44
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]))
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    }

    return buffer
  }

  const downsampleTo16k = (
    buffer: Float32Array,
    inputRate: number
  ): Float32Array => {
    if (inputRate === 16000) return buffer
    // Simple 2-tap low-pass before decimate to reduce aliasing (Brave + Flux quality)
    // Light smoothing: y[n] = 0.5*x[n] + 0.5*x[n-1]
    const filtered = new Float32Array(buffer.length)
    let prev = 0
    for (let i = 0; i < buffer.length; i++) {
      filtered[i] = 0.5 * buffer[i] + 0.5 * prev
      prev = buffer[i]
    }
    const ratio = inputRate / 16000
    const newLen = Math.round(filtered.length / ratio)
    const result = new Float32Array(newLen)
    let offsetResult = 0
    let offsetBuffer = 0
    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio)
      let accum = 0
      let count = 0
      for (
        let i = offsetBuffer;
        i < nextOffsetBuffer && i < filtered.length;
        i++
      ) {
        accum += filtered[i]
        count++
      }
      result[offsetResult] = count > 0 ? accum / count : 0
      offsetResult++
      offsetBuffer = nextOffsetBuffer
    }
    return result
  }

  const preRollBufferRef = useRef<Float32Array[]>([])
  const noiseFloorRef = useRef(0.015)
  const lastSpeechTimeRef = useRef(0)
  const speechStartTimeRef = useRef(0)
  // Tunables for confident speech (Brave + Never interrupt)
  const SILENCE_MS = 950
  const PRE_ROLL_MS = 180
  const CONFIDENT_VOICE_MS = 350
  const BARGE_COOLDOWN_MS = 800

  const startAudioRecording = () => {
    // Include the pre-roll buffer to preserve the first syllable
    sampleBufferRef.current = [...preRollBufferRef.current]
    isRecordingAudioRef.current = true
    speechStartTimeRef.current = Date.now()
  }

  const stopAudioRecordingAndSend = () => {
    if (!isRecordingAudioRef.current && sampleBufferRef.current.length === 0)
      return
    isSpeakingRef.current = false
    isRecordingAudioRef.current = false
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }

    const chunks = sampleBufferRef.current
    sampleBufferRef.current = []

    if (!chunks || chunks.length === 0) return

    // Merge Float32Array chunks
    let totalLen = 0
    for (const c of chunks) totalLen += c.length

    const merged = new Float32Array(totalLen)
    let curOffset = 0
    for (const c of chunks) {
      merged.set(c, curOffset)
      curOffset += c.length
    }

    // Detect actual capture rate: prefer MediaStreamTrack settings (Brave may ignore AudioContext constraint), fallback to AudioContext
    let currentRate = audioCtxRef.current?.sampleRate || 48000
    try {
      const track = mediaStreamRef.current?.getAudioTracks()?.[0]
      const settings = track?.getSettings?.() as MediaTrackSettings & {
        sampleRate?: number
      }
      if (
        settings?.sampleRate &&
        settings.sampleRate >= 8000 &&
        settings.sampleRate <= 48000
      ) {
        currentRate = settings.sampleRate
      }
    } catch {}
    const downsampled = downsampleTo16k(merged, currentRate)
    const wavBuffer = encodeWavBuffer(downsampled, 16000)

    // Keep 50ms floor (800 samples @16k) so "yes"/"no" not dropped, but confident turns <400ms still filtered if silence-triggered
    if (downsampled.length < 800) {
      console.debug(`[VAD] Dropped sub-floor turn (${downsampled.length} samples)`)
      return
    }
    // If total speech <400ms (6400 samples) and triggered by silence, likely false trigger — keep but log
    const totalMs = (downsampled.length / 16000) * 1000
    if (totalMs < 400) {
      console.debug(
        `[VAD] Short turn ${totalMs.toFixed(0)}ms — still sending (confident check passed)`
      )
    }
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      turnIdRef.current += 1
      turnActiveRef.current = true
      setVoiceState('thinking')
      setStatusMessage('Processing speech (Deepgram Flux)...')
      setAgentText('')
      currentAgentTextRef.current = ''
      // Reset jitter first-chunk flag for next TTS turn
      isFirstChunkRef.current = true
      lastTurnCompleteRef.current = false

      try {
        wsRef.current.send(wavBuffer)
      } catch (err) {
        console.error('Failed to send WAV buffer:', err)
        setVoiceState('listening')
        turnActiveRef.current = false
      }
    } else {
      toast.error('Voice connection lost — reconnecting')
      setVoiceState('listening')
      setStatusMessage('Connection lost. Reopen the voice dialog to reconnect.')
    }
  }

  // Setup WebSocket and Audio
  useEffect(() => {
    let isMounted = true

    try {
      const AudioContextClass =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext
      // Try 48000 to match Deepgram Settings input 48000, but fallback gracefully for Brave/Safari
      try {
        audioCtxRef.current = new AudioContextClass({
          sampleRate: 48000
        } as AudioContextOptions)
      } catch {
        audioCtxRef.current = new AudioContextClass()
      }
      if (audioCtxRef.current.sampleRate !== 48000) {
        console.warn(
          `AudioContext sampleRate ${audioCtxRef.current.sampleRate} != 48000 (Settings input), will downsample correctly`
        )
      }
      // Create a master gain node for TTS playback (allows fade on barge-in, 120ms jitter buffer)
      try {
        gainNodeRef.current = audioCtxRef.current.createGain()
        gainNodeRef.current.gain.value = 1
        gainNodeRef.current.connect(audioCtxRef.current.destination)
      } catch {}
    } catch (err) {
      console.warn('AudioContext initialization error:', err)
    }

    const endpoint = (selectedEndpoint || 'http://localhost:7777').replace(
      /\/+$/,
      ''
    )
    const wsUrl = endpoint.replace(/^http/, 'ws') + '/ws/voice'
    const ws = new WebSocket(wsUrl)
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    ws.onopen = () => {
      if (!isMounted) return
      setVoiceState('listening')
      setStatusMessage('Voice Bridge Active • Speak naturally')
      toast.success('Connected to Deepgram Voice Bridge')
    }

    ws.onmessage = async (event) => {
      if (!isMounted) return

      // Handle Blob fallback (some proxies deliver Blob even with binaryType arraybuffer)
      let data = event.data
      if (data instanceof Blob) {
        try {
          data = await data.arrayBuffer()
        } catch {
          return
        }
      }

      if (typeof data === 'string') {
        try {
          const parsed = JSON.parse(data)
          if (parsed.type === 'user_transcript') {
            setUserTranscript(parsed.text)
            currentUserTranscriptRef.current = parsed.text
            setStatusMessage(`You: "${parsed.text}"`)
          } else if (parsed.type === 'agent_text') {
            setVoiceState('speaking')
            setAgentText((prev) => prev + parsed.text)
            currentAgentTextRef.current += parsed.text
            setStatusMessage(`${agentName} is responding...`)
          } else if (
            parsed.type === 'turn_complete' ||
            parsed.type === 'interrupted'
          ) {
            const uText = currentUserTranscriptRef.current
            const aText = currentAgentTextRef.current

            if (uText && aText) {
              const now = Date.now()
              setHistory((prev) => [
                ...prev,
                { role: 'user', text: uText, timestamp: now - 1000 },
                { role: 'agent', text: aText, timestamp: now }
              ])

              setMessages((prev) => [
                ...prev,
                {
                  role: 'user',
                  content: uText,
                  created_at: now - 1000
                },
                {
                  role: 'agent',
                  content: aText,
                  created_at: now
                }
              ])
            }

            lastTurnCompleteRef.current = true
            turnActiveRef.current = false
            const completedTurnId = turnIdRef.current
            // Wait for jitter buffer to drain: poll until empty, but ignore if new turn started
            const checkDone = () => {
              if (!isMounted) return
              // If a new turn started, abort this check (new audio will manage state)
              if (turnIdRef.current !== completedTurnId) return
              if (activeSourcesRef.current.length === 0) {
                setVoiceState('listening')
                setStatusMessage('Listening for your voice...')
                isAgentSpeakingRef.current = false
                lastTurnCompleteRef.current = false
                isFirstChunkRef.current = true
              } else {
                setTimeout(checkDone, 80)
              }
            }
            // Brave 120ms buffer: wait a bit longer than before to let jitter drain
            setTimeout(checkDone, 180)
          } else if (parsed.type === 'no_speech') {
            turnActiveRef.current = false
            setVoiceState('listening')
          } else if (parsed.type === 'error') {
            toast.error(parsed.message || 'Voice Turn Error')
          }
        } catch {}
      } else if (data instanceof ArrayBuffer && audioCtxRef.current) {
        setVoiceState('speaking')
        isAgentSpeakingRef.current = true
        playPcmChunk(data)
      }
    }

    // The `error` event on a WebSocket is deliberately opaque (a bare Event with
    // no cause, for cross-origin safety), so it can only report *that* the socket
    // failed. The actionable detail arrives on `close` as the code/reason.
    let didError = false

    ws.onerror = () => {
      didError = true
      console.error(`Voice WS error: failed to connect to ${wsUrl}`)
      if (isMounted) {
        setVoiceState('error')
        setStatusMessage('Voice Bridge Connection Error')
      }
    }

    ws.onclose = (event) => {
      // 1006 = abnormal closure: never completed a handshake. Almost always the
      // backend not running/reachable at `endpoint`, or a wrong persisted endpoint.
      const neverConnected = didError || event.code === 1006
      if (neverConnected) {
        console.error(
          `Voice WS closed without connecting to ${wsUrl} ` +
            `(code ${event.code}${event.reason ? `, reason: ${event.reason}` : ', no reason given'}). ` +
            `Check that the voice backend is running and reachable at ${endpoint}.`
        )
      }
      if (isMounted) {
        setVoiceState(neverConnected ? 'error' : 'idle')
        setStatusMessage(
          neverConnected
            ? `Cannot reach voice backend at ${endpoint}`
            : 'Voice Bridge Disconnected'
        )
      }
    }

    // Initialize Microphone capture with adaptive RMS VAD & pre-roll — Brave + confident speech tuned
    // Uses AudioWorklet when available (off main thread, no glitches), fallback to ScriptProcessor
    const handleAudioChunk = (inputData: Float32Array) => {
      if (!isMounted || isMutedRef.current) {
        return
      }
      const chunkCopy = new Float32Array(inputData)

      // 1. Maintain ~180ms circular pre-roll buffer — dynamic size based on actual chunk duration (Brave 2.66ms @128 vs 42ms @2048)
      const ctxRate = audioCtxRef.current?.sampleRate || 48000
      const chunkMs = (inputData.length / ctxRate) * 1000
      const maxPreRoll = Math.max(
        4,
        Math.ceil(PRE_ROLL_MS / Math.max(1, chunkMs))
      )
      preRollBufferRef.current.push(chunkCopy)
      if (preRollBufferRef.current.length > maxPreRoll) {
        preRollBufferRef.current.shift()
      }

      // 2. High-precision RMS Calculation
      let sumSq = 0
      for (let i = 0; i < inputData.length; i++) {
        sumSq += inputData[i] * inputData[i]
      }
      const rms = Math.sqrt(sumSq / inputData.length)

      // Dynamic noise floor tracking (adapts to ambient, Brave lower floor)
      noiseFloorRef.current = Math.min(
        noiseFloorRef.current * 0.98 + rms * 0.02,
        0.035
      )
      const speechThreshold = Math.max(0.032, noiseFloorRef.current * 3.0)
      const isVoiceActiveRaw = rms > speechThreshold

      // Majority-vote smoothing over last 12 frames (~32ms Worklet / 500ms ScriptProcessor) — confident speech only
      vadHistoryRef.current.push(isVoiceActiveRaw)
      if (vadHistoryRef.current.length > 12) vadHistoryRef.current.shift()
      const voicedCount = vadHistoryRef.current.filter(Boolean).length
      const isVoiceActive = voicedCount >= 7 // 7/12 majority
      try {
        if (
          typeof localStorage !== 'undefined' &&
          localStorage.getItem('voice-vad-debug') &&
          Date.now() - lastVadLogRef.current > 1000
        ) {
          lastVadLogRef.current = Date.now()
          console.debug(
            `[VAD] rms=${rms.toFixed(4)} threshold=${speechThreshold.toFixed(4)} voiced=${voicedCount}/12 recording=${isRecordingAudioRef.current}`
          )
        }
      } catch {}

      if (!isPushToTalkRef.current) {
        const now = Date.now()

        if (isVoiceActive) {
          consecutiveVoiceFramesRef.current += 1
          consecutiveSilenceFramesRef.current = 0
          // Debounced barge-in: require confident voice (350ms continuous + cooldown) to cancel TTS (Never interrupt)
          const neededFrames = Math.max(
            3,
            Math.ceil(CONFIDENT_VOICE_MS / Math.max(1, chunkMs))
          )
          if (
            isAgentSpeakingRef.current &&
            consecutiveVoiceFramesRef.current >= neededFrames &&
            now - bargeInCooldownRef.current > BARGE_COOLDOWN_MS
          ) {
            bargeInCooldownRef.current = now
            stopAudioPlayback()
          }

          if (!isRecordingAudioRef.current) {
            // Require confident start: at least 80ms of voice before opening turn (avoid breath pop)
            if (
              consecutiveVoiceFramesRef.current >=
              Math.ceil(80 / Math.max(1, chunkMs))
            ) {
              isSpeakingRef.current = true
              startAudioRecording()
              setStatusMessage('Heard you — recording...')
            } else {
              // Still buffering pre-roll, not yet recording
              return
            }
          }

          sampleBufferRef.current.push(chunkCopy)
          lastSpeechTimeRef.current = now
        } else if (isRecordingAudioRef.current) {
          consecutiveSilenceFramesRef.current += 1
          consecutiveVoiceFramesRef.current = 0
          sampleBufferRef.current.push(chunkCopy)

          const silenceDuration = now - lastSpeechTimeRef.current
          const totalDuration = now - speechStartTimeRef.current

          if (silenceDuration > SILENCE_MS || totalDuration > 15000) {
            // Reset confident counters on send
            consecutiveVoiceFramesRef.current = 0
            consecutiveSilenceFramesRef.current = 0
            vadHistoryRef.current = []
            stopAudioRecordingAndSend()
          }
        } else {
          // Not recording, decay voice frames
          consecutiveVoiceFramesRef.current = Math.max(
            0,
            consecutiveVoiceFramesRef.current - 1
          )
        }
      } else if (isRecordingAudioRef.current) {
        sampleBufferRef.current.push(chunkCopy)
      }
    }

    const initMic = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
            sampleRate: 48000
          } as MediaTrackConstraints
        })
        if (!isMounted) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        mediaStreamRef.current = stream

        if (audioCtxRef.current) {
          const ctx = audioCtxRef.current
          if (ctx.state === 'suspended') {
            try {
              await ctx.resume()
            } catch {}
          }
          const source = ctx.createMediaStreamSource(stream)
          sourceNodeRef.current = source
          const analyser = ctx.createAnalyser()
          analyserNodeRef.current = analyser
          analyser.fftSize = 256
          analyser.smoothingTimeConstant = 0.3

          // Try AudioWorklet (off main thread) first, fallback to ScriptProcessor
          let workletNode: AudioWorkletNode | null = null
          const zeroGain = ctx.createGain()
          zeroGain.gain.value = 0
          zeroGainRef.current = zeroGain

          const setupAnalyserLoop = () => {
            const dataArray = new Uint8Array(analyser.frequencyBinCount)
            const checkAudioLevel = () => {
              if (!isMounted) return
              analyser.getByteFrequencyData(dataArray)
              let sum = 0
              for (let i = 0; i < dataArray.length; i++) {
                sum += dataArray[i]
              }
              const avg = sum / dataArray.length
              const normalizedVol = Math.min(1, (avg / 128) * 1.5)
              setMicVolume(normalizedVol)
              animFrameRef.current = requestAnimationFrame(checkAudioLevel)
            }
            animFrameRef.current = requestAnimationFrame(checkAudioLevel)
          }

          try {
            if (ctx.audioWorklet) {
              await ctx.audioWorklet.addModule('/worklets/vad-processor.js')
              workletNode = new AudioWorkletNode(ctx, 'vad-processor')
              workletNodeRef.current = workletNode
              workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
                handleAudioChunk(e.data)
              }
              source.connect(analyser)
              source.connect(workletNode)
              workletNode.connect(zeroGain)
              zeroGain.connect(ctx.destination)
              // Also connect analyser for volume visualization already done via source->analyser
              setupAnalyserLoop()
            } else {
              throw new Error('AudioWorklet not supported')
            }
          } catch (e) {
            console.warn(
              'AudioWorklet unavailable, falling back to ScriptProcessor:',
              e
            )
            const processor = ctx.createScriptProcessor(2048, 1, 1)
            scriptProcessorRef.current = processor
            processor.onaudioprocess = (ev) => {
              const inputData = ev.inputBuffer.getChannelData(0)
              handleAudioChunk(new Float32Array(inputData))
            }
            source.connect(analyser)
            source.connect(processor)
            processor.connect(zeroGain)
            zeroGain.connect(ctx.destination)
            setupAnalyserLoop()
          }
        }
      } catch (err) {
        console.error('Microphone access error:', err)
        toast.error('Microphone permission required for voice interaction.')
        setStatusMessage('Microphone access denied. You can still type below.')
      }
    }
    void initMic()
    return () => {
      isMounted = false
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (ws.readyState === WebSocket.OPEN) ws.close()
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop())
      }
      if (scriptProcessorRef.current) {
        try {
          scriptProcessorRef.current.disconnect()
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          ;(scriptProcessorRef.current.onaudioprocess as any) = null
        } catch {}
        scriptProcessorRef.current = null
      }
      if (workletNodeRef.current) {
        try {
          workletNodeRef.current.disconnect()
          workletNodeRef.current.port.onmessage = null
        } catch {}
        workletNodeRef.current = null
      }
      try {
        sourceNodeRef.current?.disconnect()
      } catch {}
      try {
        analyserNodeRef.current?.disconnect()
      } catch {}
      try {
        zeroGainRef.current?.disconnect()
      } catch {}
      sourceNodeRef.current = null
      analyserNodeRef.current = null
      zeroGainRef.current = null
      stopAudioPlayback()
      if (audioCtxRef.current) {
        try {
          if (audioCtxRef.current.state !== 'closed') {
            audioCtxRef.current.close().catch(() => {})
          }
        } catch {}
      }
      audioCtxRef.current = null
      gainNodeRef.current = null
      mediaStreamRef.current = null
      wsRef.current = null
      sampleBufferRef.current = []
      preRollBufferRef.current = []
      vadHistoryRef.current = []
      noiseFloorRef.current = 0.015
      consecutiveVoiceFramesRef.current = 0
      consecutiveSilenceFramesRef.current = 0
      isRecordingAudioRef.current = false
      isSpeakingRef.current = false
      nextStartTimeRef.current = 0
      resumePromiseRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEndpoint, agentName, setMessages])

  // Seamless Jitter-Free PCM Audio Playback — Brave-tuned 120ms buffer + serialized resume
  const playPcmChunk = async (arrayBuffer: ArrayBuffer) => {
    if (!audioCtxRef.current) return
    const ctx = audioCtxRef.current
    if (ctx.state === 'suspended') {
      if (!resumePromiseRef.current) {
        resumePromiseRef.current = ctx
          .resume()
          .catch(() => {})
          .finally(() => {
            resumePromiseRef.current = null
          })
      }
      try {
        await resumePromiseRef.current
      } catch {}
    }
    if (ctx.state === 'closed' || !audioCtxRef.current) return

    // Ensure gain is live for post-interrupt audio (cancel fade-out ramp)
    if (gainNodeRef.current) {
      try {
        gainNodeRef.current.gain.cancelScheduledValues(ctx.currentTime)
        gainNodeRef.current.gain.setValueAtTime(1, ctx.currentTime)
      } catch {}
    }

    // Ensure 16-bit 2-byte alignment + drop tiny glitch frames (<20ms @24k = 960 bytes)
    const byteLen = arrayBuffer.byteLength - (arrayBuffer.byteLength % 2)
    if (byteLen <= 0 || byteLen < 960) return

    const int16Array = new Int16Array(arrayBuffer, 0, byteLen / 2)
    const float32Array = new Float32Array(int16Array.length)
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0
    }

    // 24kHz Deepgram Flux TTS Buffer (matches Settings output 24000)
    const audioBuffer = ctx.createBuffer(1, float32Array.length, 24000)
    audioBuffer.getChannelData(0).set(float32Array)

    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    if (gainNodeRef.current) {
      source.connect(gainNodeRef.current)
    } else {
      source.connect(ctx.destination)
    }

    // 120ms jitter buffer: first chunk of a turn starts 120ms in future to absorb network variance
    const currentTime = ctx.currentTime
    if (isFirstChunkRef.current) {
      nextStartTimeRef.current = currentTime + 0.12
      isFirstChunkRef.current = false
    }
    const startTime = Math.max(currentTime + 0.02, nextStartTimeRef.current)
    try {
      source.start(startTime)
    } catch {
      // Fallback: try immediate
      try {
        source.start()
      } catch {
        return
      }
    }
    nextStartTimeRef.current = startTime + audioBuffer.duration

    activeSourcesRef.current.push(source)
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter(
        (s) => s !== source
      )
      try {
        source.disconnect()
      } catch {}
      const stillSpeaking = activeSourcesRef.current.length > 0
      if (!stillSpeaking) {
        if (lastTurnCompleteRef.current) {
          // Turn already signaled complete — drain finished, go listening
          lastTurnCompleteRef.current = false
          isFirstChunkRef.current = true
          isAgentSpeakingRef.current = false
          // voiceState transition handled by ws handler, but ensure not stuck speaking
          if (voiceStateRef.current === 'speaking') {
            // Let ws handler manage, but fallback:
            // setVoiceState handled via polling; keep flag consistent
          }
        } else if (voiceStateRef.current !== 'speaking') {
          isAgentSpeakingRef.current = false
        }
      }
    }
  }

  const handleSendPrompt = async (text: string) => {
    if (
      !text.trim() ||
      !wsRef.current ||
      wsRef.current.readyState !== WebSocket.OPEN
    )
      return
    if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
      await audioCtxRef.current.resume()
    }
    stopAudioPlayback()
    turnIdRef.current += 1
    turnActiveRef.current = true
    isFirstChunkRef.current = true
    lastTurnCompleteRef.current = false
    setUserTranscript(text.trim())
    currentUserTranscriptRef.current = text.trim()
    setVoiceState('thinking')
    setStatusMessage('Processing text prompt...')
    setAgentText('')
    currentAgentTextRef.current = ''
    wsRef.current.send(
      JSON.stringify({ text: text.trim(), session_id: sessionIdRef.current })
    )
    setQuickInput('')
  }

  const handleManualPushToTalkStart = () => {
    if (isMuted) return
    if (isRecordingAudioRef.current) return
    stopAudioPlayback()
    setIsManualRecording(true)
    startAudioRecording()
  }

  const handleManualPushToTalkEnd = () => {
    setIsManualRecording(false)
    if (!isRecordingAudioRef.current && sampleBufferRef.current.length === 0)
      return
    stopAudioRecordingAndSend()
  }

  const copyTranscriptText = () => {
    if (history.length === 0) {
      toast.info('No conversation turns yet')
      return
    }
    const formatted = history
      .map((h) => `${h.role === 'user' ? 'You' : agentName}: ${h.text}`)
      .join('\n\n')
    navigator.clipboard.writeText(formatted)
    setCopied(true)
    toast.success('Conversation transcript copied to clipboard!')
    setTimeout(() => setCopied(false), 2000)
  }

  const unlockAudio = async () => {
    if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
      try {
        await audioCtxRef.current.resume()
      } catch {}
    }
  }

  return (
    <div
      onClick={unlockAudio}
      className="flex h-[680px] max-h-[88vh] w-full flex-col justify-between bg-[#0a0f1e]"
    >
      {/* Top Status Header */}
      <div className="flex items-center justify-between border-b border-white/10 bg-[#0a0f1e]/95 px-7 py-4 backdrop-blur-2xl">
        <div className="flex items-center gap-3">
          <span className="relative flex size-2.5">
            <span className="size-full animate-ping rounded-full bg-[#f48c06] opacity-75" />
            <span className="absolute inset-0 size-2.5 rounded-full bg-[#f48c06] shadow-[0_0_8px_#f48c06]" />
          </span>
          <div className="flex items-center gap-2">
            <Zap className="size-4 text-[#f48c06]" />
            <span className="font-mono text-xs font-medium text-zinc-200">
              Deepgram Voice Bridge
            </span>
            <span className="rounded-full border border-[#f48c06]/20 bg-[#f48c06]/10 px-2.5 py-0.5 font-mono text-[10px] text-[#faa307]">
              Nova-3 STT • Flux TTS
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`flex items-center gap-1.5 rounded-full border px-3 py-1.5 font-mono text-[11px] transition-all ${
              showHistory
                ? 'border-[#e85d04]/50 bg-[#e85d04]/20 text-[#f48c06]'
                : 'border-white/10 bg-white/5 text-zinc-400 hover:border-white/20 hover:text-zinc-200'
            }`}
            title="Toggle full conversation transcript"
          >
            <MessageSquare className="size-3.5" />
            <span>Transcript ({(history.length / 2) | 0})</span>
          </button>

          <button
            onClick={() => setIsPushToTalk(!isPushToTalk)}
            className={`rounded-full border px-3 py-1.5 font-mono text-[11px] transition-all ${
              isPushToTalk
                ? 'border-amber-500/40 bg-amber-500/20 text-amber-300'
                : 'border-white/10 bg-white/5 text-zinc-400 hover:border-white/20 hover:text-zinc-200'
            }`}
            title={
              isPushToTalk
                ? 'Switch to Hands-free VAD'
                : 'Switch to Push-To-Talk'
            }
          >
            {isPushToTalk ? 'Push-To-Talk' : 'Fast VAD'}
          </button>

          <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 font-mono text-[11px] text-zinc-300">
            <span className="text-zinc-500">State:</span>
            <span className="font-semibold uppercase text-[#f48c06]">
              {voiceState}
            </span>
          </div>

          <button
            onClick={onDisconnect}
            className="flex size-7 items-center justify-center rounded-full border border-white/10 bg-white/5 text-zinc-400 transition-all hover:border-white/20 hover:bg-white/10 hover:text-white active:scale-95"
            title="Close Voice Assistant"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      {showHistory ? (
        /* Full Transcript View */
        <div className="flex flex-1 flex-col overflow-hidden bg-[#0a0f1e]/90 p-7">
          <div className="mb-4 flex items-center justify-between">
            <h4 className="font-mono text-xs uppercase tracking-wider text-zinc-400">
              Saved Conversation Turns ({(history.length / 2) | 0})
            </h4>
            <Button
              variant="outline"
              size="sm"
              onClick={copyTranscriptText}
              className="h-8 gap-1.5 rounded-xl border-white/10 bg-white/5 px-3 text-xs text-zinc-300 transition-all hover:border-[#e85d04]/40 hover:bg-[#e85d04]/20 hover:text-white"
            >
              {copied ? (
                <Check className="size-3.5 text-[#22c55e]" />
              ) : (
                <Copy className="size-3.5" />
              )}
              {copied ? 'Copied' : 'Copy All'}
            </Button>
          </div>
          <div className="flex-1 space-y-3.5 overflow-y-auto rounded-2xl border border-white/5 bg-[#0f172a]/60 p-5 pr-3">
            {history.length === 0 ? (
              <div className="py-16 text-center font-mono text-xs italic text-zinc-500">
                No spoken turns yet. Speak or type to start recording the
                conversation.
              </div>
            ) : (
              history.map((turn, i) => (
                <div
                  key={i}
                  className={`rounded-2xl p-3.5 text-xs ${
                    turn.role === 'user'
                      ? 'ml-8 border border-sky-500/20 bg-sky-950/20 text-zinc-200'
                      : 'mr-8 border border-[#e85d04]/30 bg-[#e85d04]/10 text-zinc-100'
                  }`}
                >
                  <div className="mb-1.5 font-mono text-[10px] uppercase text-zinc-400">
                    {turn.role === 'user' ? 'You' : agentName}
                  </div>
                  <div className="font-main text-sm leading-relaxed">
                    {turn.text}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      ) : (
        /* Visualizer Centerpiece */
        <div className="relative flex flex-1 flex-col items-center justify-between overflow-hidden bg-[#0a0f1e]/90 px-8 py-6">
          {/* Subtle background glow */}
          <div className="orb-orange pointer-events-none -right-24 -top-24 size-80 opacity-20" />

          {/* 1. Visualizer Stage */}
          <div className="flex shrink-0 flex-col items-center justify-center pt-1">
            <VoiceVisualizer
              state={voiceState}
              volume={voiceState === 'speaking' ? 0.65 : micVolume}
              barCount={15}
              engineLabel="Deepgram Flux"
            />
          </div>

          {/* 2. Live Conversation Transcript Feed */}
          <div className="relative z-10 my-auto flex w-full max-w-xl flex-1 items-center justify-center py-2">
            <AnimatePresence mode="wait">
              {agentText ? (
                <motion.div
                  key="agent-text"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="max-h-36 w-full overflow-y-auto rounded-2xl border border-[#e85d04]/30 bg-[#0f172a]/95 p-4 text-xs text-zinc-100 shadow-2xl shadow-orange-950/30 backdrop-blur-xl"
                >
                  <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase text-[#f48c06]">
                    <span className="flex items-center gap-1.5">
                      <Sparkles className="size-3" />
                      {agentName}
                    </span>
                    <span className="rounded-full bg-[#e85d04]/10 px-2 py-0.5 text-[9px] font-semibold text-[#faa307]">
                      Speaking
                    </span>
                  </div>
                  <div className="font-main text-sm leading-relaxed text-zinc-100">
                    {agentText}
                  </div>
                </motion.div>
              ) : userTranscript ? (
                <motion.div
                  key="user-text"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="max-h-36 w-full overflow-y-auto rounded-2xl border border-sky-500/30 bg-[#0f172a]/95 p-4 text-xs text-zinc-100 shadow-2xl shadow-sky-950/30 backdrop-blur-xl"
                >
                  <div className="mb-2 flex items-center justify-between font-mono text-[10px] uppercase text-sky-400">
                    <span className="flex items-center gap-1.5">
                      <Mic className="size-3" />
                      You
                    </span>
                    <span className="rounded-full bg-sky-500/10 px-2 py-0.5 text-[9px] font-semibold text-sky-300">
                      Spoken
                    </span>
                  </div>
                  <div className="font-main text-sm leading-relaxed text-zinc-100">
                    {userTranscript}
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key="status-msg"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="rounded-2xl border border-white/5 bg-[#0f172a]/60 px-6 py-3 font-mono text-xs text-zinc-400 backdrop-blur-xl"
                >
                  {statusMessage}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* 3. Bottom Controls & Mic Feedback */}
          <div className="relative z-10 flex w-full max-w-xl shrink-0 flex-col items-center gap-3">
            {/* Live Mic Level Feedback Indicator */}
            <div className="flex items-center gap-3 rounded-full border border-white/10 bg-[#0f172a]/80 px-4 py-1.5 font-mono text-[11px] text-zinc-400 shadow-md backdrop-blur-xl">
              <Mic
                className={`size-3.5 transition-colors ${
                  micVolume > 0.018
                    ? 'animate-pulse text-emerald-400'
                    : 'text-zinc-500'
                }`}
              />
              <span className="text-[10px] text-zinc-400">Mic Level</span>
              <div className="h-1.5 w-32 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full bg-gradient-to-r from-emerald-400 via-amber-400 to-[#e85d04] transition-all duration-75"
                  style={{
                    width: `${Math.min(100, Math.max(4, micVolume * 100))}%`
                  }}
                />
              </div>
              <span
                className={`text-[10px] font-medium transition-colors ${
                  micVolume > 0.018 ? 'text-emerald-400' : 'text-zinc-500'
                }`}
              >
                {micVolume > 0.018 ? 'Voice Active' : 'Ready'}
              </span>
            </div>

            {/* Push to talk hold button or text input */}
            {isPushToTalk ? (
              <div className="flex w-full max-w-sm justify-center">
                <button
                  onPointerDown={(e) => {
                    e.currentTarget.setPointerCapture(e.pointerId)
                    handleManualPushToTalkStart()
                  }}
                  onPointerUp={handleManualPushToTalkEnd}
                  onPointerCancel={handleManualPushToTalkEnd}
                  onLostPointerCapture={() => {
                    if (isRecordingAudioRef.current) handleManualPushToTalkEnd()
                  }}
                  onContextMenu={(e) => e.preventDefault()}
                  className={`relative flex touch-none select-none items-center gap-2 rounded-full px-9 py-3 font-mono text-xs font-semibold text-white shadow-xl transition-all ${
                    isManualRecording
                      ? 'scale-95 bg-rose-600 shadow-rose-950/60 ring-4 ring-rose-500/40'
                      : 'bg-gradient-to-tr from-[#e85d04] to-[#f48c06] shadow-orange-950/50 hover:brightness-110 active:scale-95'
                  }`}
                >
                  <Mic className="size-4" />
                  <span>
                    {isManualRecording ? 'Release to Send' : 'Hold to Speak'}
                  </span>
                </button>
              </div>
            ) : (
              <div className="flex w-full items-center gap-2 px-2">
                <input
                  type="text"
                  placeholder="Ask with voice or type message..."
                  value={quickInput}
                  onChange={(e) => setQuickInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSendPrompt(quickInput)
                  }}
                  className="h-11 w-full rounded-2xl border border-white/10 bg-[#0f172a]/90 px-4 text-xs text-white backdrop-blur-xl placeholder:text-zinc-500 focus:border-[#e85d04]/60 focus:outline-none"
                />
                <Button
                  size="icon"
                  onClick={() => handleSendPrompt(quickInput)}
                  disabled={!quickInput.trim()}
                  className="size-11 shrink-0 rounded-2xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] text-white shadow-md shadow-orange-950/50 hover:brightness-110 disabled:opacity-40"
                >
                  <Send className="size-4" />
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Control Bar */}
      <VoiceAgentControlBar
        isConnected={voiceState !== 'error'}
        isMuted={isMuted}
        onToggleMute={() => setIsMuted(!isMuted)}
        onDisconnect={onDisconnect}
        agentName={agentName}
        mode="Deepgram Flux TTS"
      />
    </div>
  )
}

export const LiveKitVoiceModal: React.FC<LiveKitVoiceModalProps> = ({
  isOpen,
  onClose,
  agentName = 'Realtime Voice Assistant'
}) => {
  const [token, setToken] = useState<string>('')
  const [wsUrl, setWsUrl] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)
  const [useFallbackMode, setUseFallbackMode] = useState(true)
  const { selectedEndpoint } = useStore()

  useEffect(() => {
    if (!isOpen) {
      setToken('')
      return
    }

    const fetchToken = async () => {
      setIsLoading(true)

      try {
        let res = await fetch('/api/livekit/token?room=voice-agent-room')
        if (!res.ok) {
          res = await fetch(
            `${selectedEndpoint}/api/livekit/token?room=voice-agent-room`
          )
        }

        if (res.ok) {
          const data = await res.json()
          if (
            data.token &&
            data.url &&
            !data.url.includes('placeholder') &&
            process.env.NEXT_PUBLIC_LIVEKIT_URL
          ) {
            setToken(data.token)
            setWsUrl(data.url)
            setUseFallbackMode(false)
            setIsLoading(false)
            return
          }
        }

        // Default to direct streaming bridge if LiveKit Cloud URL isn't configured in env
        setUseFallbackMode(true)
      } catch (err) {
        console.warn('LiveKit token fetch using voice bridge:', err)
        setUseFallbackMode(true)
      } finally {
        setIsLoading(false)
      }
    }

    fetchToken()
  }, [isOpen, selectedEndpoint])

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        hideCloseButton={true}
        className="max-h-[92vh] max-w-3xl overflow-hidden rounded-3xl border border-white/10 bg-[#0a0f1e] p-0 text-white shadow-2xl ring-1 ring-white/10 backdrop-blur-2xl sm:max-w-[780px] lg:max-w-[820px]"
      >
        <DialogHeader className="sr-only">
          <DialogTitle>Realtime Voice Assistant</DialogTitle>
          <DialogDescription>
            Interactive voice conversation session
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex h-[520px] flex-col items-center justify-center gap-4 bg-[#0a0f1e]">
            <RefreshCw className="size-8 animate-spin text-[#f48c06]" />
            <div className="font-mono text-sm font-medium text-zinc-300">
              Initializing Voice Session...
            </div>
          </div>
        ) : useFallbackMode || !token || !wsUrl ? (
          <DirectVoiceSession onDisconnect={onClose} agentName={agentName} />
        ) : (
          <LiveKitRoom
            serverUrl={wsUrl}
            token={token}
            connect={true}
            audio={true}
            video={false}
            onError={() => {
              toast.info('Switching to Direct Streaming Voice Bridge')
              setUseFallbackMode(true)
            }}
            onDisconnected={onClose}
          >
            <LiveKitVoiceSession onDisconnect={onClose} agentName={agentName} />
          </LiveKitRoom>
        )}
      </DialogContent>
    </Dialog>
  )
}

export default LiveKitVoiceModal
