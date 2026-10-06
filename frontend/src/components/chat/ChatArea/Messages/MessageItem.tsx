import { stripEmptyFences, stripToolPayload } from '@/lib/toolPayload'
import MarkdownRenderer from '@/components/ui/typography/MarkdownRenderer'
import { useStore } from '@/store'
import type { ChatMessage } from '@/types/os'
import Videos from './Multimedia/Videos'
import Images from './Multimedia/Images'
import Audios from './Multimedia/Audios'
import { memo, useState } from 'react'
import AgentThinkingLoader from './AgentThinkingLoader'
import { Check, Copy, Sparkles, User } from 'lucide-react'

interface MessageProps {
  message: ChatMessage
}

/**
 * Copy action under an agent reply (action-bar pattern from assistant-ui).
 * Hover-revealed with a pointer, always visible on touch.
 */
const CopyAction = ({ text }: { text: string }) => {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard blocked: nothing to do */
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={copied ? 'Copied' : 'Copy reply'}
      className="inline-flex h-11 items-center gap-1.5 rounded-lg px-2 font-mono text-xs text-muted transition-opacity hover:text-white focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-accentGold lg:h-8 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover:opacity-100"
    >
      {copied ? (
        <Check className="size-3.5" aria-hidden="true" />
      ) : (
        <Copy className="size-3.5" aria-hidden="true" />
      )}
      <span aria-live="polite">{copied ? 'Copied' : 'Copy'}</span>
    </button>
  )
}

const AgentMessage = ({ message }: MessageProps) => {
  const { isStreaming, messages } = useStore()
  const isLive = isStreaming && messages[messages.length - 1] === message
  const copyText = message.content
    ? stripEmptyFences(stripToolPayload(message.content)).trim()
    : ''
  const { streamingErrorMessage } = useStore()
  let messageContent
  if (message.streamingError) {
    messageContent = (
      <p className="font-mono text-xs text-destructive">
        Oops! Something went wrong while streaming.{' '}
        {streamingErrorMessage ? (
          <>{streamingErrorMessage}</>
        ) : (
          'Please try refreshing the page or try again later.'
        )}
      </p>
    )
  } else if (message.content) {
    messageContent = (
      <div className="flex w-full flex-col gap-4 font-main text-sm leading-relaxed text-zinc-100">
        <MarkdownRenderer>
          {stripEmptyFences(stripToolPayload(message.content))}
        </MarkdownRenderer>
        {message.videos && message.videos.length > 0 && (
          <Videos videos={message.videos} />
        )}
        {message.images && message.images.length > 0 && (
          <Images images={message.images} />
        )}
        {message.audio && message.audio.length > 0 && (
          <Audios audio={message.audio} />
        )}
      </div>
    )
  } else if (message.response_audio) {
    if (!message.response_audio.transcript) {
      messageContent = (
        <div className="mt-2 flex items-start">
          <AgentThinkingLoader />
        </div>
      )
    } else {
      messageContent = (
        <div className="flex w-full flex-col gap-4 font-main text-sm leading-relaxed text-zinc-100">
          <MarkdownRenderer>
            {message.response_audio.transcript}
          </MarkdownRenderer>
          {message.response_audio.content && message.response_audio && (
            <Audios audio={[message.response_audio]} />
          )}
        </div>
      )
    }
  } else {
    messageContent = (
      <div className="mt-2">
        <AgentThinkingLoader />
      </div>
    )
  }

  return (
    <div className="group flex w-full flex-col items-start">
      <div className="flex max-w-[88%] items-start gap-3.5 rounded-3xl rounded-tl-sm border border-white/10 bg-[#0f172a]/80 p-3.5 text-zinc-100 shadow-xl backdrop-blur-2xl transition-all hover:border-white/20 sm:p-5">
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl bg-linear-to-tr from-brand to-accentGold text-white shadow-md shadow-orange-950/50">
          <Sparkles className="size-4" />
        </div>
        <div className="min-w-0 flex-1 wrap-break-word">{messageContent}</div>
      </div>
      {copyText && !isLive && !message.streamingError && (
        <div className="mt-1 pl-2">
          <CopyAction text={copyText} />
        </div>
      )}
    </div>
  )
}

const UserMessage = memo(({ message }: MessageProps) => {
  return (
    <div className="flex w-full justify-end">
      <div className="flex max-w-[82%] items-start gap-3 rounded-3xl rounded-tr-sm border border-brand/40 bg-linear-to-tr from-brand/20 via-accentGold/15 to-[#dc2f02]/20 p-3 text-white shadow-lg shadow-orange-950/20 backdrop-blur-2xl transition-all hover:border-brand/60 sm:p-4">
        <div className="min-w-0 flex-1 font-main text-sm leading-relaxed wrap-break-word text-zinc-100">
          {message.content}
        </div>
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/10 text-zinc-200 shadow-xs">
          <User className="size-3.5" />
        </div>
      </div>
    </div>
  )
})

AgentMessage.displayName = 'AgentMessage'
UserMessage.displayName = 'UserMessage'
export { AgentMessage, UserMessage }
