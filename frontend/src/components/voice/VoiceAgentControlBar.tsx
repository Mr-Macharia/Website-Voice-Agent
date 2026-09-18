'use client'

import React from 'react'
import { Button } from '@/components/ui/button'
import { Mic, MicOff, PhoneOff, Sparkles, Zap, Radio } from 'lucide-react'

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
  agentName = 'Clyde',
  mode = 'Portfolio voice agent'
}) => {
  const isLiveKit = mode.toLowerCase().includes('livekit')

  return (
    <div className="flex w-full items-center justify-between border-t border-white/10 bg-[#0a0f1e]/95 px-6 py-3.5 backdrop-blur-2xl">
      {/* Agent Info & Connection Status */}
      <div className="flex items-center gap-3">
        <div className="relative flex size-10 items-center justify-center rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] text-white shadow-lg shadow-orange-950/40 ring-1 ring-white/20">
          <Sparkles className="size-4.5" />
          <span className="absolute -bottom-0.5 -right-0.5 flex size-2.5">
            <span
              className={`size-full rounded-full ${
                isConnected
                  ? 'animate-ping bg-emerald-400 opacity-75'
                  : 'bg-amber-400'
              }`}
            />
            <span
              className={`absolute inset-0 size-2.5 rounded-full ${
                isConnected ? 'bg-emerald-500' : 'bg-amber-500'
              }`}
            />
          </span>
        </div>

        <div className="flex flex-col">
          <div className="text-sm font-semibold tracking-tight text-white">
            {agentName}
          </div>
          <div className="flex items-center gap-1.5 font-mono text-[11px] text-zinc-400">
            {isLiveKit ? (
              <Radio className="size-3 text-sky-400" />
            ) : (
              <Zap className="size-3 text-[#f48c06]" />
            )}
            <span className="text-zinc-300">
              {isConnected ? mode : 'Connecting...'}
            </span>
          </div>
        </div>
      </div>

      {/* Main Control Actions */}
      <div className="flex items-center gap-2.5">
        {/* Mute / Unmute Button */}
        <Button
          variant="outline"
          size="icon"
          onClick={onToggleMute}
          disabled={!isConnected}
          className={`size-10 rounded-full border transition-all ${
            isMuted
              ? 'border-rose-500/50 bg-rose-500/20 text-rose-300 shadow-md shadow-rose-950/40 hover:bg-rose-500/30'
              : 'border-white/10 bg-white/5 text-zinc-200 hover:border-white/20 hover:bg-white/10 hover:text-white'
          }`}
          title={isMuted ? 'Unmute Microphone' : 'Mute Microphone'}
        >
          {isMuted ? (
            <MicOff className="size-4.5 text-rose-400" />
          ) : (
            <Mic className="size-4.5 text-zinc-200" />
          )}
        </Button>

        {/* Disconnect / End Session Button */}
        <Button
          variant="destructive"
          size="icon"
          onClick={onDisconnect}
          className="size-10 rounded-full bg-gradient-to-tr from-[#dc2f02] to-rose-600 text-white shadow-lg shadow-rose-950/60 transition-all hover:scale-105 hover:brightness-110 active:scale-95"
          title="End Voice Session"
        >
          <PhoneOff className="size-4.5" />
        </Button>
      </div>
    </div>
  )
}

export default VoiceAgentControlBar
