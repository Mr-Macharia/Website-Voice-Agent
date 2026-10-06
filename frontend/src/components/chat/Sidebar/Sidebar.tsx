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
import MobileSidebar from './MobileSidebar'

const SidebarHeader = () => (
  <div className="flex items-center gap-2.5 px-1 py-1">
    <div className="flex size-8 items-center justify-center rounded-xl bg-linear-to-tr from-brand via-accentGold to-[#dc2f02] shadow-lg ring-1 shadow-orange-950/50 ring-white/20">
      <span className="font-mono text-xs font-black tracking-tighter text-white">
        GM
      </span>
    </div>
    <div className="flex min-w-0 flex-col">
      <span className="truncate font-large text-xs font-bold tracking-tight text-white">
        Gichogu Macharia
      </span>
      <span className="flex items-center gap-1 font-mono text-[10px] tracking-wider text-accentGold uppercase">
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
    className="h-9 w-full rounded-xl border border-white/10 bg-white/10 text-xs font-medium text-white shadow-xs transition-all hover:border-white/20 hover:bg-white/15"
  >
    <Icon type="plus-icon" size="xs" className="text-white" />
    <span className="font-mono text-[11px] tracking-wider uppercase">
      New Chat
    </span>
  </Button>
)

const LiveVoiceButton = ({ onClick }: { onClick: () => void }) => (
  <Button
    onClick={onClick}
    size="lg"
    className="group relative h-10 w-full overflow-hidden rounded-xl border border-brand/40 bg-transparent bg-linear-to-r from-brand/20 via-accentGold/15 to-[#dc2f02]/20 text-xs font-semibold text-orange-200 shadow-lg shadow-orange-950/40 transition-all hover:border-brand hover:bg-brand/30"
  >
    <div className="absolute inset-0 bg-linear-to-r from-transparent via-white/5 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
    <Mic className="size-4 animate-pulse text-accentGold transition-transform group-hover:scale-110" />
    <span className="font-mono text-[11px] tracking-wider text-white uppercase">
      Live Voice Agent
    </span>
  </Button>
)

/**
 * The sidebar's contents, shared by the desktop aside and the mobile drawer.
 * `onAction` lets the drawer close itself after New Chat or Live Voice.
 */
export const SidebarContent = ({
  onOpenVoice,
  onAction
}: {
  onOpenVoice: () => void
  onAction?: () => void
}) => {
  const { clearChat, focusChatInput } = useChatActions()
  const { messages, isEndpointActive } = useStore()
  const [isMounted, setIsMounted] = useState(false)

  useEffect(() => setIsMounted(true), [])

  const handleNewChat = () => {
    clearChat()
    onAction?.()
    focusChatInput()
  }

  const handleVoice = () => {
    onAction?.()
    onOpenVoice()
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <SidebarHeader />
      <div className="space-y-2">
        <NewChatButton
          disabled={messages.length === 0}
          onClick={handleNewChat}
        />
        <LiveVoiceButton onClick={handleVoice} />
      </div>

      {isMounted && isEndpointActive && <Sessions />}
    </div>
  )
}

const Sidebar = () => {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [isVoiceModalOpen, setIsVoiceModalOpen] = useState(false)
  const { initialize } = useChatActions()
  const { selectedEndpoint, hydrated, agents, mode } = useStore()
  const [agentId] = useQueryState('agent')

  const activeAgentName =
    agents.find((a) => a.id === agentId)?.name || DEFAULT_AGENT_NAME

  useEffect(() => {
    if (hydrated) initialize()
  }, [selectedEndpoint, initialize, hydrated, mode])

  const setMobileSidebarOpen = useStore((state) => state.setMobileSidebarOpen)
  const openVoice = () => setIsVoiceModalOpen(true)

  return (
    <>
      {/* Desktop: collapsible aside. Below lg the drawer takes over. */}
      <motion.aside
        className="relative z-20 hidden h-dvh shrink-0 grow-0 flex-col overflow-hidden border-r border-white/5 bg-[#0f172a]/60 px-4 py-3.5 font-main backdrop-blur-2xl lg:flex"
        initial={{ width: '27.5rem' }}
        animate={{ width: isCollapsed ? '3.5rem' : '27.5rem' }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      >
        <motion.button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="absolute top-3.5 right-3 z-10 rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
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
          className="flex min-h-0 w-100 flex-1 flex-col"
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: isCollapsed ? 0 : 1, x: isCollapsed ? -20 : 0 }}
          transition={{ duration: 0.3, ease: 'easeInOut' }}
          style={{
            pointerEvents: isCollapsed ? 'none' : 'auto'
          }}
        >
          <SidebarContent onOpenVoice={openVoice} />
        </motion.div>
      </motion.aside>

      <MobileSidebar>
        <SidebarContent
          onOpenVoice={openVoice}
          onAction={() => setMobileSidebarOpen(false)}
        />
      </MobileSidebar>

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
