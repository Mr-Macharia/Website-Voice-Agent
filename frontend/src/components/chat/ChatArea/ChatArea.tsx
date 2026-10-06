'use client'

import { stripToolPayload } from '@/lib/toolPayload'
import { DEFAULT_AGENT_NAME } from '@/lib/agentIdentity'
import React, { useState } from 'react'
import ChatInput from './ChatInput'
import MessageArea from './MessageArea'
import { useStore } from '@/store'
import { useQueryState } from 'nuqs'
import { Mic, Trash2, Copy, Check, Sparkles, Menu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import VoiceModal from '@/components/voice/VoiceModal'
import useChatActions from '@/hooks/useChatActions'
import { toast } from 'sonner'

const ChatAreaHeader = () => {
  const { agents, selectedModel, messages } = useStore()
  const [agentId] = useQueryState('agent')
  const [teamId] = useQueryState('team')
  const { clearChat } = useChatActions()
  const [isVoiceOpen, setIsVoiceOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const isMenuOpen = useStore((state) => state.isMobileSidebarOpen)
  const setMenuOpen = useStore((state) => state.setMobileSidebarOpen)

  const activeAgent = agents.find((a) => a.id === agentId)
  const agentName =
    activeAgent?.name || (teamId ? `Team: ${teamId}` : DEFAULT_AGENT_NAME)

  const copyFullConversation = () => {
    if (messages.length === 0) {
      toast.info('No messages in this chat yet')
      return
    }
    const formatted = messages
      .map(
        (m) =>
          `${m.role === 'user' ? 'You' : agentName}: ${stripToolPayload(m.content)}`
      )
      .join('\n\n')
    navigator.clipboard.writeText(formatted)
    setCopied(true)
    toast.success('Conversation copied to clipboard!')
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <>
      <header className="z-10 flex items-center justify-between border-b border-white/5 bg-[#0f172a]/50 px-3 pt-[max(0.75rem,env(safe-area-inset-top))] pb-3 backdrop-blur-xl sm:px-6">
        {/* Left: Active Agent & Model Indicator */}
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            aria-expanded={isMenuOpen}
            className="-ml-2 flex size-11 shrink-0 items-center justify-center rounded-xl text-zinc-300 transition-colors hover:bg-white/5 hover:text-white lg:hidden"
          >
            <Menu className="size-5" />
          </button>
          <div className="flex size-8 items-center justify-center rounded-xl bg-linear-to-tr from-brand to-accentGold text-white shadow-md shadow-orange-950/40">
            <Sparkles className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-large text-sm font-bold text-white">
                {agentName}
              </span>
              <span className="flex items-center gap-1 rounded-full border border-positive/30 bg-positive/10 px-2 py-0.5 font-mono text-[10px] text-positive">
                <span className="size-1.5 animate-pulse rounded-full bg-positive" />
                Live
              </span>
            </div>
            <div className="flex min-w-0 items-center gap-2 font-mono text-[11px] text-zinc-400">
              <span className="truncate">
                {selectedModel || 'grok-4.20-non-reasoning'}
              </span>
              <span>•</span>
              <span className="truncate text-orange-400/90">
                Gichogu&apos;s AI assistant
              </span>
            </div>
          </div>
        </div>

        {/* Right: Quick Action Controls */}
        <div className="flex shrink-0 items-center gap-2">
          {messages.length > 0 && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={copyFullConversation}
                className="h-11 min-w-11 gap-1.5 rounded-xl border-white/10 bg-white/5 px-3 font-mono text-xs text-zinc-300 transition-all hover:bg-white/10 hover:text-white lg:h-8 lg:min-w-0"
                title="Copy full chat transcript"
              >
                {copied ? (
                  <Check className="size-3 text-positive" />
                ) : (
                  <Copy className="size-3" />
                )}
                <span className="hidden sm:inline">
                  {copied ? 'Copied' : 'Export'}
                </span>
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={clearChat}
                className="h-11 min-w-11 gap-1.5 rounded-xl border-white/10 bg-white/5 px-3 font-mono text-xs text-zinc-400 transition-all hover:border-rose-500/30 hover:bg-rose-500/10 hover:text-rose-300 lg:h-8 lg:min-w-0"
                title="Clear current chat"
              >
                <Trash2 className="size-3" />
                <span className="hidden sm:inline">Clear</span>
              </Button>
            </>
          )}

          {/* Direct Live Voice Assistant Button */}
          <Button
            size="sm"
            onClick={() => setIsVoiceOpen(true)}
            aria-label="Voice mode"
            className="h-11 min-w-11 gap-1.5 rounded-xl border border-brand/50 bg-linear-to-r from-brand to-accentGold px-3.5 font-mono text-xs font-semibold text-white shadow-md shadow-orange-950/40 transition-all hover:brightness-110 active:scale-95 lg:h-8 lg:min-w-0"
          >
            <Mic className="size-3.5 animate-pulse" />
            <span className="hidden sm:inline">Voice Mode</span>
          </Button>
        </div>
      </header>

      {/* Voice Assistant Modal */}
      <VoiceModal
        isOpen={isVoiceOpen}
        onClose={() => setIsVoiceOpen(false)}
        agentName={agentName}
      />
    </>
  )
}

const ChatArea = () => {
  return (
    <main className="relative flex h-dvh min-w-0 grow flex-col overflow-hidden bg-background/40 font-main">
      <ChatAreaHeader />
      <div className="flex flex-1 flex-col overflow-hidden">
        <MessageArea />
      </div>
      <div className="pt-1 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        <ChatInput />
      </div>
    </main>
  )
}

export default ChatArea
