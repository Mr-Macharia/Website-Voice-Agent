'use client'
import { Button } from '@/components/ui/button'
import { ModeSelector } from '@/components/chat/Sidebar/ModeSelector'
import { EntitySelector } from '@/components/chat/Sidebar/EntitySelector'
import useChatActions from '@/hooks/useChatActions'
import { useStore } from '@/store'
import { motion, AnimatePresence } from 'framer-motion'
import { useState, useEffect } from 'react'
import Icon from '@/components/ui/icon'
import { getProviderIcon } from '@/lib/modelProvider'
import Sessions from './Sessions'
import AuthToken from './AuthToken'
import { isValidUrl } from '@/lib/utils'
import { toast } from 'sonner'
import { useQueryState } from 'nuqs'
import { truncateText } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'
import { Mic, Sparkles } from 'lucide-react'
import LiveKitVoiceModal from '@/components/voice/LiveKitVoiceModal'

const ENDPOINT_PLACEHOLDER = 'NO ENDPOINT ADDED'

const SidebarHeader = () => (
  <div className="flex items-center gap-2.5 px-1 py-1">
    <div className="size-8 rounded-xl bg-gradient-to-tr from-[#e85d04] via-[#f48c06] to-[#dc2f02] flex items-center justify-center shadow-lg shadow-orange-950/50 ring-1 ring-white/20">
      <span className="font-mono text-xs font-black text-white tracking-tighter">GM</span>
    </div>
    <div className="flex flex-col min-w-0">
      <span className="text-xs font-bold tracking-tight text-white font-large truncate">
        Gichogu Macharia
      </span>
      <span className="text-[10px] font-mono text-[#f48c06] tracking-wider uppercase flex items-center gap-1">
        <Sparkles className="size-2.5 inline" /> AI Agent OS
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
    className="h-9 w-full rounded-xl bg-white/10 border border-white/10 text-xs font-medium text-white hover:bg-white/15 hover:border-white/20 transition-all shadow-sm"
  >
    <Icon type="plus-icon" size="xs" className="text-white" />
    <span className="uppercase font-mono text-[11px] tracking-wider">New Chat</span>
  </Button>
)

const LiveVoiceButton = ({ onClick }: { onClick: () => void }) => (
  <Button
    onClick={onClick}
    size="lg"
    className="h-10 w-full rounded-xl border border-[#e85d04]/40 bg-gradient-to-r from-[#e85d04]/20 via-[#f48c06]/15 to-[#dc2f02]/20 text-xs font-semibold text-orange-200 hover:border-[#e85d04] hover:bg-[#e85d04]/30 shadow-lg shadow-orange-950/40 transition-all group relative overflow-hidden"
  >
    <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
    <Mic className="size-4 text-[#f48c06] group-hover:scale-110 transition-transform animate-pulse" />
    <span className="uppercase font-mono text-[11px] tracking-wider text-white">Live Voice Agent</span>
  </Button>
)

const ModelDisplay = ({ model }: { model: string }) => (
  <div className="flex h-9 w-full items-center gap-3 rounded-xl border border-white/10 bg-[#0f172a]/70 p-3 text-xs font-mono uppercase text-zinc-300">
    {(() => {
      const icon = getProviderIcon(model)
      return icon ? <Icon type={icon} className="shrink-0" size="xs" /> : null
    })()}
    <span className="truncate">{model}</span>
  </div>
)

const Endpoint = () => {
  const {
    selectedEndpoint,
    isEndpointActive,
    setSelectedEndpoint,
    setAgents,
    setSessionsData,
    setMessages
  } = useStore()
  const { initialize } = useChatActions()
  const [isEditing, setIsEditing] = useState(false)
  const [endpointValue, setEndpointValue] = useState('')
  const [isMounted, setIsMounted] = useState(false)
  const [isHovering, setIsHovering] = useState(false)
  const [isRotating, setIsRotating] = useState(false)
  const [, setAgentId] = useQueryState('agent')
  const [, setSessionId] = useQueryState('session')

  useEffect(() => {
    setEndpointValue(selectedEndpoint)
    setIsMounted(true)
  }, [selectedEndpoint])

  const getStatusColor = (isActive: boolean) =>
    isActive ? 'bg-[#22c55e] shadow-[0_0_8px_#22c55e]' : 'bg-[#dc2f02] shadow-[0_0_8px_#dc2f02]'

  const handleSave = async () => {
    if (!isValidUrl(endpointValue)) {
      toast.error('Please enter a valid URL')
      return
    }
    const cleanEndpoint = endpointValue.replace(/\/$/, '').trim()
    setSelectedEndpoint(cleanEndpoint)
    setAgentId(null)
    setSessionId(null)
    setIsEditing(false)
    setIsHovering(false)
    setAgents([])
    setSessionsData([])
    setMessages([])
  }

  const handleCancel = () => {
    setEndpointValue(selectedEndpoint)
    setIsEditing(false)
    setIsHovering(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleSave()
    } else if (e.key === 'Escape') {
      handleCancel()
    }
  }

  const handleRefresh = async () => {
    setIsRotating(true)
    await initialize()
    setTimeout(() => setIsRotating(false), 500)
  }

  return (
    <div className="flex flex-col items-start gap-2">
      <div className="text-[11px] font-mono uppercase tracking-wider text-zinc-400">AgentOS</div>
      {isEditing ? (
        <div className="flex w-full items-center gap-1">
          <input
            type="text"
            value={endpointValue}
            onChange={(e) => setEndpointValue(e.target.value)}
            onKeyDown={handleKeyDown}
            className="flex h-9 w-full items-center text-ellipsis rounded-xl border border-[#e85d04]/50 bg-[#0f172a] p-3 text-xs font-mono text-zinc-200 focus:outline-none"
            autoFocus
          />
          <Button
            variant="ghost"
            size="icon"
            onClick={handleSave}
            className="hover:cursor-pointer hover:bg-white/5 text-zinc-300"
          >
            <Icon type="save" size="xs" />
          </Button>
        </div>
      ) : (
        <div className="flex w-full items-center gap-1">
          <motion.div
            className="relative flex h-9 w-full cursor-pointer items-center justify-between rounded-xl border border-white/10 bg-[#0f172a]/60 p-3 uppercase hover:border-[#e85d04]/40 transition-colors"
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
            onClick={() => setIsEditing(true)}
            transition={{ type: 'spring', stiffness: 400, damping: 10 }}
          >
            <AnimatePresence mode="wait">
              {isHovering ? (
                <motion.div
                  key="endpoint-display-hover"
                  className="absolute inset-0 flex items-center justify-center"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <p className="flex items-center gap-2 whitespace-nowrap text-xs font-mono text-zinc-200">
                    <Icon type="edit" size="xxs" /> EDIT AGENTOS
                  </p>
                </motion.div>
              ) : (
                <motion.div
                  key="endpoint-display"
                  className="absolute inset-0 flex items-center justify-between px-3"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <p className="text-xs font-mono text-zinc-400">
                    {isMounted
                      ? truncateText(selectedEndpoint, 21) ||
                        ENDPOINT_PLACEHOLDER
                      : 'http://localhost:7777'}
                  </p>
                  <div
                    className={`size-2 shrink-0 rounded-full ${getStatusColor(isEndpointActive)}`}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleRefresh}
            className="hover:cursor-pointer hover:bg-white/5 text-zinc-400 hover:text-zinc-200"
          >
            <motion.div
              key={isRotating ? 'rotating' : 'idle'}
              animate={{ rotate: isRotating ? 360 : 0 }}
              transition={{ duration: 0.5, ease: 'easeInOut' }}
            >
              <Icon type="refresh" size="xs" />
            </motion.div>
          </Button>
        </div>
      )}
    </div>
  )
}

const Sidebar = ({
  hasEnvToken,
  envToken
}: {
  hasEnvToken?: boolean
  envToken?: string
}) => {
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [isVoiceModalOpen, setIsVoiceModalOpen] = useState(false)
  const { clearChat, focusChatInput, initialize } = useChatActions()
  const {
    messages,
    selectedEndpoint,
    isEndpointActive,
    selectedModel,
    hydrated,
    isEndpointLoading,
    agents,
    mode
  } = useStore()
  const [isMounted, setIsMounted] = useState(false)
  const [agentId] = useQueryState('agent')
  const [teamId] = useQueryState('team')

  const activeAgentName =
    agents.find((a) => a.id === agentId)?.name || 'Realtime Voice Assistant'

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
        className="relative flex h-screen shrink-0 grow-0 flex-col overflow-hidden border-r border-white/5 bg-[#0f172a]/60 backdrop-blur-2xl px-4 py-3.5 font-main z-20"
        initial={{ width: '27.5rem' }}
        animate={{ width: isCollapsed ? '3.5rem' : '27.5rem' }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
      >
        <motion.button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="absolute right-3 top-3.5 z-10 p-1.5 rounded-lg text-zinc-400 hover:text-white hover:bg-white/5 transition-colors"
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

          {isMounted && (
            <>
              <Endpoint />
              <AuthToken hasEnvToken={hasEnvToken} envToken={envToken} />
              {isEndpointActive && (
                <>
                  <motion.div
                    className="flex w-full flex-col items-start gap-2"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.5, ease: 'easeInOut' }}
                  >
                    <div className="text-[11px] font-mono uppercase tracking-wider text-zinc-400">
                      Mode
                    </div>
                    {isEndpointLoading ? (
                      <div className="flex w-full flex-col gap-2">
                        {Array.from({ length: 3 }).map((_, index) => (
                          <Skeleton
                            key={index}
                            className="h-9 w-full rounded-xl bg-white/5"
                          />
                        ))}
                      </div>
                    ) : (
                      <>
                        <ModeSelector />
                        <EntitySelector />
                        {selectedModel && (agentId || teamId) && (
                          <ModelDisplay model={selectedModel} />
                        )}
                      </>
                    )}
                  </motion.div>
                  <Sessions />
                </>
              )}
            </>
          )}
        </motion.div>
      </motion.aside>

      {/* Voice Assistant Modal */}
      <LiveKitVoiceModal
        isOpen={isVoiceModalOpen}
        onClose={() => setIsVoiceModalOpen(false)}
        agentName={activeAgentName}
      />
    </>
  )
}

export default Sidebar
