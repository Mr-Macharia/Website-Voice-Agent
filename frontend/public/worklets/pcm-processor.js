/**
 * Microphone capture worklet for the AssemblyAI Voice Agent.
 *
 * Takes raw Float32 frames at the AudioContext's native rate, resamples to the
 * 24 kHz mono PCM16 the Voice Agent API expects, and posts them to the main
 * thread as transferable ArrayBuffers.
 *
 * This replaced vad-processor.js, which did adaptive-RMS voice detection in
 * the browser. The server now owns turn detection — it decides from what was
 * said, not just from volume — so all this needs to do is convert and forward.
 */

// Samples per post: 50 ms at 24 kHz. process() runs every 128-frame render
// quantum (~2.7 ms at 48 kHz); posting each one meant ~375 base64 + JSON +
// WebSocket sends a second on the main thread, competing with reply-audio
// playback. Batching to 50 ms brings that to ~20 and adds at most 50 ms of
// input latency, which the server's turn detection absorbs.
const BATCH_SAMPLES = 1200

class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const { inputSampleRate, targetSampleRate } = options.processorOptions
    this.ratio = inputSampleRate / targetSampleRate
    this.batch = new Int16Array(BATCH_SAMPLES)
    this.filled = 0
  }

  process(inputs) {
    const input = inputs[0]?.[0]
    if (!input) return true

    const outLength = Math.floor(input.length / this.ratio)
    if (outLength <= 0) return true

    // Linear pick rather than a filtered resample: speech at 24 kHz tolerates
    // it, and the transcription model is far more sensitive to latency and
    // dropouts than to the aliasing this introduces.
    for (let i = 0; i < outLength; i++) {
      const sample = input[Math.floor(i * this.ratio)] ?? 0
      this.batch[this.filled++] = Math.max(
        -32768,
        Math.min(32767, Math.round(sample * 32767))
      )
      if (this.filled === BATCH_SAMPLES) {
        this.port.postMessage(this.batch.buffer, [this.batch.buffer])
        this.batch = new Int16Array(BATCH_SAMPLES)
        this.filled = 0
      }
    }
    return true
  }
}

registerProcessor('pcm-processor', PCMProcessor)
