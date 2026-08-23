import type { ChatMessage } from '@/types/os'
import { AgentMessage, UserMessage } from './MessageItem'
import { memo } from 'react'
import {
  ToolCallProps,
  ReasoningStepProps,
  ReasoningProps,
  ReferenceData,
  Reference
} from '@/types/os'
import React, { type FC } from 'react'
import ChatBlankState from './ChatBlankState'
import { Wrench, BrainCircuit, BookOpen } from 'lucide-react'

interface MessageListProps {
  messages: ChatMessage[]
}

interface MessageWrapperProps {
  message: ChatMessage
  isLastMessage: boolean
}

interface ReferenceProps {
  references: ReferenceData[]
}

interface ReferenceItemProps {
  reference: Reference
}

const ReferenceItem: FC<ReferenceItemProps> = ({ reference }) => (
  <div className="relative flex h-[64px] w-[200px] cursor-default flex-col justify-between overflow-hidden rounded-xl border border-white/10 bg-[#0f172a]/70 p-3 transition-colors hover:border-[#e85d04]/40 hover:bg-[#0f172a]">
    <p className="text-xs font-semibold text-white truncate font-main">{reference.name}</p>
    <p className="truncate text-[11px] font-mono text-zinc-400">{reference.content}</p>
  </div>
)

const References: FC<ReferenceProps> = ({ references }) => (
  <div className="flex flex-col gap-3">
    {references.map((referenceData, index) => (
      <div
        key={`${referenceData.query}-${index}`}
        className="flex flex-col gap-2"
      >
        <div className="flex flex-wrap gap-2.5">
          {referenceData.references.map((reference, refIndex) => (
            <ReferenceItem
              key={`${reference.name}-${reference.meta_data.chunk}-${refIndex}`}
              reference={reference}
            />
          ))}
        </div>
      </div>
    ))}
  </div>
)

const AgentMessageWrapper = ({ message }: MessageWrapperProps) => {
  return (
    <div className="flex flex-col gap-y-3 w-full">
      {message.extra_data?.reasoning_steps &&
        message.extra_data.reasoning_steps.length > 0 && (
          <div className="flex w-full justify-start">
            <div className="flex max-w-[88%] items-start gap-3 rounded-2xl border border-purple-500/20 bg-purple-950/20 p-3.5 backdrop-blur-md">
              <div className="size-6 rounded-lg bg-purple-500/20 text-purple-400 flex items-center justify-center shrink-0 mt-0.5">
                <BrainCircuit className="size-3.5" />
              </div>
              <div className="flex flex-col gap-2">
                <p className="text-[11px] font-mono uppercase tracking-wider text-purple-300 font-semibold">Reasoning Steps</p>
                <Reasonings reasoning={message.extra_data.reasoning_steps} />
              </div>
            </div>
          </div>
        )}

      {message.extra_data?.references &&
        message.extra_data.references.length > 0 && (
          <div className="flex w-full justify-start">
            <div className="flex max-w-[88%] items-start gap-3 rounded-2xl border border-white/10 bg-white/5 p-3.5 backdrop-blur-md">
              <div className="size-6 rounded-lg bg-white/10 text-zinc-300 flex items-center justify-center shrink-0 mt-0.5">
                <BookOpen className="size-3.5" />
              </div>
              <div className="flex flex-col gap-2">
                <p className="text-[11px] font-mono uppercase tracking-wider text-zinc-400 font-semibold">References</p>
                <References references={message.extra_data.references} />
              </div>
            </div>
          </div>
        )}

      {message.tool_calls && message.tool_calls.length > 0 && (
        <div className="flex w-full justify-start">
          <div className="flex max-w-[88%] items-start gap-3 rounded-2xl border border-[#e85d04]/20 bg-[#e85d04]/10 p-3.5 backdrop-blur-md">
            <div className="size-6 rounded-lg bg-[#e85d04]/20 text-[#f48c06] flex items-center justify-center shrink-0 mt-0.5">
              <Wrench className="size-3.5" />
            </div>
            <div className="flex flex-col gap-2">
              <p className="text-[11px] font-mono uppercase tracking-wider text-orange-300 font-semibold">Tool Execution</p>
              <div className="flex flex-wrap gap-2">
                {message.tool_calls.map((toolCall, index) => (
                  <ToolComponent
                    key={
                      toolCall.tool_call_id ||
                      `${toolCall.tool_name}-${toolCall.created_at}-${index}`
                    }
                    tools={toolCall}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      <AgentMessage message={message} />
    </div>
  )
}

const Reasoning: FC<ReasoningStepProps> = ({ index, stepTitle }) => (
  <div className="flex items-center gap-2 text-zinc-300 text-xs">
    <span className="flex h-5 items-center rounded-md bg-purple-500/20 px-2 font-mono text-[10px] text-purple-300">
      STEP {index + 1}
    </span>
    <span className="font-main">{stepTitle}</span>
  </div>
)

const Reasonings: FC<ReasoningProps> = ({ reasoning }) => (
  <div className="flex flex-col items-start justify-center gap-1.5">
    {reasoning.map((title, index) => (
      <Reasoning
        key={`${title.title}-${title.action}-${index}`}
        stepTitle={title.title}
        index={index}
      />
    ))}
  </div>
)

const ToolComponent = memo(({ tools }: ToolCallProps) => (
  <div className="inline-flex items-center gap-1.5 rounded-xl border border-[#e85d04]/30 bg-[#0f172a]/90 px-3 py-1 text-xs font-mono text-orange-200 shadow-sm">
    <span className="size-1.5 rounded-full bg-[#f48c06] animate-pulse" />
    <span className="uppercase">{tools.tool_name}</span>
  </div>
))
ToolComponent.displayName = 'ToolComponent'

const Messages = ({ messages }: MessageListProps) => {
  if (messages.length === 0) {
    return <ChatBlankState />
  }

  return (
    <div className="flex flex-col gap-y-6 w-full">
      {messages.map((message, index) => {
        const key = `${message.role}-${message.created_at}-${index}`
        const isLastMessage = index === messages.length - 1

        if (message.role === 'agent') {
          return (
            <AgentMessageWrapper
              key={key}
              message={message}
              isLastMessage={isLastMessage}
            />
          )
        }
        return <UserMessage key={key} message={message} />
      })}
    </div>
  )
}

export default Messages
