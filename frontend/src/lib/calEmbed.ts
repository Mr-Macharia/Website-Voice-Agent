/**
 * Cal.com's embed loader.
 *
 * `https://app.cal.com/embed/embed.js` does NOT bootstrap itself. Its last
 * lines are:
 *
 *     const h = window.Cal;
 *     if (!h || !h.q) throw new Error("Cal is not defined. This shouldn't happen");
 *
 * So `window.Cal` must already exist, as a function with a queue, *before* the
 * script loads -- otherwise it throws on parse and nothing mounts. This is the
 * snippet `@calcom/embed-snippet` installs, and the reason loading the script
 * with a plain <script> tag silently produced an empty card.
 *
 * Calls made before the script finishes are pushed onto `Cal.q` and replayed
 * by the real implementation once it takes over, so callers never have to wait.
 */

const EMBED_JS_URL = 'https://app.cal.com/embed/embed.js'

export type CalApi = ((...args: unknown[]) => void) & {
  ns?: Record<string, CalApi>
  q?: unknown[]
  loaded?: boolean
}

interface CalWindow extends Window {
  Cal?: CalApi
}

/**
 * Install the stub and inject the script, once per page.
 *
 * Returns the queueing `Cal` function, or null outside the browser. Safe to
 * call repeatedly: every booking card calls it, and only the first injects.
 */
export function loadCalApi(embedJsUrl: string = EMBED_JS_URL): CalApi | null {
  if (typeof window === 'undefined') return null

  const win = window as CalWindow
  const doc = window.document

  if (!win.Cal) {
    const cal: CalApi = function (...args: unknown[]) {
      const c = win.Cal as CalApi
      if (!c.loaded) {
        c.ns = {}
        c.q = c.q || []
        // The script tag must exist before the first queued call is replayed.
        doc.head.appendChild(doc.createElement('script')).src = embedJsUrl
        c.loaded = true
      }
      // `Cal("init", "namespace")` creates a namespaced queue of its own.
      if (args[0] === 'init') {
        const namespace = args[1]
        if (typeof namespace === 'string') {
          const ns = cal.ns as Record<string, CalApi>
          if (!ns[namespace]) {
            const nsApi: CalApi = function (...nsArgs: unknown[]) {
              nsApi.q?.push(nsArgs)
            }
            nsApi.q = []
            ns[namespace] = nsApi
          }
          ns[namespace].q?.push(args)
          return
        }
      }
      c.q?.push(args)
    }
    cal.q = []
    win.Cal = cal
  }

  return win.Cal ?? null
}

/** The queueing Cal function if it has been installed, else null. */
export function getCal(): CalApi | null {
  if (typeof window === 'undefined') return null
  return (window as CalWindow).Cal ?? null
}
