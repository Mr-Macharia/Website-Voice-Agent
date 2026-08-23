'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { AudioWaveform, Cpu, Terminal, ArrowRight } from 'lucide-react'
import { useStore } from '@/store'
import useAIChatStreamHandler from '@/hooks/useAIStreamHandler'
import { toast } from 'sonner'

const TECH_BADGES = [
  { name: 'Deepgram Flux TTS', highlight: true },
  { name: 'Deepgram Nova-3 STT', highlight: true },
  { name: 'Agno AgentOS', highlight: false },
  { name: 'Grok xAI / GPT-4o', highlight: false },
  { name: 'Low-Latency WebSocket', highlight: true },
  { name: 'Next.js & Web Audio', highlight: false }
]

const PROMPT_SUGGESTIONS = [
  {
    icon: AudioWaveform,
    title: 'Realtime Voice Agent',
    desc: 'Launch a voice conversation with ultra-low latency Deepgram Flux TTS.',
    prompt: 'Tell me about how your realtime voice bridge works with Deepgram Flux and Agno.'
  },
  {
    icon: Cpu,
    title: 'AI Systems & Architecture',
    desc: 'Ask about full-stack ML pipelines, streaming APIs, and agentic workflows.',
    prompt: 'Explain the architecture for building low-latency conversational voice assistants.'
  },
  {
    icon: Terminal,
    title: 'Code & Tool Execution',
    desc: 'Run research queries, duckduckgo web search, and data processing.',
    prompt: 'Search the web for the latest breakthroughs in AI voice synthesis.'
  }
]

const ChatBlankState = () => {
  const { handleStreamResponse } = useAIChatStreamHandler()
  const isStreaming = useStore((state) => state.isStreaming)

  const handleSuggestionClick = async (prompt: string) => {
    if (isStreaming) return
    try {
      await handleStreamResponse(prompt)
    } catch {
      toast.error('Failed to send prompt')
    }
  }

  return (
    <section
      className="flex flex-col items-center justify-center text-center font-main px-4 py-8 max-w-4xl mx-auto"
      aria-label="Welcome section"
    >
      {/* Kicker Pill */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="mb-4 inline-flex items-center gap-2 rounded-full border border-[#e85d04]/30 bg-[#e85d04]/10 px-4 py-1.5 text-xs font-mono font-semibold uppercase tracking-wider text-[#f48c06] shadow-sm shadow-orange-950/20"
      >
        <span className="size-2 rounded-full bg-[#22c55e] animate-pulse" />
        <span>AI/ML Engineer • Realtime Voice Agent OS</span>
      </motion.div>

      {/* Hero Title */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="space-y-3 mb-6"
      >
        <h1 className="font-large text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight text-white leading-tight">
          Gichogu <span className="accent-gradient-text">Macharia</span>
        </h1>
        <p className="text-zinc-400 text-sm sm:text-base max-w-2xl mx-auto leading-relaxed">
          Building intelligent systems, conversational voice agents powered by Deepgram Flux & Nova-3, and multi-agent workflows with Agno.
        </p>
      </motion.div>

      {/* Tech Stack Badges */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, delay: 0.2 }}
        className="flex flex-wrap items-center justify-center gap-2 mb-8 max-w-2xl"
      >
        {TECH_BADGES.map((b, i) => (
          <span
            key={i}
            className={`font-mono text-xs px-3 py-1 rounded-full border transition-all ${
              b.highlight
                ? 'border-[#e85d04]/40 bg-[#e85d04]/10 text-orange-300'
                : 'border-white/10 bg-white/5 text-zinc-400'
            }`}
          >
            {b.name}
          </span>
        ))}
      </motion.div>

      {/* Suggested Prompt Cards */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.3 }}
        className="grid grid-cols-1 sm:grid-cols-3 gap-3.5 w-full text-left"
      >
        {PROMPT_SUGGESTIONS.map((card, i) => {
          const IconComponent = card.icon
          return (
            <button
              key={i}
              onClick={() => handleSuggestionClick(card.prompt)}
              className="glass-panel-interactive p-4 rounded-2xl flex flex-col justify-between group text-left cursor-pointer hover:scale-[1.02] active:scale-[0.99] transition-all bg-[#0f172a]/60"
            >
              <div>
                <div className="size-8 rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] flex items-center justify-center mb-3 shadow-md shadow-orange-950/40 text-white group-hover:rotate-6 transition-transform">
                  <IconComponent className="size-4" />
                </div>
                <h3 className="font-large font-bold text-sm text-white mb-1 group-hover:text-[#f48c06] transition-colors">
                  {card.title}
                </h3>
                <p className="text-xs text-zinc-400 leading-relaxed">
                  {card.desc}
                </p>
              </div>

              <div className="mt-4 flex items-center gap-1 text-[11px] font-mono text-zinc-500 group-hover:text-orange-400 transition-colors">
                <span>Ask prompt</span>
                <ArrowRight className="size-3 group-hover:translate-x-1 transition-transform" />
              </div>
            </button>
          )
        })}
      </motion.div>
    </section>
  )
}

export default ChatBlankState
