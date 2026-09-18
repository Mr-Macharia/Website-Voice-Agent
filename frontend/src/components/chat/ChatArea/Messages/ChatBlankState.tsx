'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { AudioWaveform, Cpu, Terminal, ArrowRight } from 'lucide-react'
import { useStore } from '@/store'
import useAIChatStreamHandler from '@/hooks/useAIStreamHandler'
import { toast } from 'sonner'

const TECH_BADGES = [
  { name: 'RAG', highlight: true },
  { name: 'Voice', highlight: true },
  { name: 'Search', highlight: false },
  { name: 'Booking', highlight: false },
  { name: 'Conversational', highlight: true }
]

// The agent speaks about Gichogu in the third person — it's his assistant, not
// him — so these are phrased the way a visitor would actually ask.
const PROMPT_SUGGESTIONS = [
  {
    icon: Cpu,
    title: 'What he builds',
    desc: 'Projects, the stack he works in, and what he is focused on now.',
    prompt: 'What does Gichogu build, and what is he working on at the moment?'
  },
  {
    icon: Terminal,
    title: 'Experience',
    desc: 'Where he has worked, what he has shipped, and what he is good at.',
    prompt: "What's Gichogu's background and experience with AI systems?"
  },
  {
    icon: AudioWaveform,
    title: 'Get in touch',
    desc: 'Check his availability and book a time, or leave your details.',
    prompt: 'Is Gichogu available for work? I would like to book a chat.'
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
      className="mx-auto flex max-w-4xl flex-col items-center justify-center px-4 py-8 text-center font-main"
      aria-label="Welcome section"
    >
      {/* Kicker Pill */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="mb-4 inline-flex items-center gap-2 rounded-full border border-[#e85d04]/30 bg-[#e85d04]/10 px-4 py-1.5 font-mono text-xs font-semibold uppercase tracking-wider text-[#f48c06] shadow-sm shadow-orange-950/20"
      >
        <span className="size-2 animate-pulse rounded-full bg-[#22c55e]" />
        <span>AI/ML Engineer • Conversational Portfolio</span>
      </motion.div>

      {/* Hero Title */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="mb-6 space-y-3"
      >
        <h1 className="font-large text-4xl font-black leading-tight tracking-tight text-white sm:text-5xl lg:text-6xl">
          Gichogu <span className="accent-gradient-text">Macharia</span>
        </h1>
        <p className="mx-auto max-w-2xl text-sm leading-relaxed text-zinc-400 sm:text-base">
          A portfolio you can actually talk to. Ask Clyde about my work, my
          projects, or book a time — by text or by voice.
        </p>
      </motion.div>

      {/* Tech Stack Badges */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, delay: 0.2 }}
        className="mb-8 flex max-w-2xl flex-wrap items-center justify-center gap-2"
      >
        {TECH_BADGES.map((b, i) => (
          <span
            key={i}
            className={`rounded-full border px-3 py-1 font-mono text-xs transition-all ${
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
        className="grid w-full grid-cols-1 gap-3.5 text-left sm:grid-cols-3"
      >
        {PROMPT_SUGGESTIONS.map((card, i) => {
          const IconComponent = card.icon
          return (
            <button
              key={i}
              onClick={() => handleSuggestionClick(card.prompt)}
              className="glass-panel-interactive group flex cursor-pointer flex-col justify-between rounded-2xl bg-[#0f172a]/60 p-4 text-left transition-all hover:scale-[1.02] active:scale-[0.99]"
            >
              <div>
                <div className="mb-3 flex size-8 items-center justify-center rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] text-white shadow-md shadow-orange-950/40 transition-transform group-hover:rotate-6">
                  <IconComponent className="size-4" />
                </div>
                <h3 className="mb-1 font-large text-sm font-bold text-white transition-colors group-hover:text-[#f48c06]">
                  {card.title}
                </h3>
                <p className="text-xs leading-relaxed text-zinc-400">
                  {card.desc}
                </p>
              </div>

              <div className="mt-4 flex items-center gap-1 font-mono text-[11px] text-zinc-500 transition-colors group-hover:text-orange-400">
                <span>Ask prompt</span>
                <ArrowRight className="size-3 transition-transform group-hover:translate-x-1" />
              </div>
            </button>
          )
        })}
      </motion.div>
    </section>
  )
}

export default ChatBlankState
