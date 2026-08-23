import type { Metadata } from 'next'
import { NuqsAdapter } from 'nuqs/adapters/next/app'
import { Toaster } from '@/components/ui/sonner'
import './globals.css'

export const metadata: Metadata = {
  title: 'Gichogu Macharia | Realtime Voice & AI Agent OS',
  description:
    'Building intelligent systems, realtime voice agents with Deepgram Flux, and multi-agent workflows powered by Agno and Grok.'
}

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Georama:ital,wght@0,100..900;1,100..900&family=Host+Grotesk:ital,wght@0,300..800;1,300..800&family=Fira+Code:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased font-main bg-[#0a0f1e] text-[#f1f5f9] min-h-screen overflow-x-hidden selection:bg-[#e85d04]/30 selection:text-white">
        <NuqsAdapter>{children}</NuqsAdapter>
        <Toaster
          toastOptions={{
            style: {
              background: 'rgba(15, 23, 42, 0.95)',
              border: '1px solid rgba(232, 93, 4, 0.3)',
              color: '#f1f5f9',
              backdropFilter: 'blur(16px)'
            }
          }}
        />
      </body>
    </html>
  )
}
