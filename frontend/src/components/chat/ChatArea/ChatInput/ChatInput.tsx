'use client'
import { useState } from 'react'
import { toast } from 'sonner'
import { TextArea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { useStore } from '@/store'
import useAIChatStreamHandler from '@/hooks/useAIStreamHandler'
import { useQueryState } from 'nuqs'
import Icon from '@/components/ui/icon'
import { Mic, Sparkles } from 'lucide-react'
import LiveKitVoiceModal from '@/components/voice/LiveKitVoiceModal'

const ChatInput = () => {
  const { chatInputRef, agents } = useStore()

  const { handleStreamResponse } = useAIChatStreamHandler()
  const [selectedAgent] = useQueryState('agent')
  const [teamId] = useQueryState('team')
  const [inputMessage, setInputMessage] = useState('')
  const [isVoiceOpen, setIsVoiceOpen] = useState(false)
  const isStreaming = useStore((state) => state.isStreaming)

  const activeAgentName =
    agents.find((a) => a.id === selectedAgent)?.name || 'Realtime Voice Assistant'

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
      <div className="relative mx-auto flex w-full max-w-3xl flex-col items-center font-main px-4">
        {/* Floating Glass Input Bar */}
        <div className="relative flex w-full items-end justify-center gap-x-2 rounded-2xl border border-white/10 bg-[#0f172a]/80 p-2 backdrop-blur-2xl shadow-2xl transition-all focus-within:border-[#e85d04]/60 focus-within:ring-2 focus-within:ring-[#e85d04]/20">
          <div className="relative flex-1">
            <TextArea
              placeholder={'Ask anything, execute tools, or click Voice Mode...'}
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
              className="w-full bg-transparent px-3 py-2 text-sm text-white placeholder:text-zinc-500 focus:outline-none resize-none min-h-[44px] max-h-36 border-none"
              disabled={!(selectedAgent || teamId)}
              ref={chatInputRef}
            />
          </div>

          {/* LiveKit / Deepgram Voice Assistant Button */}
          <Button
            onClick={() => setIsVoiceOpen(true)}
            type="button"
            size="icon"
            title="Start Realtime Voice Session (Deepgram Flux)"
            className="size-10 rounded-xl border border-[#e85d04]/40 bg-gradient-to-tr from-[#e85d04]/20 to-[#f48c06]/20 p-0 text-[#f48c06] hover:bg-[#e85d04]/30 hover:text-white hover:border-[#e85d04] transition-all shadow-md shadow-orange-950/40 shrink-0"
          >
            <Mic className="size-4 animate-pulse" />
          </Button>

          {/* Text Send Button */}
          <Button
            onClick={handleSubmit}
            disabled={
              !(selectedAgent || teamId) || !inputMessage.trim() || isStreaming
            }
            size="icon"
            className="size-10 rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] p-0 text-white hover:brightness-110 disabled:opacity-30 disabled:brightness-100 transition-all shadow-md shadow-orange-950/40 shrink-0"
          >
            <Icon type="send" color="white" />
          </Button>
        </div>

        {/* Input Helper Hint */}
        <div className="mt-2 flex w-full items-center justify-between px-2 text-[10px] font-mono text-zinc-500">
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-white/10 bg-white/5 px-1 py-0.5 text-zinc-400">Enter</kbd> to send
            </span>
            <span>•</span>
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-white/10 bg-white/5 px-1 py-0.5 text-zinc-400">Shift+Enter</kbd> new line
            </span>
          </div>
          <div className="flex items-center gap-1 text-[#f48c06]/80 hidden sm:flex">
            <Sparkles className="size-2.5" />
            <span>Deepgram Flux & Agno AgentOS</span>
          </div>
        </div>
      </div>

      {/* Voice Assistant Modal */}
      <LiveKitVoiceModal
        isOpen={isVoiceOpen}
        onClose={() => setIsVoiceOpen(false)}
        agentName={activeAgentName}
      />
    </>
  )
}

export default ChatInput
