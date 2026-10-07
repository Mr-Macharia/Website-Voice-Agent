'use client'
import { useState } from 'react'
import { toast } from 'sonner'
import { TextArea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { useStore } from '@/store'
import { DEFAULT_AGENT_NAME } from '@/lib/agentIdentity'
import useAIChatStreamHandler, {
  stopStreaming
} from '@/hooks/useAIStreamHandler'
import { useQueryState } from 'nuqs'
import Icon from '@/components/ui/icon'
import { Mic, Sparkles, Square } from 'lucide-react'
import VoiceModal from '@/components/voice/VoiceModal'

const ChatInput = () => {
  const { chatInputRef, agents } = useStore()

  const { handleStreamResponse } = useAIChatStreamHandler()
  const [selectedAgent] = useQueryState('agent')
  const [teamId] = useQueryState('team')
  const [inputMessage, setInputMessage] = useState('')
  const [isVoiceOpen, setIsVoiceOpen] = useState(false)
  const isStreaming = useStore((state) => state.isStreaming)

  const activeAgentName =
    agents.find((a) => a.id === selectedAgent)?.name || DEFAULT_AGENT_NAME

  const handleSubmit = async () => {
    if (!inputMessage.trim()) return

    const currentMessage = inputMessage
    setInputMessage('')

    try {
      await handleStreamResponse(currentMessage)
    } catch (error) {
      toast.error(
        `Error in handleSubmit: ${
          error instanceof Error ? error.message : String(error)
        }`
      )
    }
  }

  return (
    <>
      <div className="relative mx-auto flex w-full max-w-3xl flex-col items-center px-3 font-main sm:px-4">
        {/* Floating Glass Input Bar */}
        <div className="relative flex w-full items-end justify-center gap-x-2 rounded-2xl border border-white/10 bg-[#0f172a]/80 p-2 shadow-2xl backdrop-blur-2xl transition-all focus-within:border-brand/60 focus-within:ring-2 focus-within:ring-brand/20">
          <div className="relative flex-1">
            <TextArea
              placeholder={
                'Ask anything, execute tools, or click Voice Mode...'
              }
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === 'Enter' &&
                  !e.nativeEvent.isComposing &&
                  !e.shiftKey &&
                  !isStreaming
                ) {
                  e.preventDefault()
                  handleSubmit()
                }
              }}
              className="max-h-36 min-h-[44px] w-full resize-none border-none bg-transparent px-3 py-2 text-base text-white placeholder:text-zinc-500 focus:outline-hidden lg:text-sm"
              disabled={!(selectedAgent || teamId)}
              ref={chatInputRef}
            />
          </div>

          {/* Voice session button */}
          <Button
            onClick={() => setIsVoiceOpen(true)}
            type="button"
            size="icon"
            title="Talk to Clyde"
            aria-label="Start voice session"
            className="size-11 shrink-0 rounded-xl border border-brand/40 bg-transparent bg-linear-to-tr from-brand/20 to-accentGold/20 p-0 text-accentGold shadow-md shadow-orange-950/40 transition-all hover:border-brand hover:bg-brand/30 hover:text-white lg:size-10"
          >
            <Mic className="size-4 animate-pulse" />
          </Button>

          {/* Send, or Stop while a reply streams (pattern from assistant-ui) */}
          {isStreaming ? (
            <Button
              onClick={stopStreaming}
              aria-label="Stop generating"
              size="icon"
              className="size-11 shrink-0 rounded-xl border border-white/15 bg-white/10 p-0 text-white transition-all hover:bg-white/20 lg:size-10"
            >
              <Square className="size-3.5 fill-current" aria-hidden="true" />
            </Button>
          ) : (
            <Button
              onClick={handleSubmit}
              aria-label="Send message"
              disabled={!(selectedAgent || teamId) || !inputMessage.trim()}
              size="icon"
              className="size-11 shrink-0 rounded-xl bg-linear-to-tr from-brand to-accentGold p-0 text-white shadow-md shadow-orange-950/40 transition-all hover:brightness-110 disabled:opacity-30 disabled:brightness-100 lg:size-10"
            >
              <Icon type="send" color="white" />
            </Button>
          )}
        </div>

        {/* Input Helper Hint */}
        <div className="mt-2 hidden w-full items-center justify-between px-2 font-mono text-[10px] text-zinc-500 [@media(hover:hover)]:flex">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1">
              <kbd className="rounded-sm border border-white/10 bg-white/5 px-1 py-0.5 text-zinc-400">
                Enter
              </kbd>{' '}
              to send
            </span>
            <span>•</span>
            <span className="flex items-center gap-1">
              <kbd className="rounded-sm border border-white/10 bg-white/5 px-1 py-0.5 text-zinc-400">
                Shift+Enter
              </kbd>{' '}
              new line
            </span>
          </div>
          <div className="flex hidden items-center gap-1 text-accentGold/80 sm:flex">
            <Sparkles className="size-2.5" />
            <span>Ask Clyde anything</span>
          </div>
        </div>
      </div>

      {/* Voice Assistant Modal */}
      <VoiceModal
        isOpen={isVoiceOpen}
        onClose={() => setIsVoiceOpen(false)}
        agentName={activeAgentName}
      />
    </>
  )
}

export default ChatInput
