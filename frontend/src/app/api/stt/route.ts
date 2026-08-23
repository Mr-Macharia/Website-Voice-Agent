import { NextRequest, NextResponse } from 'next/server'

export async function POST(req: NextRequest) {
  try {
    const apiKey = process.env.DEEPGRAM_API_KEY
    if (!apiKey) {
      return NextResponse.json({ error: 'DEEPGRAM_API_KEY is not configured' }, { status: 500 })
    }

    const audioBuffer = await req.arrayBuffer()
    if (!audioBuffer || audioBuffer.byteLength === 0) {
      return NextResponse.json({ error: 'Empty audio buffer' }, { status: 400 })
    }

    const contentType = req.headers.get('content-type') || 'audio/webm'

    const response = await fetch('https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true', {
      method: 'POST',
      headers: {
        Authorization: `Token ${apiKey}`,
        'Content-Type': contentType
      },
      body: audioBuffer
    })

    if (!response.ok) {
      const errText = await response.text()
      console.error('Deepgram STT error:', response.status, errText)
      return NextResponse.json({ error: 'STT transcription failed' }, { status: response.status })
    }

    const data = await response.json()
    const transcript =
      data?.results?.channels?.[0]?.alternatives?.[0]?.transcript || ''

    return NextResponse.json({ transcript })
  } catch (error) {
    console.error('Error in /api/stt:', error)
    return NextResponse.json({ error: 'Internal Server Error' }, { status: 500 })
  }
}
