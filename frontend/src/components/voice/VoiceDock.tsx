'use client'

/**
 * Liquid control dock for the voice sheet.
 *
 * Coloured blobs sit behind the real buttons under an SVG "goo" filter, so
 * they merge, squish on press and (while listening) seep a droplet out of the
 * mic. The filter is decoration only: the buttons on top are ordinary, crisp,
 * labelled controls.
 */

import React, { useId, useRef } from 'react'

import { Keyboard, Mic, MicOff, PhoneOff } from 'lucide-react'

import { cn } from '@/lib/utils'

interface VoiceDockProps {
  isMuted: boolean
  isListening: boolean
  onToggleMute: () => void
  onEnd: () => void
  onTypeInstead: () => void
  className?: string
}

/** Restart the squish animation on a blob, even mid-animation. */
function squish(el: HTMLElement | null) {
  if (!el) return
  el.classList.remove('voice-squish')
  void el.offsetWidth
  el.classList.add('voice-squish')
}

export function VoiceDock({
  isMuted,
  isListening,
  onToggleMute,
  onEnd,
  onTypeInstead,
  className
}: VoiceDockProps) {
  const filterId = `voice-goo-${useId().replace(/:/g, '')}`
  const micBlob = useRef<HTMLSpanElement>(null)
  const endBlob = useRef<HTMLSpanElement>(null)
  const kbdBlob = useRef<HTMLSpanElement>(null)

  const blob =
    'absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-[width,background-color] duration-500'

  return (
    <div className={cn('w-full', className)}>
      <svg width="0" height="0" className="absolute" aria-hidden="true">
        <defs>
          <filter id={filterId}>
            <feGaussianBlur in="SourceGraphic" stdDeviation="9" result="b" />
            <feColorMatrix
              in="b"
              mode="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -10"
              result="g"
            />
            <feBlend in="SourceGraphic" in2="g" />
          </filter>
        </defs>
      </svg>

      <div className="relative h-[84px] rounded-[42px] border border-white/10 bg-white/5 shadow-[inset_0_1px_0_rgba(255,255,255,0.14),0_20px_50px_rgba(0,0,0,0.5)] backdrop-blur-xl backdrop-saturate-150">
        <div
          className="absolute inset-0"
          style={{ filter: `url(#${filterId})` }}
          aria-hidden="true"
        >
          <span
            ref={micBlob}
            className={cn(
              blob,
              'left-[58px] h-voice-control',
              isMuted ? 'w-16 bg-voice-error/55' : 'w-voice-control bg-white/15'
            )}
          />
          <span
            ref={endBlob}
            className={cn(blob, 'left-1/2 h-voice-control w-28 bg-rose-600')}
          />
          <span
            ref={kbdBlob}
            className={cn(
              blob,
              'left-[calc(100%-58px)] h-voice-control w-voice-control bg-white/15'
            )}
          />
        </div>

        <div className="absolute inset-0 grid grid-cols-[1fr_auto_1fr] items-center px-[30px]">
          <button
            type="button"
            onPointerDown={() => squish(micBlob.current)}
            onClick={onToggleMute}
            aria-pressed={isMuted}
            aria-label={isMuted ? 'Unmute microphone' : 'Mute microphone'}
            className={cn(
              'grid size-voice-control place-items-center rounded-full text-white ring-2 transition-[box-shadow] duration-500 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold',
              // Listening: a soft blue halo on the mic. (The goo droplet
              // didn't render on mobile browsers and floated loose.)
              isListening && !isMuted
                ? 'shadow-[0_0_18px_rgba(56,189,248,0.45)] ring-voice-listening/70'
                : 'ring-transparent'
            )}
          >
            {isMuted ? (
              <MicOff className="size-6" aria-hidden="true" />
            ) : (
              <Mic className="size-6" aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            onPointerDown={() => squish(endBlob.current)}
            onClick={onEnd}
            className="inline-flex h-voice-control w-28 items-center justify-center gap-2 rounded-full font-large text-[15px] font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold"
          >
            <PhoneOff className="size-[18px]" aria-hidden="true" />
            End
          </button>
          <button
            type="button"
            onPointerDown={() => squish(kbdBlob.current)}
            onClick={onTypeInstead}
            aria-label="Type instead"
            className="grid size-voice-control place-items-center justify-self-end rounded-full text-white focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accentGold"
          >
            <Keyboard className="size-[22px]" aria-hidden="true" />
          </button>
        </div>
      </div>

      <div
        className="grid grid-cols-[1fr_auto_1fr] px-6 pt-2 font-mono text-xs text-muted"
        aria-hidden="true"
      >
        <span>{isMuted ? 'Mic off' : 'Mic on'}</span>
        <span className="w-28" />
        <span className="text-right">Type</span>
      </div>
    </div>
  )
}

export default VoiceDock
