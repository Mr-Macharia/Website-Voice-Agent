/**
 * Real-time voice session with the AssemblyAI Voice Agent API.
 *
 * One WebSocket carries everything: microphone audio up, transcripts and
 * synthesized speech down, with turn detection and barge-in decided server
 * side. This replaced the LiveKit room, whose metered resource was connection
 * minutes rather than speech.
 *
 * What this class owns: microphone capture and resampling, streamed PCM16
 * playback, flushing that playback when the visitor interrupts, relaying tool
 * calls to the backend, and ending the session cleanly.
 *
 * What it deliberately does NOT own: deciding when a turn ended, or whether
 * speech was an interruption. Both are semantic judgements the server makes
 * from what was actually said.
 */

export type VoiceSessionState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'error'

export interface VoiceTurn {
  id: string
  role: 'user' | 'agent'
  text: string
  final: boolean
}

export interface VoiceSessionCallbacks {
  onStateChange: (state: VoiceSessionState, message?: string) => void
  onUserPartial: (text: string) => void
  onUserFinal: (text: string) => void
  onAgentFinal: (text: string) => void
}

const WS_URL = 'wss://agents.assemblyai.com/v1/ws'
/** The Voice Agent API speaks PCM16 mono at 24 kHz, both directions. */
const SAMPLE_RATE = 24000
/**
 * Playback gain for the agent's voice.
 *
 * Deliberately 1.0. The kaytie reference uses 2.2 to lift a quiet TTS output,
 * but it also half-duplexes on mobile, so it never pays the cost: the browser's
 * echo canceller models the signal it sends to the speakers, and amplifying
 * that signal afterwards means what returns through the microphone no longer
 * matches the model. The residual echo then swamps the visitor's voice and
 * barge-in stops working — measured live as having to repeat a question three
 * times before the agent would stop talking.
 *
 * Loudness belongs server-side instead, where it does not break cancellation:
 * output.volume on the stored agent (0-100).
 */
const OUTPUT_GAIN = 1.0

export class AssemblyAISession {
  private ws: WebSocket | null = null
  private audioCtx: AudioContext | null = null
  private micStream: MediaStream | null = null
  private worklet: AudioWorkletNode | null = null
  private micSource: MediaStreamAudioSourceNode | null = null
  private sinkGain: GainNode | null = null
  private outGain: GainNode | null = null

  micAnalyser: AnalyserNode | null = null
  outAnalyser: AnalyserNode | null = null

  /** Queued reply audio, so barge-in can stop all of it at once. */
  private outputSources = new Set<AudioBufferSourceNode>()
  /**
   * When the next reply chunk should start playing. Chunks are scheduled on
   * this cursor rather than played on arrival: playing on arrival overlaps
   * them, and setTimeout scheduling drifts from the hardware clock and gives
   * pops and gaps.
   */
  private nextPlayTime = 0

  private sessionReady = false
  private endedByUser = false
  private cleanedUp = false
  private muted = false
  private sessionId: string | null = null

  /**
   * The most recent turn event. tool.result may only be sent when the agent is
   * idle, so results are held until reply.done.
   */
  private lastEvent:
    | 'reply.started'
    | 'input.speech.started'
    | 'reply.done'
    | null = null
  private pendingToolResults: { callId: string; result: string }[] = []

  /** Backend origin, used for the token and tool-relay endpoints. */
  private apiBase = ''

  private readonly onVisibilityChange: () => void

  constructor(private callbacks: VoiceSessionCallbacks) {
    this.onVisibilityChange = () => {
      // iOS suspends the AudioContext when the tab is backgrounded, which
      // kills the mic pipeline silently. Resume when we come back.
      if (!document.hidden && this.audioCtx?.state === 'suspended') {
        void this.audioCtx.resume().catch(() => {})
      }
    }
  }

  get isMuted() {
    return this.muted
  }

  get id(): string | null {
    return this.sessionId
  }

  async start(apiBase: string): Promise<void> {
    this.apiBase = apiBase
    this.callbacks.onStateChange('connecting')

    // 1. Token and session config from our backend. The AssemblyAI key stays
    //    server-side; the persona prompt lives in Python and is forwarded
    //    verbatim from here.
    let token: string
    let session: Record<string, unknown>
    try {
      const res = await fetch(`${apiBase}/api/voice/token`, {
        cache: 'no-store'
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || !data.token) {
        this.fail(data.detail || "Voice isn't available right now.")
        return
      }
      token = data.token as string
      session = data.session as Record<string, unknown>
    } catch {
      this.fail(
        "Couldn't reach the voice service. Check your connection and try again."
      )
      return
    }

    // 2. Audio context and microphone. Must run inside the user-gesture call
    //    stack or the browser refuses to start audio.
    try {
      this.audioCtx = new AudioContext()
      await this.audioCtx.resume()
      await this.audioCtx.audioWorklet.addModule('/worklets/pcm-processor.js')
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          // Echo cancellation is what lets the visitor talk over the agent
          // without the agent hearing itself and interrupting its own reply.
          echoCancellation: true,
          // The server denoises already, and AssemblyAI's docs are explicit
          // that a second layer costs more accuracy than the noise did. Use
          // voice_focus (set server-side) to tune this instead.
          noiseSuppression: false,
          autoGainControl: false
        }
      })
    } catch (err) {
      this.handleMicError(err)
      return
    }

    // 3. Connect.
    try {
      await this.connect(token, session)
    } catch {
      this.fail(
        "Couldn't reach the voice service. Check your connection and try again."
      )
    }
  }

  private handleMicError(err: unknown): void {
    const name = (err as DOMException)?.name
    if (
      name === 'NotAllowedError' ||
      name === 'PermissionDeniedError' ||
      name === 'SecurityError'
    ) {
      this.fail('I need microphone access to hear you. Allow it and try again.')
    } else if (name === 'NotFoundError') {
      this.fail("I couldn't find a microphone on this device.")
    } else {
      this.fail(
        "I couldn't start the microphone. Check your audio settings and try again."
      )
    }
  }

  private connect(
    token: string,
    session: Record<string, unknown>
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`)
      this.ws = ws

      const bail = (err: unknown) => {
        ws.close()
        this.ws = null
        reject(err)
      }

      ws.onerror = () => bail(new Error('websocket error'))

      ws.onopen = () => {
        // Sent immediately, without waiting for session.ready — the config has
        // to be in place before the server starts the greeting.
        ws.send(JSON.stringify({ type: 'session.update', session }))
        this.startMicCapture()
        window.setTimeout(() => {
          if (!this.sessionReady && this.ws === ws)
            bail(new Error('handshake timeout'))
        }, 15000)
      }

      ws.onmessage = (event) => {
        try {
          this.handleMessage(JSON.parse(event.data as string))
        } catch {
          console.error('Could not parse voice agent message')
        }
      }

      ws.onclose = () => {
        if (this.cleanedUp) return
        if (!this.sessionReady && !this.endedByUser) {
          bail(new Error('closed before ready'))
        } else {
          this.cleanup()
          if (!this.endedByUser) {
            this.fail(
              'The connection dropped and the session ended. Start again when ready.'
            )
          }
        }
      }

      const ready = window.setInterval(() => {
        if (this.sessionReady && this.ws === ws) {
          window.clearInterval(ready)
          resolve()
        } else if (this.ws !== ws) {
          window.clearInterval(ready)
        }
      }, 50)
    })
  }

  private handleMessage(msg: Record<string, unknown>): void {
    switch (msg.type) {
      case 'session.ready':
        this.sessionId =
          typeof msg.session_id === 'string' ? msg.session_id : null
        this.sessionReady = true
        this.callbacks.onStateChange('listening')
        break

      case 'session.error': {
        const code = String(msg.error_code ?? msg.code ?? 'unknown')
        console.error('Voice session error:', code, msg.message)
        this.fail(
          code === 'unauthorized'
            ? 'The session token expired. Please start a new session.'
            : 'Something went wrong with the voice session. Please try again.'
        )
        break
      }

      case 'input.speech.started':
        // The visitor started talking. If the agent was mid-reply this is a
        // barge-in, so drop whatever is still queued — otherwise they keep
        // hearing speech they already interrupted.
        this.lastEvent = 'input.speech.started'
        this.flushOutput()
        this.callbacks.onStateChange('listening')
        break

      case 'transcript.user.delta':
        this.callbacks.onUserPartial(String(msg.text ?? msg.delta ?? ''))
        break

      case 'input.speech.stopped':
        this.callbacks.onStateChange('thinking')
        break

      case 'transcript.user':
        this.callbacks.onUserFinal(String(msg.text ?? msg.transcript ?? ''))
        break

      case 'reply.started':
        this.lastEvent = 'reply.started'
        this.callbacks.onStateChange('thinking')
        break

      case 'reply.audio': {
        // Note the field: input audio travels in `audio`, reply audio in
        // `data`. Reading `audio` here silently yields nothing.
        const data = String(msg.data ?? '')
        if (data) {
          this.callbacks.onStateChange('speaking')
          this.playChunk(data)
        }
        break
      }

      case 'transcript.agent':
        this.callbacks.onAgentFinal(String(msg.text ?? msg.transcript ?? ''))
        break

      case 'tool.call':
        void this.handleToolCall(msg)
        break

      case 'reply.done':
        if (msg.status === 'interrupted') {
          // The visitor cut in, so the agent has moved on. Results for the
          // abandoned turn would answer a question nobody is waiting for.
          this.pendingToolResults = []
        } else {
          this.lastEvent = 'reply.done'
          this.flushToolResults()
        }
        this.callbacks.onStateChange('listening')
        break

      case 'session.ended':
        this.cleanup()
        break

      default:
        break
    }
  }

  /**
   * Run a tool call via the backend and queue its result.
   *
   * The tools need Postgres, the knowledge base and the Composio session, so
   * only the dispatch passes through the browser.
   */
  private async handleToolCall(msg: Record<string, unknown>): Promise<void> {
    const callId = String(msg.call_id ?? '')
    const name = String(msg.name ?? '')
    if (!callId || !name) return

    let args: Record<string, unknown> = {}
    const raw = msg.arguments
    if (typeof raw === 'string') {
      try {
        args = JSON.parse(raw)
      } catch {
        args = {}
      }
    } else if (raw && typeof raw === 'object') {
      args = raw as Record<string, unknown>
    }

    let result: string
    try {
      const res = await fetch(`${this.apiBase}/api/voice/tool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, arguments: args })
      })
      const data = await res.json().catch(() => ({}))
      result = String(data.result ?? '')
      if (!res.ok || !result) {
        result = `Could not run '${name}'. Tell the visitor it didn't work and carry on.`
      }
    } catch {
      result = `Could not reach '${name}'. Tell the visitor it didn't work and carry on.`
    }

    this.pendingToolResults.push({ callId, result })
    // Send now if no reply is in flight. `input.speech.started` counts as idle:
    // the visitor interrupted, so the agent is listening rather than speaking,
    // and it is waiting on this result to answer the new question.
    //
    // Treating it as busy was a deadlock — after any barge-in, lastEvent stayed
    // 'input.speech.started' until some later reply.done, so the result sat in
    // the browser and the agent never answered at all.
    if (this.lastEvent !== 'reply.started') {
      this.flushToolResults()
    }
  }

  private flushToolResults(): void {
    if (!this.pendingToolResults.length) return
    if (this.ws?.readyState !== WebSocket.OPEN) return
    for (const { callId, result } of this.pendingToolResults) {
      this.ws.send(
        JSON.stringify({ type: 'tool.result', call_id: callId, result })
      )
    }
    this.pendingToolResults = []
  }

  private startMicCapture(): void {
    const ctx = this.audioCtx!
    this.micSource = ctx.createMediaStreamSource(this.micStream!)
    this.micAnalyser = ctx.createAnalyser()
    this.micAnalyser.fftSize = 256

    this.worklet = new AudioWorkletNode(ctx, 'pcm-processor', {
      processorOptions: {
        inputSampleRate: ctx.sampleRate,
        targetSampleRate: SAMPLE_RATE
      }
    })

    this.worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
      if (this.muted || !this.sessionReady) return
      // Full duplex: the mic keeps streaming while the agent speaks, on every
      // device, so the visitor can interrupt at any point. If an agent ever
      // interrupts *itself* on a phone, that is its own speaker leaking past
      // echo cancellation into the mic — raise interruption_delay server-side
      // before considering muting the mic during replies.
      this.sendAudio(event.data)
    }

    this.micSource.connect(this.micAnalyser)
    this.micSource.connect(this.worklet)
    document.addEventListener('visibilitychange', this.onVisibilityChange)

    // Reply audio: analyser (drives the visualizer) → gain → speakers.
    this.outAnalyser = ctx.createAnalyser()
    this.outAnalyser.fftSize = 256
    this.outGain = ctx.createGain()
    this.outGain.gain.value = OUTPUT_GAIN
    this.outAnalyser.connect(this.outGain)
    this.outGain.connect(ctx.destination)

    // The worklet needs a path to the destination to keep being pulled, but at
    // zero gain so the visitor never hears their own microphone.
    this.sinkGain = ctx.createGain()
    this.sinkGain.gain.value = 0
    this.worklet.connect(this.sinkGain)
    this.sinkGain.connect(ctx.destination)
  }

  private sendAudio(buffer: ArrayBuffer): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return
    const bytes = new Uint8Array(buffer)
    let binary = ''
    const CHUNK = 0x8000 // chunked to stay under the argument-count limit
    for (let i = 0; i < bytes.length; i += CHUNK) {
      binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
    }
    this.ws.send(JSON.stringify({ type: 'input.audio', audio: btoa(binary) }))
  }

  private playChunk(base64: string): void {
    const ctx = this.audioCtx
    if (!ctx) return
    try {
      const binary = atob(base64)
      const pcm = new Int16Array(binary.length / 2)
      for (let i = 0; i < pcm.length; i++) {
        pcm[i] = binary.charCodeAt(i * 2) | (binary.charCodeAt(i * 2 + 1) << 8)
      }
      if (!pcm.length) return

      const float = new Float32Array(pcm.length)
      for (let i = 0; i < pcm.length; i++) float[i] = pcm[i] / 32768

      const buffer = ctx.createBuffer(1, float.length, SAMPLE_RATE)
      buffer.copyToChannel(float, 0)

      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(this.outAnalyser!)
      this.outputSources.add(source)
      source.onended = () => this.outputSources.delete(source)

      // Schedule on the cursor, never "now": chunks arrive faster than they
      // play, so playing on arrival would overlap them into noise.
      const now = ctx.currentTime
      if (this.nextPlayTime < now) this.nextPlayTime = now
      source.start(this.nextPlayTime)
      this.nextPlayTime += buffer.duration
    } catch (err) {
      console.error('Voice playback error:', err)
    }
  }

  /** Drop all queued reply audio — barge-in, or teardown. */
  private flushOutput(): void {
    this.outputSources.forEach((src) => {
      try {
        src.stop()
      } catch {
        /* already stopped */
      }
      src.disconnect()
    })
    this.outputSources.clear()
    this.nextPlayTime = 0
  }

  setMuted(muted: boolean): void {
    this.muted = muted
    this.micStream?.getAudioTracks().forEach((t) => {
      t.enabled = !muted
    })
  }

  /** End cleanly: session.end first, so we don't pay for the resume grace window. */
  end(): void {
    this.endedByUser = true
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'session.end' }))
      window.setTimeout(() => {
        if (!this.cleanedUp) this.cleanup()
      }, 3000)
    } else {
      this.cleanup()
    }
  }

  private fail(message: string): void {
    this.cleanup()
    this.callbacks.onStateChange('error', message)
  }

  private cleanup(): void {
    if (this.cleanedUp) return
    this.cleanedUp = true
    this.sessionReady = false
    this.flushOutput()

    try {
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.close()
    } catch {
      /* ignore */
    }
    this.ws = null

    this.micStream?.getTracks().forEach((t) => t.stop())
    this.micSource?.disconnect()
    this.worklet?.disconnect()
    this.sinkGain?.disconnect()
    document.removeEventListener('visibilitychange', this.onVisibilityChange)
    this.micAnalyser = null
    this.outAnalyser?.disconnect()
    this.outAnalyser = null
    this.outGain?.disconnect()
    this.outGain = null
    void this.audioCtx?.close()
    this.audioCtx = null
  }
}
