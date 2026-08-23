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
import { RefreshCw, Send, Mic, Copy, Check, MessageSquare } from 'lucide-react'
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
      const audioTrack = localParticipant.getTrackPublication(Track.Source.Microphone)
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
    <div className="flex flex-col h-[540px] w-full justify-between">
      <RoomAudioRenderer />

      {/* Top Status Header */}
      <div className="flex items-center justify-between border-b border-white/5 px-6 py-3">
        <div className="flex items-center gap-2">
          <span className="flex size-2.5 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs font-mono text-zinc-300">LiveKit Room: {room.name || 'Connected'}</span>
        </div>
        <div className="text-xs font-mono text-zinc-400">
          Agent State: <span className="uppercase text-primary font-semibold">{agentState}</span>
        </div>
      </div>

      {/* Visualizer Centerpiece */}
      <div className="flex flex-col items-center justify-center flex-1 py-4">
        <VoiceVisualizer state={agentState} barCount={11} />
        
        <div className="mt-4 w-full max-w-md px-6 text-center">
          <div className="text-xs text-zinc-400 italic">
            {agentState === 'speaking'
              ? `${agentName} is responding...`
              : agentState === 'thinking'
              ? 'Processing speech...'
              : 'Speak naturally into your microphone...'}
          </div>
        </div>
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
  const [statusMessage, setStatusMessage] = useState('Connecting to Deepgram Voice Bridge...')

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
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

  useEffect(() => {
    isMutedRef.current = isMuted
  }, [isMuted])

  useEffect(() => {
    isPushToTalkRef.current = isPushToTalk
  }, [isPushToTalk])

  useEffect(() => {
    isAgentSpeakingRef.current = voiceState === 'speaking' || activeSourcesRef.current.length > 0
  }, [voiceState])

  const stopAudioPlayback = () => {
    activeSourcesRef.current.forEach((src) => {
      try {
        src.stop()
        src.disconnect()
      } catch {}
    })
    activeSourcesRef.current = []
    nextStartTimeRef.current = 0
    isAgentSpeakingRef.current = false
  }

  const sampleBufferRef = useRef<Float32Array[]>([])
  const isRecordingAudioRef = useRef(false)
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null)

  // Encode Float32 PCM samples to 16-bit Mono WAV format (100% supported by Deepgram Nova-3)
  const encodeWavBuffer = (samples: Float32Array, sampleRate: number = 16000): ArrayBuffer => {
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
    view.setUint16(20, 1, true)  // Linear PCM
    view.setUint16(22, 1, true)  // Mono (1 channel)
    view.setUint32(24, sampleRate, true) // Sample rate
    view.setUint32(28, sampleRate * 2, true) // Byte rate (SampleRate * 1 * 16/8)
    view.setUint16(32, 2, true)  // Block align (1 * 16/8)
    view.setUint16(34, 16, true) // Bits per sample (16-bit)
    writeStr(36, 'data')
    view.setUint32(40, samples.length * 2, true)

    let offset = 44
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]))
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true)
    }

    return buffer
  }

  const downsampleTo16k = (buffer: Float32Array, inputRate: number): Float32Array => {
    if (inputRate === 16000) return buffer
    const ratio = inputRate / 16000
    const newLen = Math.round(buffer.length / ratio)
    const result = new Float32Array(newLen)
    let offsetResult = 0
    let offsetBuffer = 0
    while (offsetResult < result.length) {
      const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio)
      let accum = 0
      let count = 0
      for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
        accum += buffer[i]
        count++
      }
      result[offsetResult] = count > 0 ? accum / count : 0
      offsetResult++
      offsetBuffer = nextOffsetBuffer
    }
    return result
  }

  const preRollBufferRef = useRef<Float32Array[]>([])
  const noiseFloorRef = useRef(0.01)
  const lastSpeechTimeRef = useRef(0)
  const speechStartTimeRef = useRef(0)

  const startAudioRecording = () => {
    // Include the pre-roll buffer to preserve the first syllable
    sampleBufferRef.current = [...preRollBufferRef.current]
    isRecordingAudioRef.current = true
    speechStartTimeRef.current = Date.now()
  }

  const stopAudioRecordingAndSend = () => {
    if (!isRecordingAudioRef.current && sampleBufferRef.current.length === 0) return
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
    if (totalLen < 3200) return // Skip tiny clicks (<200ms)

    const merged = new Float32Array(totalLen)
    let curOffset = 0
    for (const c of chunks) {
      merged.set(c, curOffset)
      curOffset += c.length
    }

    const currentRate = audioCtxRef.current?.sampleRate || 48000
    const downsampled = downsampleTo16k(merged, currentRate)
    const wavBuffer = encodeWavBuffer(downsampled, 16000)

    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      setVoiceState('thinking')
      setStatusMessage('Processing speech (Deepgram Nova-3)...')
      setAgentText('')
      currentAgentTextRef.current = ''

      try {
        wsRef.current.send(wavBuffer)
      } catch (err) {
        console.error('Failed to send WAV buffer:', err)
        setVoiceState('listening')
      }
    }
  }

  // Setup WebSocket and Audio
  useEffect(() => {
    let isMounted = true

    try {
      const AudioContextClass =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      audioCtxRef.current = new AudioContextClass()
    } catch (err) {
      console.warn('AudioContext initialization error:', err)
    }

    const endpoint = selectedEndpoint || 'http://localhost:7777'
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

    ws.onmessage = (event) => {
      if (!isMounted) return

      if (typeof event.data === 'string') {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'user_transcript') {
            setUserTranscript(data.text)
            currentUserTranscriptRef.current = data.text
            setStatusMessage(`You: "${data.text}"`)
          } else if (data.type === 'agent_text') {
            setVoiceState('speaking')
            setAgentText((prev) => prev + data.text)
            currentAgentTextRef.current += data.text
            setStatusMessage(`${agentName} is responding...`)
          } else if (data.type === 'turn_complete') {
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

            const checkDone = () => {
              if (activeSourcesRef.current.length === 0) {
                if (isMounted) {
                  setVoiceState('listening')
                  setStatusMessage('Listening for your voice...')
                  isAgentSpeakingRef.current = false
                }
              } else {
                setTimeout(checkDone, 80)
              }
            }
            setTimeout(checkDone, 150)
          } else if (data.type === 'no_speech') {
            setVoiceState('listening')
            setStatusMessage('Listening for your voice...')
          } else if (data.type === 'error') {
            toast.error(data.message || 'Voice Turn Error')
          }
        } catch {}
      } else if (event.data instanceof ArrayBuffer && audioCtxRef.current) {
        setVoiceState('speaking')
        isAgentSpeakingRef.current = true
        playPcmChunk(event.data)
      }
    }

    ws.onerror = (err) => {
      console.error('Voice WS error:', err)
      if (isMounted) {
        setVoiceState('error')
        setStatusMessage('Voice Bridge Connection Error')
      }
    }

    ws.onclose = () => {
      if (isMounted) {
        setVoiceState('idle')
        setStatusMessage('Voice Bridge Disconnected')
      }
    }

    // Initialize Microphone capture with adaptive RMS VAD & pre-roll
    const initMic = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          }
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
          const analyser = ctx.createAnalyser()
          analyser.fftSize = 256
          analyser.smoothingTimeConstant = 0.3

          // ScriptProcessor for continuous PCM sample recording & real-time RMS VAD
          const processor = ctx.createScriptProcessor(2048, 1, 1)
          scriptProcessorRef.current = processor

          // Mute monitor to avoid echo feedback
          const zeroGain = ctx.createGain()
          zeroGain.gain.value = 0

          processor.onaudioprocess = (e) => {
            if (!isMounted || isMutedRef.current) return
            const inputData = e.inputBuffer.getChannelData(0)
            const chunkCopy = new Float32Array(inputData)

            // 1. Maintain 3-chunk (~130ms) circular pre-roll buffer
            preRollBufferRef.current.push(chunkCopy)
            if (preRollBufferRef.current.length > 4) {
              preRollBufferRef.current.shift()
            }

            // 2. High-precision RMS Calculation for accurate Voice Activity Detection
            let sumSq = 0
            for (let i = 0; i < inputData.length; i++) {
              sumSq += inputData[i] * inputData[i]
            }
            const rms = Math.sqrt(sumSq / inputData.length)

            // Dynamic noise floor tracking (adapts to ambient room acoustics)
            noiseFloorRef.current = Math.min(noiseFloorRef.current * 0.98 + rms * 0.02, 0.04)
            const speechThreshold = Math.max(0.024, noiseFloorRef.current * 2.2)
            const isVoiceActive = rms > speechThreshold

            if (!isPushToTalkRef.current) {
              const now = Date.now()

              if (isVoiceActive) {
                // If user speaks while agent is speaking: Barge-in interrupt
                if (isAgentSpeakingRef.current) {
                  stopAudioPlayback()
                }

                if (!isRecordingAudioRef.current) {
                  isSpeakingRef.current = true
                  startAudioRecording()
                }

                sampleBufferRef.current.push(chunkCopy)
                lastSpeechTimeRef.current = now
              } else if (isRecordingAudioRef.current) {
                sampleBufferRef.current.push(chunkCopy)

                // Silence threshold: 650ms of quiet after speaking, or 15s max utterance
                const silenceDuration = now - lastSpeechTimeRef.current
                const totalDuration = now - speechStartTimeRef.current

                if (silenceDuration > 650 || totalDuration > 15000) {
                  stopAudioRecordingAndSend()
                }
              }
            } else if (isRecordingAudioRef.current) {
              sampleBufferRef.current.push(chunkCopy)
            }
          }

          source.connect(analyser)
          source.connect(processor)
          processor.connect(zeroGain)
          zeroGain.connect(ctx.destination)

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
      } catch (err) {
        console.error('Microphone access error:', err)
        toast.error('Microphone permission required for voice interaction.')
        setStatusMessage('Microphone access denied. You can still type below.')
      }
    }

    initMic()

    return () => {
      isMounted = false
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
      if (ws.readyState === WebSocket.OPEN) ws.close()
      if (mediaStreamRef.current) {
        mediaStreamRef.current.getTracks().forEach((t) => t.stop())
      }
      if (scriptProcessorRef.current) {
        scriptProcessorRef.current.disconnect()
      }
      stopAudioPlayback()
      if (audioCtxRef.current) {
        audioCtxRef.current.close().catch(() => {})
      }
    }
  }, [selectedEndpoint, agentName, setMessages])

  // Seamless Jitter-Free PCM Audio Playback
  const playPcmChunk = async (arrayBuffer: ArrayBuffer) => {
    if (!audioCtxRef.current) return
    const ctx = audioCtxRef.current
    if (ctx.state === 'suspended') {
      try {
        await ctx.resume()
      } catch {}
    }

    // Ensure 16-bit 2-byte alignment
    const byteLen = arrayBuffer.byteLength - (arrayBuffer.byteLength % 2)
    if (byteLen <= 0) return

    const int16Array = new Int16Array(arrayBuffer, 0, byteLen / 2)
    const float32Array = new Float32Array(int16Array.length)
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / 32768.0
    }

    // 24kHz Deepgram Flux TTS Buffer
    const audioBuffer = ctx.createBuffer(1, float32Array.length, 24000)
    audioBuffer.getChannelData(0).set(float32Array)

    const source = ctx.createBufferSource()
    source.buffer = audioBuffer
    source.connect(ctx.destination)

    // Seamless gap-free scheduling (standard Web Audio streaming pattern)
    const currentTime = ctx.currentTime
    const startTime = Math.max(currentTime, nextStartTimeRef.current)
    source.start(startTime)
    nextStartTimeRef.current = startTime + audioBuffer.duration

    activeSourcesRef.current.push(source)
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== source)
      if (activeSourcesRef.current.length === 0 && voiceState !== 'speaking') {
        isAgentSpeakingRef.current = false
      }
    }
  }

  const handleSendPrompt = async (text: string) => {
    if (!text.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (audioCtxRef.current && audioCtxRef.current.state === 'suspended') {
      await audioCtxRef.current.resume()
    }
    stopAudioPlayback()
    setUserTranscript(text.trim())
    currentUserTranscriptRef.current = text.trim()
    setVoiceState('thinking')
    setStatusMessage('Processing text prompt...')
    setAgentText('')
    currentAgentTextRef.current = ''
    wsRef.current.send(JSON.stringify({ text: text.trim() }))
    setQuickInput('')
  }

  const handleManualPushToTalkStart = () => {
    if (isMuted) return
    stopAudioPlayback()
    setIsManualRecording(true)
    startAudioRecording()
  }

  const handleManualPushToTalkEnd = () => {
    setIsManualRecording(false)
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
    <div onClick={unlockAudio} className="flex flex-col h-[540px] w-full justify-between">
      {/* Top Status Header */}
      <div className="flex items-center justify-between border-b border-white/5 bg-[#0a0f1e]/80 px-6 py-3.5 backdrop-blur-xl">
        <div className="flex items-center gap-2">
          <span className="flex size-2.5 rounded-full bg-[#f48c06] shadow-[0_0_8px_#f48c06] animate-pulse" />
          <span className="text-xs font-mono text-zinc-300">Deepgram Voice Bridge</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`flex items-center gap-1 text-[11px] font-mono px-3 py-1 rounded-full border transition-all ${
              showHistory
                ? 'bg-[#e85d04]/20 border-[#e85d04]/50 text-[#f48c06]'
                : 'bg-white/5 border-white/10 text-zinc-400 hover:text-zinc-200 hover:border-white/20'
            }`}
            title="View full conversation transcript"
          >
            <MessageSquare className="size-3" />
            <span>Transcript ({history.length / 2 | 0})</span>
          </button>
          <button
            onClick={() => setIsPushToTalk(!isPushToTalk)}
            className={`text-[11px] font-mono px-3 py-1 rounded-full border transition-all ${
              isPushToTalk
                ? 'bg-amber-500/20 border-amber-500/40 text-amber-300'
                : 'bg-white/5 border-white/10 text-zinc-400 hover:text-zinc-200 hover:border-white/20'
            }`}
          >
            {isPushToTalk ? 'Push-To-Talk' : 'Fast VAD'}
          </button>
          <div className="text-xs font-mono text-zinc-400">
            State: <span className="uppercase text-[#f48c06] font-semibold">{voiceState}</span>
          </div>
        </div>
      </div>

      {showHistory ? (
        /* Full Transcript View */
        <div className="flex flex-col flex-1 overflow-hidden p-6 bg-[#0a0f1e]/90">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-mono uppercase tracking-wider text-zinc-400">
              Saved Conversation Turns ({history.length / 2 | 0})
            </h4>
            <Button
              variant="outline"
              size="sm"
              onClick={copyTranscriptText}
              className="h-7 gap-1.5 rounded-lg border-white/10 bg-white/5 px-2.5 text-xs text-zinc-300 hover:bg-[#e85d04]/20 hover:border-[#e85d04]/40 hover:text-white transition-all"
            >
              {copied ? <Check className="size-3 text-[#22c55e]" /> : <Copy className="size-3" />}
              {copied ? 'Copied' : 'Copy All'}
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto space-y-3 pr-2 rounded-2xl border border-white/5 bg-[#0f172a]/60 p-4">
            {history.length === 0 ? (
              <div className="text-center text-xs text-zinc-500 py-12 italic font-mono">
                No spoken turns yet. Speak or type to start recording the conversation.
              </div>
            ) : (
              history.map((turn, i) => (
                <div
                  key={i}
                  className={`rounded-xl p-3 text-xs ${
                    turn.role === 'user'
                      ? 'border border-white/10 bg-white/5 ml-6'
                      : 'border border-[#e85d04]/30 bg-[#e85d04]/10 mr-6'
                  }`}
                >
                  <div className="font-mono text-[10px] uppercase text-zinc-400 mb-1">
                    {turn.role === 'user' ? 'You' : agentName}
                  </div>
                  <div className="text-zinc-200 leading-relaxed font-main">{turn.text}</div>
                </div>
              ))
            )}
          </div>
        </div>
      ) : (
        /* Visualizer Centerpiece */
        <div className="flex flex-col items-center justify-center flex-1 py-4 bg-[#0a0f1e]/90 relative overflow-hidden">
          {/* Subtle background glow */}
          <div className="orb-orange -top-20 -right-20 size-64 opacity-20 pointer-events-none" />

          <VoiceVisualizer
            state={voiceState}
            volume={voiceState === 'speaking' ? 0.6 : micVolume}
            barCount={11}
          />

          {/* Live Conversation Transcript Feed */}
          <div className="mt-2 w-full max-w-md px-6 text-center min-h-[72px] flex items-center justify-center relative z-10">
            <AnimatePresence mode="wait">
              {agentText ? (
                <motion.div
                  key="agent-text"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="max-h-24 overflow-y-auto rounded-2xl border border-[#e85d04]/30 bg-[#0f172a]/90 p-3 text-sm text-zinc-100 w-full shadow-lg"
                >
                  <div className="text-[10px] uppercase font-mono text-[#f48c06] mb-1">{agentName}</div>
                  {agentText}
                </motion.div>
              ) : userTranscript ? (
                <motion.div
                  key="user-text"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl border border-white/10 bg-[#0f172a]/90 p-3 text-sm text-zinc-200 w-full shadow-lg"
                >
                  <div className="text-[10px] uppercase font-mono text-zinc-400 mb-1">You</div>
                  {userTranscript}
                </motion.div>
              ) : (
                <motion.div
                  key="status-msg"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-xs text-zinc-400 italic font-mono"
                >
                  {statusMessage}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Live Mic Level Feedback Indicator */}
          <div className="mt-1 flex items-center gap-2 rounded-full border border-white/5 bg-[#0f172a]/60 px-3 py-1 text-[11px] font-mono text-zinc-400 relative z-10 shadow-sm">
            <Mic className={`size-3 ${micVolume > 0.02 ? 'text-[#22c55e] animate-pulse' : 'text-zinc-500'}`} />
            <span className="text-[10px] text-zinc-400">Input:</span>
            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full bg-gradient-to-r from-[#22c55e] via-[#f48c06] to-[#dc2f02] transition-all duration-75"
                style={{ width: `${Math.min(100, Math.max(4, micVolume * 100))}%` }}
              />
            </div>
            <span className="text-[10px] text-zinc-500">{micVolume > 0.018 ? 'Voice Active' : 'Ready'}</span>
          </div>

          {/* Push to talk hold button or text input */}
          {isPushToTalk ? (
            <div className="mt-4 flex w-full max-w-xs justify-center relative z-10">
              <button
                onMouseDown={handleManualPushToTalkStart}
                onMouseUp={handleManualPushToTalkEnd}
                onTouchStart={handleManualPushToTalkStart}
                onTouchEnd={handleManualPushToTalkEnd}
                className={`flex items-center gap-2 px-6 py-2.5 rounded-full font-medium text-xs transition-all shadow-lg select-none ${
                  isManualRecording
                    ? 'bg-rose-600 text-white scale-95 ring-4 ring-rose-500/30'
                    : 'bg-gradient-to-tr from-[#e85d04] to-[#f48c06] hover:brightness-110 text-white active:scale-95'
                }`}
              >
                <Mic className="size-4" />
                {isManualRecording ? 'Release to Send' : 'Hold to Speak'}
              </button>
            </div>
          ) : (
            <div className="mt-4 flex w-full max-w-sm items-center gap-1.5 px-4 relative z-10">
              <input
                type="text"
                placeholder="Ask with voice or type message..."
                value={quickInput}
                onChange={(e) => setQuickInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSendPrompt(quickInput)
                }}
                className="h-9 w-full rounded-xl border border-white/10 bg-[#0f172a]/90 px-3 text-xs text-white placeholder:text-zinc-500 focus:outline-none focus:border-[#e85d04]/60"
              />
              <Button
                size="icon"
                onClick={() => handleSendPrompt(quickInput)}
                disabled={!quickInput.trim()}
                className="size-9 rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] hover:brightness-110 text-white shrink-0"
              >
                <Send className="size-3.5" />
              </Button>
            </div>
          )}
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
          res = await fetch(`${selectedEndpoint}/api/livekit/token?room=voice-agent-room`)
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
      <DialogContent className="max-w-xl overflow-hidden border border-white/10 bg-[#0a0f1e] p-0 text-white shadow-2xl rounded-3xl backdrop-blur-2xl ring-1 ring-white/5">
        <DialogHeader className="sr-only">
          <DialogTitle>Realtime Voice Assistant</DialogTitle>
          <DialogDescription>Interactive voice conversation session</DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex h-[480px] flex-col items-center justify-center gap-4 bg-[#0a0f1e]">
            <RefreshCw className="size-8 animate-spin text-[#f48c06]" />
            <div className="text-sm font-medium text-zinc-300 font-mono">Initializing Voice Session...</div>
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
