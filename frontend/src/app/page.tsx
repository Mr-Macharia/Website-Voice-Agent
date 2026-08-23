'use client'

import Sidebar from '@/components/chat/Sidebar/Sidebar'
import { ChatArea } from '@/components/chat/ChatArea'
import { Suspense } from 'react'

export default function Home() {
  const hasEnvToken = !!process.env.NEXT_PUBLIC_OS_SECURITY_KEY
  const envToken = process.env.NEXT_PUBLIC_OS_SECURITY_KEY || ''

  return (
    <Suspense fallback={<div className="flex h-screen items-center justify-center text-sm font-mono text-zinc-400">Loading Agent OS...</div>}>
      <div className="relative flex h-screen bg-[#0a0f1e] text-[#f1f5f9] overflow-hidden">
        {/* Atmospheric Background from gichogumacharia.tech */}
        <div className="pointer-events-none fixed inset-0 z-0 bg-grid-dots opacity-40" />
        <div className="orb-orange -top-40 -right-40 size-[550px] z-0" />
        <div className="orb-fire -bottom-40 -left-40 size-[480px] z-0" />

        {/* Application Layout */}
        <div className="relative z-10 flex size-full">
          <Sidebar hasEnvToken={hasEnvToken} envToken={envToken} />
          <ChatArea />
        </div>
      </div>
    </Suspense>
  )
}
