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
class PCMProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { inputSampleRate, targetSampleRate } = options.processorOptions;
    this.ratio = inputSampleRate / targetSampleRate;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;

    const outLength = Math.floor(input.length / this.ratio);
    if (outLength <= 0) return true;

    // Linear pick rather than a filtered resample: speech at 24 kHz tolerates
    // it, and the transcription model is far more sensitive to latency and
    // dropouts than to the aliasing this introduces.
    const pcm16 = new Int16Array(outLength);
    for (let i = 0; i < outLength; i++) {
      const sample = input[Math.floor(i * this.ratio)] ?? 0;
      pcm16[i] = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)));
    }

    this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
