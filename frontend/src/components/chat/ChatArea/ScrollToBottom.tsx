'use client'

import type React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useStickToBottomContext } from 'use-stick-to-bottom'
import { Button } from '@/components/ui/button'
import { ArrowDown } from 'lucide-react'

const ScrollToBottom: React.FC = () => {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext()

  return (
    <AnimatePresence>
      {!isAtBottom && (
        <motion.div
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 15 }}
          transition={{ duration: 0.25, ease: 'easeInOut' }}
          className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20"
        >
          <Button
            onClick={() => scrollToBottom()}
            type="button"
            size="icon"
            className="size-9 rounded-full border border-[#e85d04]/40 bg-[#0f172a]/90 text-orange-300 shadow-xl shadow-orange-950/40 hover:bg-[#e85d04]/20 hover:border-[#e85d04] hover:text-white transition-all"
            title="Scroll to latest message"
          >
            <ArrowDown className="size-4" />
          </Button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export default ScrollToBottom
