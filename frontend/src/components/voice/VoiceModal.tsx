'use client'

/**
 * Chooses the voice transport.
 *
 * The AssemblyAI Voice Agent API is replacing LiveKit, whose metered resource
 * was connection minutes rather than speech. This switch exists so both paths
 * can be exercised during the migration; once AssemblyAI is proven in
 * production the LiveKit branch and its dependencies come out.
 *
 * Set NEXT_PUBLIC_VOICE_PROVIDER=livekit to fall back.
 */

import React from 'react'

import AssemblyAIVoiceModal from './AssemblyAIVoiceModal'
import LiveKitVoiceModal from './LiveKitVoiceModal'

interface VoiceModalProps {
  isOpen: boolean
  onClose: () => void
  agentName?: string
}

const useLiveKit = process.env.NEXT_PUBLIC_VOICE_PROVIDER === 'livekit'

export const VoiceModal: React.FC<VoiceModalProps> = (props) =>
  useLiveKit ? (
    <LiveKitVoiceModal {...props} />
  ) : (
    <AssemblyAIVoiceModal {...props} />
  )

export default VoiceModal
