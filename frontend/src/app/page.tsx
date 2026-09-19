'use client'

import Sidebar from '@/components/chat/Sidebar/Sidebar'
import { ChatArea } from '@/components/chat/ChatArea'
import { Suspense } from 'react'

export default function Home() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center font-mono text-sm text-zinc-400">
          Loading...
        </div>
      }
    >
      <div className="relative flex h-screen overflow-hidden bg-[#0a0f1e] text-[#f1f5f9]">
        {/* Atmospheric Background from gichogumacharia.tech */}
        <div className="bg-grid-dots pointer-events-none fixed inset-0 z-0 opacity-40" />
        <div className="orb-orange -right-40 -top-40 z-0 size-[550px]" />
        <div className="orb-fire -bottom-40 -left-40 z-0 size-[480px]" />

        {/* Application Layout */}
        <div className="relative z-10 flex size-full">
          <Sidebar />
          <ChatArea />
        </div>
      </div>
    </Suspense>
  )
}
