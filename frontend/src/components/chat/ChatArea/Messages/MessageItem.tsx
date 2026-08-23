import MarkdownRenderer from '@/components/ui/typography/MarkdownRenderer'
import { useStore } from '@/store'
import type { ChatMessage } from '@/types/os'
import Videos from './Multimedia/Videos'
import Images from './Multimedia/Images'
import Audios from './Multimedia/Audios'
import { memo } from 'react'
import AgentThinkingLoader from './AgentThinkingLoader'
import { Sparkles, User } from 'lucide-react'

interface MessageProps {
  message: ChatMessage
}

const AgentMessage = ({ message }: MessageProps) => {
  const { streamingErrorMessage } = useStore()
  let messageContent
  if (message.streamingError) {
    messageContent = (
      <p className="text-destructive font-mono text-xs">
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
      <div className="flex w-full flex-col gap-4 font-main text-zinc-100 text-sm leading-relaxed">
        <MarkdownRenderer>{message.content}</MarkdownRenderer>
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
        <div className="flex w-full flex-col gap-4 font-main text-zinc-100 text-sm leading-relaxed">
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
    <div className="flex w-full justify-start">
      <div className="flex max-w-[88%] items-start gap-3.5 rounded-3xl rounded-tl-sm border border-white/10 bg-[#0f172a]/80 p-5 text-zinc-100 backdrop-blur-2xl shadow-xl hover:border-white/20 transition-all">
        <div className="flex-shrink-0 size-8 rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] flex items-center justify-center text-white shadow-md shadow-orange-950/50 mt-0.5">
          <Sparkles className="size-4" />
        </div>
        <div className="flex-1 min-w-0">{messageContent}</div>
      </div>
    </div>
  )
}

const UserMessage = memo(({ message }: MessageProps) => {
  return (
    <div className="flex w-full justify-end">
      <div className="flex max-w-[82%] items-start gap-3 rounded-3xl rounded-tr-sm border border-[#e85d04]/40 bg-gradient-to-tr from-[#e85d04]/20 via-[#f48c06]/15 to-[#dc2f02]/20 p-4 text-white backdrop-blur-2xl shadow-lg shadow-orange-950/20 hover:border-[#e85d04]/60 transition-all">
        <div className="text-sm font-main text-zinc-100 flex-1 leading-relaxed">
          {message.content}
        </div>
        <div className="flex-shrink-0 size-7 rounded-xl bg-white/10 flex items-center justify-center text-zinc-200 border border-white/10 shadow-sm mt-0.5">
          <User className="size-3.5" />
        </div>
      </div>
    </div>
  )
})

AgentMessage.displayName = 'AgentMessage'
UserMessage.displayName = 'UserMessage'
export { AgentMessage, UserMessage }
