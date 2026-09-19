'use client'
import { Button } from '@/components/ui/button'
import useChatActions from '@/hooks/useChatActions'
import { useStore } from '@/store'
import { DEFAULT_AGENT_NAME } from '@/lib/agentIdentity'
import { motion } from 'framer-motion'
import { useState, useEffect } from 'react'
import Icon from '@/components/ui/icon'
import Sessions from './Sessions'
import { useQueryState } from 'nuqs'
import { Mic, Sparkles } from 'lucide-react'
import VoiceModal from '@/components/voice/VoiceModal'

const SidebarHeader = () => (
  <div className="flex items-center gap-2.5 px-1 py-1">
    <div className="flex size-8 items-center justify-center rounded-xl bg-gradient-to-tr from-[#e85d04] via-[#f48c06] to-[#dc2f02] shadow-lg shadow-orange-950/50 ring-1 ring-white/20">
      <span className="font-mono text-xs font-black tracking-tighter text-white">
        GM
      </span>
    </div>
    <div className="flex min-w-0 flex-col">
      <span className="truncate font-large text-xs font-bold tracking-tight text-white">
        Gichogu Macharia
      </span>
      <span className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-[#f48c06]">
        <Sparkles className="inline size-2.5" /> AI/ML Engineer
      </span>
    </div>
  </div>
)

const NewChatButton = ({
  disabled,
  onClick
}: {
  disabled: boolean
  onClick: () => void
}) => (
  <Button
    onClick={onClick}
    disabled={disabled}
    size="lg"
    className="h-9 w-full rounded-xl border border-white/10 bg-white/10 text-xs font-medium text-white shadow-sm transition-all hover:border-white/20 hover:bg-white/15"
  >
    <Icon type="plus-icon" size="xs" className="text-white" />
    <span className="font-mono text-[11px] uppercase tracking-wider">
      New Chat
    </span>
  </Button>
)

const LiveVoiceButton = ({ onClick }: { onClick: () => void }) => (
  <Button
    onClick={onClick}
    size="lg"
    className="group relative h-10 w-full overflow-hidden rounded-xl border border-[#e85d04]/40 bg-gradient-to-r from-[#e85d04]/20 via-[#f48c06]/15 to-[#dc2f02]/20 text-xs font-semibold text-orange-200 shadow-lg shadow-orange-950/40 transition-all hover:border-[#e85d04] hover:bg-[#e85d04]/30"
  >
    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
    <Mic className="size-4 animate-pulse text-[#f48c06] transition-transform group-hover:scale-110" />
    <span className="font-mono text-[11px] uppercase tracking-wider text-white">
      Live Voice Agent
    </span>
  </Button>
)

const Sidebar = () => {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [isVoiceModalOpen, setIsVoiceModalOpen] = useState(false)
  const { clearChat, focusChatInput, initialize } = useChatActions()
  const {
    messages,
    selectedEndpoint,
    isEndpointActive,
    hydrated,
    agents,
    mode
  } = useStore()
  const [isMounted, setIsMounted] = useState(false)
  const [agentId] = useQueryState('agent')

  const activeAgentName =
    agents.find((a) => a.id === agentId)?.name || DEFAULT_AGENT_NAME

  useEffect(() => {
    setIsMounted(true)

    if (hydrated) initialize()
  }, [selectedEndpoint, initialize, hydrated, mode])

  const handleNewChat = () => {
    clearChat()
    focusChatInput()
  }

  return (
    <>
      <motion.aside
        className="relative z-20 flex h-screen shrink-0 grow-0 flex-col overflow-hidden border-r border-white/5 bg-[#0f172a]/60 px-4 py-3.5 font-main backdrop-blur-2xl"
        initial={{ width: '27.5rem' }}
        animate={{ width: isCollapsed ? '3.5rem' : '27.5rem' }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      >
        <motion.button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="absolute right-3 top-3.5 z-10 rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          type="button"
          whileTap={{ scale: 0.95 }}
        >
          <Icon
            type="sheet"
            size="xs"
            className={`transform ${isCollapsed ? 'rotate-180' : 'rotate-0'}`}
          />
        </motion.button>
        <motion.div
          className="w-[25rem] space-y-4"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: isCollapsed ? 0 : 1, x: isCollapsed ? -20 : 0 }}
          transition={{ duration: 0.3, ease: 'easeInOut' }}
          style={{
            pointerEvents: isCollapsed ? 'none' : 'auto'
          }}
        >
          <SidebarHeader />
          <div className="space-y-2">
            <NewChatButton
              disabled={messages.length === 0}
              onClick={handleNewChat}
            />
            <LiveVoiceButton onClick={() => setIsVoiceModalOpen(true)} />
          </div>

          {isMounted && isEndpointActive && <Sessions />}
        </motion.div>
      </motion.aside>

      {/* Voice Assistant Modal */}
      <VoiceModal
        isOpen={isVoiceModalOpen}
        onClose={() => setIsVoiceModalOpen(false)}
        agentName={activeAgentName}
      />
    </>
  )
}

export default Sidebar
