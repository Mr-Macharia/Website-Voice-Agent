import { NextRequest, NextResponse } from 'next/server'
import { AccessToken } from 'livekit-server-sdk'

export async function GET(req: NextRequest) {
  return handleToken(req)
}

export async function POST(req: NextRequest) {
  return handleToken(req)
}

async function handleToken(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url)
    let room = searchParams.get('room') || 'voice-agent-room'
    let identity = searchParams.get('identity') || `user-${Math.random().toString(36).substring(2, 9)}`
    let name = searchParams.get('name') || identity

    if (req.method === 'POST') {
      try {
        const body = await req.json()
        if (body.room) room = body.room
        if (body.identity) identity = body.identity
        if (body.name) name = body.name
      } catch {
        // Body parsing optional
      }
    }

    const apiKey = process.env.LIVEKIT_API_KEY || 'devkey'
    const apiSecret = process.env.LIVEKIT_API_SECRET || 'secret01234567890123456789012345678901'
    const wsUrl = process.env.NEXT_PUBLIC_LIVEKIT_URL || process.env.LIVEKIT_URL || 'wss://voice-agent.livekit.cloud'

    const at = new AccessToken(apiKey, apiSecret, {
      identity,
      name,
      ttl: '1h'
    })

    at.addGrant({
      roomJoin: true,
      room,
      canPublish: true,
      canSubscribe: true,
      canPublishData: true
    })

    const token = await at.toJwt()

    return NextResponse.json({
      token,
      url: wsUrl,
      room,
      identity,
      name
    })
  } catch (error) {
    console.error('Error generating LiveKit token:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Failed to generate token' },
      { status: 500 }
    )
  }
}
