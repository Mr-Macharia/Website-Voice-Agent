'use client'

/**
 * The card shown when the agent hands over a booking link.
 *
 * The visitor books inside the chat: Cal.com's real calendar, with real
 * availability, mounted inline in the message. No popup, no navigating away.
 *
 * Kept in its own file, taking a plain payload rather than a message, so the
 * voice modal can render the same card from its own tool-call handler later
 * (voice tool calls run client-side in AssemblyAISession.handleToolCall).
 *
 * Why the script and not `@calcom/embed-react`: that package is a ~2KB wrapper
 * that installs Cal's loader snippet and then calls `Cal("inline", ...)`,
 * which is what happens below. It ships ESM-only `.mjs` in a package with no
 * `"type": "module"`, which webpack could not chunk under `next/dynamic` --
 * dev threw ChunkLoadError, and the production build quietly inlined it
 * instead. `lib/calEmbed.ts` reproduces the loader, which embed.js requires:
 * the script throws unless `window.Cal` already exists.
 *
 * The link is kept visible underneath. Cal's calendar is third-party script in
 * an iframe: it can be blocked, slow, or broken, and a visitor who cannot book
 * is the one outcome this card must never produce.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { CalendarDays, ArrowUpRight } from 'lucide-react'

import { calLinkFromUrl, type BookingPayload } from '@/lib/toolPayload'
import { loadCalApi } from '@/lib/calEmbed'

const CAL_ORIGIN = 'https://app.cal.com'

/**
 * Which card currently owns the inline calendar, and the next id to hand out.
 *
 * Cal's `inline` embed is effectively one instance per page for our purposes.
 * Namespaces look like the answer and are not: embed.js upgrades namespaces
 * into real instances in a single loop that runs once, when the script
 * finishes loading, and its constructor is module-private. A namespace created
 * after that point gets a queue and never an instance, so its calendar never
 * appears. A chat that renders cards as the conversation happens cannot
 * register every namespace up front, so that door is closed.
 *
 * So exactly one card shows a calendar: the newest, which is the one the
 * visitor just asked for. Every other card renders link-only -- not as a
 * failure, because nothing failed, but as the deliberate presentation for a
 * card that is no longer the live one.
 */
let calOwnerSeq = 0

/**
 * Cards waiting to be told they have been superseded.
 *
 * An explicit notification rather than relying on React to re-render the older
 * card: nothing guarantees a mounted card re-renders just because a new one
 * appeared elsewhere in the tree, and a card that never re-renders would keep
 * a calendar it no longer owns.
 */
const calOwnerListeners = new Set<(ownerId: number) => void>()

/**
 * Rank of the card that currently holds the calendar, and its id.
 *
 * Rank beats recency: a priority card (one in the voice modal, on top of
 * everything) keeps the calendar even when a lower-ranked card mounts later.
 * Among cards of equal rank the newest wins, which is right for two bookings
 * in one chat.
 */
let calOwnerRank = -1
let calOwnerId = -1

function claimCalOwnership(id: number, rank: number) {
  // A rejected claim still has to notify: the claiming card starts
  // optimistically as owner, so without this it would keep a calendar the
  // higher-ranked card already holds.
  if (rank < calOwnerRank) {
    for (const notify of calOwnerListeners) notify(calOwnerId)
    return
  }
  calOwnerRank = rank
  calOwnerId = id
  for (const notify of calOwnerListeners) notify(id)
}

/** A card unmounting releases the calendar so a remaining card can take it. */
function releaseCalOwnership(id: number) {
  if (calOwnerId !== id) return
  calOwnerRank = -1
  calOwnerId = -1
  for (const notify of calOwnerListeners) notify(-1)
}

// How long to wait for the iframe before showing the link-only fallback.
const EMBED_TIMEOUT_MS = 10000

interface BookingCardProps {
  payload: BookingPayload
  /**
   * Set on a card rendered inside the voice modal.
   *
   * A voice booking mounts two cards from one payload: one in the modal and a
   * mirrored one in the chat behind it. Only one can hold the calendar, and
   * "newest wins" picks the wrong one -- the chat mirror is appended second,
   * so it would claim the calendar while the visitor is looking at the modal
   * on top of it. A card on top outranks one behind it, whenever it mounted.
   */
  priority?: boolean
}

export const BookingCard: React.FC<BookingCardProps> = ({
  payload,
  priority = false
}) => {
  const calLink = calLinkFromUrl(payload.url)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mountedRef = useRef(false)
  // Allocated once per component instance, not per render. Allocation only --
  // claiming ownership notifies other cards, and notifying during render means
  // calling setState on a component React is not currently rendering, which it
  // rejects ("Cannot update a component while rendering a different
  // component"). The claim happens in the effect below instead.
  const idRef = useRef<number | null>(null)
  if (idRef.current === null) {
    idRef.current = calOwnerSeq += 1
  }
  // Optimistic: a card starts as owner and yields if an newer one claims.
  // Corrected on mount, so a card rendered after a newer sibling settles fast.
  const [isOwner, setIsOwner] = useState(true)
  const [status, setStatus] = useState<'loading' | 'ready' | 'failed'>(
    calLink ? 'loading' : 'failed'
  )

  // A card that has been superseded gives up its calendar and becomes
  // link-only. Subscribing means this does not depend on the older card
  // happening to re-render for another reason.
  useEffect(() => {
    const onOwnerChanged = (ownerId: number) => {
      if (ownerId === -1) {
        // The owner unmounted. Re-claim; the ranking decides who actually
        // takes it when several cards are still on screen.
        claimCalOwnership(idRef.current as number, priority ? 1 : 0)
        return
      }
      setIsOwner(idRef.current === ownerId)
    }
    calOwnerListeners.add(onOwnerChanged)
    // Claim on mount, in commit phase where notifying siblings is safe.
    const id = idRef.current as number
    claimCalOwnership(id, priority ? 1 : 0)
    return () => {
      calOwnerListeners.delete(onOwnerChanged)
      // Closing the voice modal unmounts its card; the mirrored chat card
      // behind it should get the calendar rather than leaving none on screen.
      releaseCalOwnership(id)
    }
  }, [priority])

  /**
   * Mount the calendar into our own div.
   *
   * Cal's snippet queues calls made before the script finishes, so this is
   * safe to run as soon as `window.Cal` exists. `mountedRef` guards against a
   * second mount: this component re-renders whenever the message list updates,
   * and mounting twice stacks two iframes in one card.
   */
  const mountCalendar = useCallback(() => {
    if (!isOwner) return
    if (!calLink || mountedRef.current || !containerRef.current) return
    try {
      // Installs the queueing stub and injects embed.js on first call. Calls
      // made before the script lands are replayed, so no waiting is needed.
      const cal = loadCalApi()
      if (typeof cal !== 'function') return

      cal('init', { origin: CAL_ORIGIN })
      cal('inline', {
        elementOrSelector: containerRef.current,
        calLink,
        // month_view puts the slot list BESIDE the calendar. column_view
        // stacks them, which in a fixed-height container means the slots sit
        // below the fold behind a scrollbar. Cal falls back to its own mobile
        // layout under 768px regardless, so this is the wide-container choice.
        config: { theme: 'dark', layout: 'month_view' }
      })
      cal('ui', {
        theme: 'dark',
        layout: 'month_view',
        hideEventTypeDetails: false,
        cssVarsPerTheme: { dark: { 'cal-brand': '#e85d04' } }
      })
      mountedRef.current = true
    } catch {
      setStatus('failed')
    }
  }, [calLink, isOwner])

  // Mount on render. The queue makes this safe whether or not embed.js has
  // finished loading, and whether this is the first booking card or the fifth.
  useEffect(() => {
    if (!isOwner) {
      // The container just unmounted. Cal refuses a second `inline()` while
      // its previous element is still in the DOM ("Inline embed already
      // exists. Ignoring this call") and offers no teardown API, so removing
      // the element is what frees the embed. Clearing the guard lets this
      // card mount afresh if it becomes the owner again -- without this it
      // would render an empty container forever.
      mountedRef.current = false
      setStatus(calLink ? 'loading' : 'failed')
      return
    }
    // Deferred one frame. When the modal closes, React can remove its
    // container and mount this one in the same commit; Cal checks
    // `document.body.contains(inlineEl)` synchronously, so calling
    // immediately can still see the old element and refuse. A frame later the
    // removal has landed.
    const raf = requestAnimationFrame(() => mountCalendar())
    return () => cancelAnimationFrame(raf)
  }, [mountCalendar, isOwner, calLink])

  // Watch for the iframe Cal injects. Its arrival is what "ready" means; its
  // absence after the timeout means the script was blocked or failed, and the
  // card collapses to the link rather than holding an empty frame open.
  useEffect(() => {
    // Keeps watching after a timeout, not only while loading: a slow script
    // that lands at 12s should still produce a calendar rather than leaving
    // the visitor with a failure message beside a working embed.
    if (!isOwner || !calLink || status === 'ready') return
    const el = containerRef.current
    if (!el) return

    const check = () => {
      if (el.querySelector('iframe')) {
        setStatus('ready')
        return true
      }
      return false
    }
    if (check()) return

    const observer = new MutationObserver(() => check())
    observer.observe(el, { childList: true, subtree: true })
    // Only the first pass declares failure; later passes can only recover.
    const timer =
      status === 'loading'
        ? setTimeout(() => {
            if (!check()) setStatus('failed')
          }, EMBED_TIMEOUT_MS)
        : undefined

    return () => {
      observer.disconnect()
      if (timer) clearTimeout(timer)
    }
  }, [calLink, status, isOwner])

  return (
    <div className="rounded-2xl border border-[#e85d04]/25 bg-[#e85d04]/[0.07] p-3.5 backdrop-blur-md">
      <div className="flex items-start gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-tr from-[#e85d04] to-[#f48c06] text-white shadow-md shadow-orange-950/40">
          <CalendarDays className="size-4" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="font-large text-sm font-semibold text-white">
            {payload.label || 'Book a chat'}
          </div>
          {payload.note ? (
            <p className="mt-0.5 text-xs leading-relaxed text-zinc-400">
              {payload.note}
            </p>
          ) : null}
        </div>
      </div>

      {/*
        The calendar itself. Always in the tree once we have a slug, because
        Cal mounts into this node -- hiding it with a conditional would remove
        the very element the script is told to fill.
      */}
      {/*
        Collapsed rather than hidden when the embed fails: `display:none` would
        stop Cal ever rendering into this node, turning a slow load into a
        permanent failure.
      */}
      {calLink && isOwner ? (
        <div
          className={
            status === 'failed'
              ? 'pointer-events-none h-0 overflow-hidden'
              : 'mt-3'
          }
          aria-hidden={status === 'failed'}
        >
          {/*
            A minimum height, no maximum. Cal starts its iframe at 300px and
            resizes it as the visitor moves through the flow, so the container
            must have room to show something immediately -- with no height and
            `overflow-hidden` it collapsed to 0px and the calendar never
            appeared -- but must not cap the grown height either.
          */}
          <div
            ref={containerRef}
            className="min-h-[560px] w-full rounded-xl border border-white/10 bg-[#0a0f1e] [&_iframe]:!w-full"
          />
          {status === 'loading' ? (
            <p className="mt-2 text-center text-xs text-zinc-500">
              Loading his calendar…
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="mt-2.5 flex items-center justify-between gap-2">
        {!isOwner ? (
          // Not a failure: a superseded card is deliberately link-only, so it
          // must not claim the calendar broke.
          <span className="text-xs text-zinc-600">Pick a time on cal.com</span>
        ) : status === 'failed' ? (
          <p className="text-xs text-zinc-500">
            The calendar could not load here — this link still works.
          </p>
        ) : (
          <span className="text-xs text-zinc-600">Pick a slot above</span>
        )}

        <a
          href={payload.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-xl border border-white/10 px-3 py-1.5 font-mono text-xs text-zinc-300 transition-all hover:border-[#e85d04]/60 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#f48c06] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a0f1e]"
        >
          <span>Open on cal.com</span>
          <ArrowUpRight className="size-3.5" aria-hidden="true" />
        </a>
      </div>
    </div>
  )
}

BookingCard.displayName = 'BookingCard'

export default BookingCard
