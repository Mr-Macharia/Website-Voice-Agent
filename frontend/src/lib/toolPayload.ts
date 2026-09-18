/**
 * Parse the structured UI payload a tool appends to its result.
 *
 * Tools return one string serving two audiences: a sentence the voice channel
 * speaks aloud, and -- for the tools worth rendering -- a machine-readable
 * marker the chat uses to draw a real component. The backend writes it in
 * `core/ui_payload.py`; the delimiters below must stay in sync with that file.
 *
 *     Booking link: https://cal.com/...
 *     <<<ui:{"type":"booking","url":"https://cal.com/..."}>>>
 *
 * The marker is always the last line and always compact JSON, so a partial
 * stream chunk either contains the whole thing or none of it.
 */

const OPEN = '<<<ui:'
const CLOSE = '>>>'

// Anchored to the end, single line. No `s` flag: a newline inside means the
// marker is malformed, and half-parsing it is worse than ignoring it.
const PAYLOAD_RE = /\n*<<<ui:([^\n]*?)>>>\s*$/

export interface BookingPayload {
  type: 'booking'
  url: string
  label?: string
  note?: string
}

export interface LeadFormPayload {
  type: 'lead_form'
  fields?: string[]
  known?: Record<string, string>
}

export interface LeadSavedPayload {
  type: 'lead_saved'
  lead_id?: number
}

export type ToolPayload = BookingPayload | LeadFormPayload | LeadSavedPayload

/**
 * Empty fenced blocks, as a run of "```json {}" pairs.
 *
 * The stream handler used to append `getJsonMarkdown(chunk.content)` for any
 * non-string chunk content, which turned a run of empty protocol objects into
 * pages of visible "```json {}" in the bubble. That branch is gone, but
 * sessions saved while it existed still hold the blocks, so replayed content
 * is cleaned on the way to the screen.
 *
 * Fence runs are matched as `{3,}: the leak used six backticks, not three.
 */
const FENCE_RUN_RE = /`{3,}[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n?/g
const EMPTY_BODY_RE = /^\s*(?:\{\s*\}|\[\s*\])?\s*$/

/**
 * Remove empty fenced blocks, leaving blocks that have real content.
 *
 * Scanned rather than done with one regex. The leaked output is a run of
 * consecutive *openers* with no closers ("``````json {} ``````json ..."), so
 * treating the next fence run as a closer makes "json\n{}" look like a real
 * body and keeps it on screen. A fence run carrying a language tag is a new
 * opener, not a closer.
 */
export function stripEmptyFences(text?: string | null): string {
  if (!text) return ''
  if (!text.includes('```')) return text

  const out: string[] = []
  let pos = 0
  let changed = false

  FENCE_RUN_RE.lastIndex = 0
  let opener = FENCE_RUN_RE.exec(text)
  while (opener) {
    const ticks = (opener[0].match(/`/g) ?? []).length
    const openEnd = opener.index + opener[0].length

    // A fence run NOT followed by a language tag can close this block.
    const closerRe = new RegExp(
      '`{' + ticks + ',}(?![ \\t]*[A-Za-z0-9_+-])',
      'g'
    )
    closerRe.lastIndex = openEnd
    const closer = closerRe.exec(text)

    FENCE_RUN_RE.lastIndex = openEnd
    const nextOpener = FENCE_RUN_RE.exec(text)

    let bodyEnd: number
    let consumeTo: number
    if (nextOpener && (!closer || nextOpener.index < closer.index)) {
      bodyEnd = nextOpener.index
      consumeTo = nextOpener.index
    } else if (closer) {
      bodyEnd = closer.index
      consumeTo = closer.index + closer[0].length
    } else {
      bodyEnd = text.length
      consumeTo = text.length
    }

    if (EMPTY_BODY_RE.test(text.slice(openEnd, bodyEnd))) {
      out.push(text.slice(pos, opener.index))
      changed = true
    } else {
      out.push(text.slice(pos, consumeTo))
    }
    pos = consumeTo

    FENCE_RUN_RE.lastIndex = consumeTo
    opener = FENCE_RUN_RE.exec(text)
  }
  out.push(text.slice(pos))

  if (!changed) return text
  return out
    .join('')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/**
 * The text a tool returned, whichever field carried it.
 *
 * The live run stream puts it on `result`; the session-replay path rebuilds
 * tool calls from `reasoning_messages`, where it lands on `content`. Reading
 * only one of them is what kept these cards from ever rendering, so both are
 * read here, in one place, rather than at each call site.
 */
export function toolResultText(toolCall: {
  result?: string | null
  content?: string | null
}): string | null {
  if (typeof toolCall.result === 'string' && toolCall.result) {
    return toolCall.result
  }
  if (typeof toolCall.content === 'string' && toolCall.content) {
    return toolCall.content
  }
  return null
}

/** Extract the payload from a tool result, or null when there isn't one. */
export function parseToolPayload(text?: string | null): ToolPayload | null {
  if (!text || !text.includes(OPEN)) return null
  const m = text.match(PAYLOAD_RE)
  if (!m) return null

  let data: unknown
  try {
    data = JSON.parse(m[1])
  } catch {
    return null
  }
  if (!data || typeof data !== 'object') return null

  const payload = data as { type?: unknown }
  if (payload.type === 'booking') {
    // A card without a usable link is worse than no card.
    const url = (data as BookingPayload).url
    if (typeof url !== 'string' || !isSafeHttpUrl(url)) return null
    return data as BookingPayload
  }
  if (payload.type === 'lead_form' || payload.type === 'lead_saved') {
    return data as LeadFormPayload | LeadSavedPayload
  }
  return null
}

/** Remove the marker, leaving only the human-readable sentence. */
export function stripToolPayload(text?: string | null): string {
  if (!text) return ''
  if (!text.includes(OPEN)) return text
  return text.replace(PAYLOAD_RE, '').trimEnd()
}

/**
 * The Cal.com booking slug from a full booking URL, or null.
 *
 * Cal's embed script binds to `data-cal-link`, which is the slug
 * ("macharia/ai-and-automation-consultation"), not a URL. Deriving it here
 * keeps the parsing out of the component, and means a non-Cal booking URL
 * simply renders as an ordinary link with no popup attached.
 */
export function calLinkFromUrl(value: string): string | null {
  try {
    const url = new URL(value)
    if (!/(^|\.)cal\.com$/i.test(url.hostname)) return null
    const slug = url.pathname.replace(/^\/+|\/+$/g, '')
    // A bare cal.com with no path has nothing to embed.
    return slug ? slug : null
  } catch {
    return null
  }
}

/**
 * Only http(s) may reach an href. The URL is backend-controlled today, but
 * this renders as a clickable link, and `javascript:` in an href is the
 * classic way that stops being true.
 */
export function isSafeHttpUrl(value: string): boolean {
  try {
    const { protocol } = new URL(value)
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}

export { CLOSE, OPEN }
