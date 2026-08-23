/**
 * VAD AudioWorkletProcessor
 * Off-main-thread capture. Forwards 128-sample Float32 chunks to main thread.
 * Main thread handles RMS, pre-roll, VAD logic to avoid blocking audio thread.
 * Runs at AudioContext.sampleRate (device-dependent); main thread downsamples to 16k.
 */
class VADProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (input && input.length > 0) {
      const channel = input[0]
      if (channel && channel.length > 0) {
        // Copy to avoid detached buffer issues
        this.port.postMessage(channel.slice(0))
      }
    }
    return true // keep alive
  }
}

registerProcessor('vad-processor', VADProcessor)
