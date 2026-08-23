export function decodeBase64Audio(
  base64String: string,
  mimeType = 'audio/mpeg',
  sampleRate = 24000,
  numChannels = 1
): string {
  // Chunked base64 decode to avoid stack overflow on large payloads (>1MB)
  // atob can handle large strings but loop over charCodeAt is safer chunked
  const CHUNK = 8192
  let byteArray: Uint8Array
  try {
    const byteString = atob(base64String)
    byteArray = new Uint8Array(byteString.length)
    for (let i = 0; i < byteString.length; i += 1) {
      byteArray[i] = byteString.charCodeAt(i)
    }
  } catch {
    // Fallback chunked
    const bytes: number[] = []
    for (let i = 0; i < base64String.length; i += CHUNK) {
      const chunk = base64String.slice(i, i + CHUNK)
      const decoded = atob(chunk)
      for (let j = 0; j < decoded.length; j++) bytes.push(decoded.charCodeAt(j))
    }
    byteArray = new Uint8Array(bytes)
  }

  let blob: Blob

  if (mimeType === 'audio/pcm16') {
    // Convert PCM16 raw audio to WAV format
    const wavHeader = createWavHeader(byteArray.length, sampleRate, numChannels)
    const wavData = new Uint8Array(wavHeader.length + byteArray.length)
    wavData.set(wavHeader, 0)
    wavData.set(byteArray, wavHeader.length)

    blob = new Blob([wavData as BlobPart], { type: 'audio/wav' }) // Convert PCM to WAV
  } else {
    blob = new Blob([byteArray as BlobPart], { type: mimeType })
  }

  return URL.createObjectURL(blob)
}

// Function to generate WAV header for PCM16
function createWavHeader(
  dataLength: number,
  sampleRate: number,
  numChannels: number
): Uint8Array {
  const header = new ArrayBuffer(44)
  const view = new DataView(header)

  const blockAlign = numChannels * 2 // 16-bit PCM = 2 bytes per sample
  const byteRate = sampleRate * blockAlign

  // "RIFF" chunk descriptor
  view.setUint32(0, 0x52494646, false) // "RIFF"
  view.setUint32(4, 36 + dataLength, true) // File size
  view.setUint32(8, 0x57415645, false) // "WAVE"

  // "fmt " sub-chunk
  view.setUint32(12, 0x666d7420, false) // "fmt "
  view.setUint32(16, 16, true) // Subchunk1 size
  view.setUint16(20, 1, true) // Audio format (1 = PCM)
  view.setUint16(22, numChannels, true) // Number of channels
  view.setUint32(24, sampleRate, true) // Sample rate
  view.setUint32(28, byteRate, true) // Byte rate
  view.setUint16(32, blockAlign, true) // Block align
  view.setUint16(34, 16, true) // Bits per sample (16-bit)

  // "data" sub-chunk
  view.setUint32(36, 0x64617461, false) // "data"
  view.setUint32(40, dataLength, true) // Data size

  return new Uint8Array(header)
}
