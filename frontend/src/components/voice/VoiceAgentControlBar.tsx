'use client'

import React from 'react'
import { Button } from '@/components/ui/button'
import { Mic, MicOff, PhoneOff, Sparkles } from 'lucide-react'

interface VoiceAgentControlBarProps {
  isMuted: boolean
  onToggleMute: () => void
  onDisconnect: () => void
  isConnected: boolean
  agentName?: string
  mode?: string
}

export const VoiceAgentControlBar: React.FC<VoiceAgentControlBarProps> = ({
  isMuted,
  onToggleMute,
  onDisconnect,
  isConnected,
  agentName = 'Realtime Voice Assistant',
  mode = 'LiveKit WebRTC'
}) => {
  return (
    <div className="flex w-full items-center justify-between border-t border-white/5 bg-[#0a0f1e]/90 px-6 py-4 backdrop-blur-2xl font-main">
      {/* Agent Info & Connection Status */}
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] text-white shadow-md shadow-orange-950/40">
          <Sparkles className="size-4" />
        </div>
        <div>
          <div className="text-sm font-large font-bold text-white">{agentName}</div>
          <div className="flex items-center gap-1.5 text-xs font-mono text-zinc-400">
            <span
              className={`size-1.5 rounded-full ${
                isConnected ? 'bg-[#22c55e] shadow-[0_0_6px_#22c55e]' : 'bg-[#e85d04] animate-pulse'
              }`}
            />
            <span>{isConnected ? mode : 'Connecting...'}</span>
          </div>
        </div>
      </div>

      {/* Main Control Actions */}
      <div className="flex items-center gap-3">
        {/* Mute / Unmute Button */}
        <Button
          variant="outline"
          size="icon"
          onClick={onToggleMute}
          disabled={!isConnected}
          className={`size-11 rounded-full border transition-all ${
            isMuted
              ? 'border-rose-500/50 bg-rose-500/10 text-rose-400 hover:bg-rose-500/20'
              : 'border-white/10 bg-white/5 text-zinc-200 hover:bg-white/10 hover:text-white'
          }`}
          title={isMuted ? 'Unmute microphone' : 'Mute microphone'}
        >
          {isMuted ? <MicOff className="size-5" /> : <Mic className="size-5" />}
        </Button>

        {/* Disconnect / End Call Button */}
        <Button
          variant="destructive"
          size="icon"
          onClick={onDisconnect}
          className="size-11 rounded-full bg-gradient-to-tr from-[#dc2f02] to-rose-600 text-white shadow-lg shadow-rose-950/50 transition-all hover:brightness-110 hover:scale-105 active:scale-95"
          title="Disconnect Voice Session"
        >
          <PhoneOff className="size-5" />
        </Button>
      </div>
    </div>
  )
}

export default VoiceAgentControlBar
