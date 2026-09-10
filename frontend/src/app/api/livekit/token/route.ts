import { NextRequest, NextResponse } from 'next/server'
import { AccessToken, type RoomConfiguration } from 'livekit-server-sdk'

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
    let identity =
      searchParams.get('identity') ||
      `user-${Math.random().toString(36).substring(2, 9)}`
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

    const apiKey = process.env.LIVEKIT_API_KEY
    const apiSecret = process.env.LIVEKIT_API_SECRET
    const wsUrl =
      process.env.NEXT_PUBLIC_LIVEKIT_URL || process.env.LIVEKIT_URL

    // Previously these silently defaulted to devkey/secret, which produced a
    // confusing "invalid API key" in the browser when signing against a real
    // LiveKit Cloud project. Fail loudly instead.
    if (!apiKey || !apiSecret || !wsUrl) {
      const missing = [
        !apiKey && 'LIVEKIT_API_KEY',
        !apiSecret && 'LIVEKIT_API_SECRET',
        !wsUrl && 'NEXT_PUBLIC_LIVEKIT_URL (or LIVEKIT_URL)'
      ].filter(Boolean)

      console.error(
        `[LiveKit token] Missing config: ${missing.join(', ')}. ` +
          'Set these in the repo-root .env (loaded by next.config.ts).'
      )
      return NextResponse.json(
        { error: `LiveKit is not configured. Missing: ${missing.join(', ')}` },
        { status: 500 }
      )
    }

    // The worker registers with agent_name="voice-agent", which makes it an
    // explicit-dispatch agent: it will NOT auto-join rooms. Embedding the
    // dispatch in the token tells LiveKit to bring the agent into this room
    // as soon as the user connects.
    const agentName = process.env.LIVEKIT_AGENT_NAME || 'voice-agent'

    const at = new AccessToken(apiKey, apiSecret, {
      identity,
      name,
      ttl: '1h'
    })

    at.roomConfig = {
      agents: [{ agentName }]
    } as RoomConfiguration

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
      {
        error:
          error instanceof Error ? error.message : 'Failed to generate token'
      },
      { status: 500 }
    )
  }
}
