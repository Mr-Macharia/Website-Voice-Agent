'use client'

import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'connecting' | 'error'

interface VoiceVisualizerProps {
  state: VoiceState
  volume?: number // 0 to 1
  barCount?: number
  className?: string
}

export const VoiceVisualizer: React.FC<VoiceVisualizerProps> = ({
  state,
  volume = 0,
  barCount = 11,
  className = ''
}) => {
  const [animatedHeights, setAnimatedHeights] = useState<number[]>(
    Array(barCount).fill(12)
  )

  useEffect(() => {
    let interval: NodeJS.Timeout

    if (state === 'speaking') {
      interval = setInterval(() => {
        setAnimatedHeights(
          Array.from({ length: barCount }, (_, i) => {
            const centerFactor = 1 - Math.abs(i - (barCount - 1) / 2) / ((barCount - 1) / 2)
            const randomVariation = Math.random() * 32 + 18
            const volMultiplier = Math.max(0.5, volume * 2.2)
            return Math.min(80, Math.max(12, (randomVariation * centerFactor + 12) * volMultiplier))
          })
        )
      }, 70)
    } else if (state === 'listening') {
      interval = setInterval(() => {
        setAnimatedHeights(
          Array.from({ length: barCount }, (_, i) => {
            const centerFactor = 1 - Math.abs(i - (barCount - 1) / 2) / ((barCount - 1) / 2)
            const baseWave = Math.sin(Date.now() / 200 + i * 0.6) * 6 + 14
            const volBoost = volume > 0.02 ? volume * 75 * (centerFactor * 0.8 + 0.5) : 0
            return Math.min(88, Math.max(10, baseWave + volBoost))
          })
        )
      }, 35)
    } else if (state === 'thinking') {
      interval = setInterval(() => {
        setAnimatedHeights(
          Array.from({ length: barCount }, (_, i) => {
            const wave = (Math.sin(Date.now() / 140 + i * 0.8) + 1) * 14 + 10
            return wave
          })
        )
      }, 50)
    } else {
      // Idle / connecting
      setAnimatedHeights(Array(barCount).fill(10))
    }

    return () => clearInterval(interval)
  }, [state, volume, barCount])

  // Color scheme matching gichogumacharia.tech
  const getBarColor = () => {
    switch (state) {
      case 'speaking':
        return 'bg-gradient-to-t from-[#dc2f02] via-[#e85d04] to-[#faa307] shadow-[0_0_16px_rgba(232,93,4,0.8)]'
      case 'listening':
        return 'bg-gradient-to-t from-[#0284c7] via-[#38bdf8] to-[#67e8f9] shadow-[0_0_14px_rgba(56,189,248,0.7)]'
      case 'thinking':
        return 'bg-gradient-to-t from-[#e85d04] via-[#f59e0b] to-[#fde047] shadow-[0_0_14px_rgba(245,158,11,0.8)]'
      case 'connecting':
        return 'bg-gradient-to-t from-zinc-700 to-zinc-500 shadow-[0_0_8px_rgba(255,255,255,0.2)]'
      case 'error':
        return 'bg-gradient-to-t from-red-700 to-rose-500 shadow-[0_0_14px_rgba(244,63,94,0.7)]'
      default:
        return 'bg-zinc-700'
    }
  }

  const getAuraColor = () => {
    switch (state) {
      case 'speaking':
        return 'from-[#e85d04]/25 via-[#dc2f02]/15 to-transparent border-[#e85d04]/40 shadow-[0_0_40px_rgba(232,93,4,0.3)]'
      case 'listening':
        return 'from-sky-500/20 via-cyan-500/10 to-transparent border-sky-500/30 shadow-[0_0_35px_rgba(56,189,248,0.25)]'
      case 'thinking':
        return 'from-amber-500/25 via-orange-500/15 to-transparent border-amber-500/40 shadow-[0_0_40px_rgba(245,158,11,0.3)]'
      default:
        return 'from-zinc-800/20 to-transparent border-white/5'
    }
  }

  return (
    <div className={`relative flex flex-col items-center justify-center p-8 ${className}`}>
      {/* Outer Pulse Glow Aura */}
      <motion.div
        className={`absolute size-48 rounded-full bg-gradient-to-b border backdrop-blur-sm ${getAuraColor()}`}
        animate={{
          scale: state === 'speaking' ? [1, 1.18, 1] : state === 'listening' ? [1, 1.1, 1] : 1,
          opacity: state === 'idle' ? 0.2 : 0.85
        }}
        transition={{
          repeat: Infinity,
          duration: state === 'thinking' ? 1.1 : 2.2,
          ease: 'easeInOut'
        }}
      />

      {/* Central Visualizer Bars */}
      <div className="relative z-10 flex h-28 items-center justify-center gap-1.5 px-6">
        {animatedHeights.map((height, i) => (
          <motion.div
            key={i}
            className={`w-2.5 rounded-full transition-all duration-75 ${getBarColor()}`}
            style={{
              height: `${height}px`,
              minHeight: '10px'
            }}
            layout
          />
        ))}
      </div>

      {/* State label badge */}
      <div className="relative z-10 mt-4">
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-[#0f172a]/90 px-4 py-1.5 text-xs font-mono tracking-wider uppercase text-zinc-200 backdrop-blur-xl shadow-lg">
          <span
            className={`size-2 rounded-full ${
              state === 'speaking'
                ? 'bg-[#e85d04] shadow-[0_0_8px_#e85d04] animate-pulse'
                : state === 'listening'
                ? 'bg-sky-400 shadow-[0_0_8px_#38bdf8] animate-ping'
                : state === 'thinking'
                ? 'bg-amber-400 shadow-[0_0_8px_#f59e0b] animate-pulse'
                : 'bg-zinc-500'
            }`}
          />
          {state === 'speaking'
            ? 'Deepgram Flux Speaking'
            : state === 'listening'
            ? 'Listening to Microphone'
            : state === 'thinking'
            ? 'Deepgram & Agno Thinking'
            : state === 'connecting'
            ? 'Connecting Voice Bridge'
            : 'Voice Standby'}
        </span>
      </div>
    </div>
  )
}

export default VoiceVisualizer
