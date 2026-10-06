'use client'

import { useEffect, type ReactNode } from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useStore } from '@/store'

/**
 * Below lg the sidebar lives in this left-side drawer. Radix Dialog gives it
 * the backdrop, Esc to close, a focus trap, scroll lock, and focus return to
 * the menu button that opened it.
 */
const MobileSidebar = ({ children }: { children: ReactNode }) => {
  const isOpen = useStore((state) => state.isMobileSidebarOpen)
  const setOpen = useStore((state) => state.setMobileSidebarOpen)

  // Rotating a tablet or widening the window past lg shows the desktop
  // aside, so a drawer left open would be a stray second sidebar.
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1024px)')
    const close = (e: MediaQueryListEvent) => e.matches && setOpen(false)
    query.addEventListener('change', close)
    return () => query.removeEventListener('change', close)
  }, [setOpen])

  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none lg:hidden" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed inset-y-0 left-0 z-50 flex h-dvh w-[min(20rem,85vw)] flex-col border-r border-white/10 bg-background-secondary/95 px-4 pt-[max(0.875rem,env(safe-area-inset-top))] pb-[max(0.875rem,env(safe-area-inset-bottom))] font-main shadow-2xl backdrop-blur-2xl duration-200 data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:animate-in data-[state=open]:slide-in-from-left motion-reduce:animate-none lg:hidden"
        >
          <DialogPrimitive.Title className="sr-only">
            Menu
          </DialogPrimitive.Title>
          <DialogPrimitive.Close
            className="absolute top-[max(0.5rem,env(safe-area-inset-top))] right-2 z-10 flex size-11 items-center justify-center rounded-xl text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
            aria-label="Close menu"
          >
            <X className="size-5" />
          </DialogPrimitive.Close>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

export default MobileSidebar
