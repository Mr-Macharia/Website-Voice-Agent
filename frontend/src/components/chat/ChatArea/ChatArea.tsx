'use client'

import React, { useState } from 'react'
import ChatInput from './ChatInput'
import MessageArea from './MessageArea'
import { useStore } from '@/store'
import { useQueryState } from 'nuqs'
import { Mic, Trash2, Copy, Check, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import LiveKitVoiceModal from '@/components/voice/LiveKitVoiceModal'
import useChatActions from '@/hooks/useChatActions'
import { toast } from 'sonner'

const ChatAreaHeader = () => {
  const { agents, selectedModel, messages } = useStore()
  const [agentId] = useQueryState('agent')
  const [teamId] = useQueryState('team')
  const { clearChat } = useChatActions()
  const [isVoiceOpen, setIsVoiceOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const activeAgent = agents.find((a) => a.id === agentId)
  const agentName = activeAgent?.name || (teamId ? `Team: ${teamId}` : 'Realtime Voice Assistant')

  const copyFullConversation = () => {
    if (messages.length === 0) {
      toast.info('No messages in this chat yet')
      return
    }
    const formatted = messages
      .map((m) => `${m.role === 'user' ? 'You' : agentName}: ${m.content}`)
      .join('\n\n')
    navigator.clipboard.writeText(formatted)
    setCopied(true)
    toast.success('Conversation copied to clipboard!')
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <>
      <header className="flex items-center justify-between border-b border-white/5 bg-[#0f172a]/50 px-6 py-3 backdrop-blur-xl z-10">
        {/* Left: Active Agent & Model Indicator */}
        <div className="flex items-center gap-3">
          <div className="size-8 rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] flex items-center justify-center text-white shadow-md shadow-orange-950/40">
            <Sparkles className="size-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-large font-bold text-sm text-white">{agentName}</span>
              <span className="flex items-center gap-1 rounded-full border border-[#22c55e]/30 bg-[#22c55e]/10 px-2 py-0.5 text-[10px] font-mono text-[#22c55e]">
                <span className="size-1.5 rounded-full bg-[#22c55e] animate-pulse" />
                Live
              </span>
            </div>
            <div className="flex items-center gap-2 text-[11px] font-mono text-zinc-400">
              <span>{selectedModel || 'grok-4.20-non-reasoning'}</span>
              <span>•</span>
              <span className="text-orange-400/90">Deepgram Flux 24kHz</span>
            </div>
          </div>
        </div>

        {/* Right: Quick Action Controls */}
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={copyFullConversation}
                className="h-8 gap-1.5 rounded-xl border-white/10 bg-white/5 px-3 text-xs font-mono text-zinc-300 hover:bg-white/10 hover:text-white transition-all"
                title="Copy full chat transcript"
              >
                {copied ? <Check className="size-3 text-[#22c55e]" /> : <Copy className="size-3" />}
                <span className="hidden sm:inline">{copied ? 'Copied' : 'Export'}</span>
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={clearChat}
                className="h-8 gap-1.5 rounded-xl border-white/10 bg-white/5 px-3 text-xs font-mono text-zinc-400 hover:bg-rose-500/10 hover:border-rose-500/30 hover:text-rose-300 transition-all"
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
            className="h-8 gap-1.5 rounded-xl border border-[#e85d04]/50 bg-gradient-to-r from-[#e85d04] to-[#f48c06] px-3.5 text-xs font-mono font-semibold text-white shadow-md shadow-orange-950/40 hover:brightness-110 active:scale-95 transition-all"
          >
            <Mic className="size-3.5 animate-pulse" />
            <span>Voice Mode</span>
          </Button>
        </div>
      </header>

      {/* Voice Assistant Modal */}
      <LiveKitVoiceModal
        isOpen={isVoiceOpen}
        onClose={() => setIsVoiceOpen(false)}
        agentName={agentName}
      />
    </>
  )
}

const ChatArea = () => {
  return (
    <main className="relative flex flex-grow flex-col h-screen overflow-hidden bg-[#0a0f1e]/40 font-main">
      <ChatAreaHeader />
      <div className="flex-1 overflow-hidden flex flex-col">
        <MessageArea />
      </div>
      <div className="pb-3 pt-1">
        <ChatInput />
      </div>
    </main>
  )
}

export default ChatArea
