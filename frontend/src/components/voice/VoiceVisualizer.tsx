'use client'

import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'

export type VoiceState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'connecting'
  | 'error'

interface VoiceVisualizerProps {
  state: VoiceState
  volume?: number // 0 to 1
  barCount?: number
  className?: string
  engineLabel?: string
}

export const VoiceVisualizer: React.FC<VoiceVisualizerProps> = ({
  state,
  volume = 0,
  barCount = 15,
  className = '',
  engineLabel
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
            const centerFactor =
              1 - Math.abs(i - (barCount - 1) / 2) / ((barCount - 1) / 2)
            const randomVariation = Math.random() * 32 + 18
            const volMultiplier = Math.max(0.6, volume * 2.4)
            return Math.min(
              76,
              Math.max(
                10,
                (randomVariation * centerFactor + 10) * volMultiplier
              )
            )
          })
        )
      }, 60)
    } else if (state === 'listening') {
      interval = setInterval(() => {
        setAnimatedHeights(
          Array.from({ length: barCount }, (_, i) => {
            const centerFactor =
              1 - Math.abs(i - (barCount - 1) / 2) / ((barCount - 1) / 2)
            const baseWave = Math.sin(Date.now() / 180 + i * 0.45) * 6 + 12
            const volBoost =
              volume > 0.015 ? volume * 75 * (centerFactor * 0.9 + 0.4) : 0
            return Math.min(82, Math.max(8, baseWave + volBoost))
          })
        )
      }, 35)
    } else if (state === 'thinking') {
      interval = setInterval(() => {
        setAnimatedHeights(
          Array.from({ length: barCount }, (_, i) => {
            const wave = (Math.sin(Date.now() / 130 + i * 0.6) + 1) * 14 + 10
            return wave
          })
        )
      }, 45)
    } else {
      // Idle / connecting
      setAnimatedHeights(
        Array.from({ length: barCount }, (_, i) => {
          const wave = Math.sin(Date.now() / 300 + i * 0.35) * 4 + 10
          return wave
        })
      )
    }

    return () => clearInterval(interval)
  }, [state, volume, barCount])

  // Color scheme matching gichogumacharia.tech
  const getBarColor = () => {
    switch (state) {
      case 'speaking':
        return 'bg-gradient-to-t from-[#dc2f02] via-[#e85d04] to-[#faa307] shadow-[0_0_14px_rgba(232,93,4,0.7)]'
      case 'listening':
        return 'bg-gradient-to-t from-[#0284c7] via-[#38bdf8] to-[#67e8f9] shadow-[0_0_14px_rgba(56,189,248,0.7)]'
      case 'thinking':
        return 'bg-gradient-to-t from-[#d97706] via-[#f59e0b] to-[#fde047] shadow-[0_0_14px_rgba(245,158,11,0.7)]'
      case 'connecting':
        return 'bg-gradient-to-t from-zinc-600 via-zinc-400 to-zinc-200 shadow-[0_0_8px_rgba(255,255,255,0.15)]'
      case 'error':
        return 'bg-gradient-to-t from-red-700 to-rose-500 shadow-[0_0_14px_rgba(244,63,94,0.7)]'
      default:
        return 'bg-gradient-to-t from-zinc-700 to-zinc-500'
    }
  }

  const getAuraColor = () => {
    switch (state) {
      case 'speaking':
        return 'from-[#e85d04]/25 via-[#dc2f02]/15 to-transparent border-[#e85d04]/40 shadow-[0_0_50px_rgba(232,93,4,0.3)]'
      case 'listening':
        return 'from-sky-500/25 via-cyan-500/10 to-transparent border-sky-500/40 shadow-[0_0_45px_rgba(56,189,248,0.25)]'
      case 'thinking':
        return 'from-amber-500/25 via-orange-500/15 to-transparent border-amber-500/40 shadow-[0_0_50px_rgba(245,158,11,0.3)]'
      case 'error':
        return 'from-rose-600/25 via-red-500/10 to-transparent border-rose-500/40 shadow-[0_0_45px_rgba(244,63,94,0.3)]'
      default:
        return 'from-zinc-800/30 via-zinc-900/10 to-transparent border-white/10 shadow-[0_0_20px_rgba(255,255,255,0.05)]'
    }
  }

  const getStateText = () => {
    switch (state) {
      case 'speaking':
        return engineLabel ? `${engineLabel} Speaking` : 'Assistant Speaking'
      case 'listening':
        return 'Listening to Microphone'
      case 'thinking':
        return 'Processing Speech...'
      case 'connecting':
        return 'Connecting Voice Session...'
      case 'error':
        return 'Connection Disrupted'
      default:
        return 'Voice Standby'
    }
  }

  return (
    <div
      className={`relative flex flex-col items-center justify-center py-2 ${className}`}
    >
      {/* Visualizer Sphere Stage */}
      <div className="relative flex size-44 items-center justify-center">
        {/* Concentric Ambient Aura Rings */}
        <motion.div
          className={`absolute inset-0 rounded-full border bg-gradient-to-b backdrop-blur-md ${getAuraColor()}`}
          animate={{
            scale:
              state === 'speaking'
                ? [1, 1.12, 1]
                : state === 'listening'
                  ? [1, 1.08, 1]
                  : state === 'thinking'
                    ? [1, 1.05, 1]
                    : 1,
            opacity: state === 'idle' ? 0.35 : 0.95
          }}
          transition={{
            repeat: Infinity,
            duration: state === 'thinking' ? 1.2 : 2.4,
            ease: 'easeInOut'
          }}
        />

        {/* Inner Pulse Ring */}
        <motion.div
          className="absolute inset-4 rounded-full border border-white/10 bg-black/20"
          animate={{
            scale:
              state === 'speaking' || state === 'listening' ? [1, 1.04, 1] : 1
          }}
          transition={{
            repeat: Infinity,
            duration: 1.8,
            ease: 'easeInOut'
          }}
        />

        {/* Central Waveform Bars */}
        <div className="relative z-10 flex h-24 items-center justify-center gap-1.5 px-3">
          {animatedHeights.map((height, i) => (
            <motion.div
              key={i}
              className={`w-2 rounded-full transition-all duration-75 ${getBarColor()}`}
              style={{
                height: `${height}px`,
                minHeight: '8px'
              }}
              layout
            />
          ))}
        </div>
      </div>

      {/* State Label Pill */}
      <div className="relative z-10 mt-3.5 flex justify-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-[#0f172a]/95 px-4 py-1.5 font-mono text-[11px] font-medium uppercase tracking-wider text-zinc-200 shadow-xl backdrop-blur-2xl">
          <span
            className={`size-2 rounded-full ${
              state === 'speaking'
                ? 'animate-pulse bg-[#e85d04] shadow-[0_0_8px_#e85d04]'
                : state === 'listening'
                  ? 'animate-ping bg-sky-400 shadow-[0_0_8px_#38bdf8]'
                  : state === 'thinking'
                    ? 'animate-pulse bg-amber-400 shadow-[0_0_8px_#f59e0b]'
                    : state === 'error'
                      ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e]'
                      : 'bg-zinc-500'
            }`}
          />
          {getStateText()}
        </span>
      </div>
    </div>
  )
}

export default VoiceVisualizer
