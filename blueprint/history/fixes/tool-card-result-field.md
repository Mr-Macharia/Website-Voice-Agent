# Fix: Tool cards never render — wrong field read from the tool event

**Type:** Fix
**Status:** verified — cards, form, voice regression and F-05 rate limiting all confirmed
**Branch:** `fix/tool-card-result-field`
**Fixes:** the booking card and lead form shipped in feature 14, which have
never rendered once in the browser.

## The problem

Feature 14 added a booking card and a lead-capture form that render from a
sentinel payload appended to a tool's return value. Neither has ever appeared.

Captured from the live SSE stream (`POST /agents/site-agent/runs`, streaming,
real DeepSeek run), the `ToolCallCompleted` event carries the tool's return
value on **`tool.result`**:

    tool keys   : ['tool_call_id', 'tool_name', 'tool_args', 'tool_call_error',
                   'result', 'metrics', ...]
    tool.result : 'Booking link: https://cal.com/macharia/... <<<ui:{...}>>>'
    tool.content: None

The frontend reads **`toolCall.content`** — `ToolCall.content` in
`frontend/src/types/os.ts:3`, consumed by `ToolCards` in
`Messages.tsx:155`. That field does not exist on this Agno version's tool
object, so `parseToolPayload(undefined)` returned `null` on every tool call and
`ToolCards` rendered nothing, every time.

The same mismatch hits session replay: `useSessionLoader.tsx:97` spreads
`run.tools` through unchanged, so stored runs carry `result` too.

This was missed because feature 14 was verified by reading the producing code
and the consuming code, and by calling `text_agent.run()` server-side — never by
inspecting the bytes on the wire between them. The plan asserted the transport
already worked; it did not.

Two further points from the report, checked against the same capture:

- **"JSON appears before text."** The assistant text in the capture is clean —
  no sentinel, no control token. What the screenshot shows is the tool pill
  strip above the reply. The sentinel reaching a visible surface is still
  possible wherever raw tool text is shown, so the parser fix must strip it at
  every read site, not only where a card replaces it.
- **"Still just a link."** Correct, and it does not have to be. Cal.com
  publishes `@calcom/embed-react` (v1.5.3, verified on the registry), which
  renders the real booking calendar inline. A visitor picks a slot without
  leaving the chat.

Voice routing is untouched by this fix and by feature 14: AssemblyAI remains the
default, and `core/adapters/livekit.py` is only edited to keep the dormant path
from speaking the marker.

## The fix

**1. Read the field Agno actually sends.** Treat `result` as the primary source
and `content` as a fallback, so the fix survives both schema spellings rather
than trading one hard-coded guess for another. Add `result?: string | null` to
`ToolCall`, and read through one helper (e.g. `toolResultText(toolCall)`) used
by `ToolCards` and by anything else that reads tool text. Do not scatter
`?? toolCall.result` across call sites.

Must not break: `useSessionLoader.tsx:97-117`, which builds `ToolCall` objects
from `reasoning_messages` where `content` *is* the populated field.

**2. Embed the real Cal.com calendar.** Add `@calcom/embed-react` and render the
booking payload as an inline calendar in `BookingCard.tsx`, keeping the existing
link visible as a fallback for when the embed fails or is blocked. The embed
loads third-party script and frames, so: it must not break the chat if it fails
to load, it must be constrained to the message column width, and the link must
remain usable on its own. Derive the Cal link from `payload.url` — do not
hardcode the slug.

If the embed proves unworkable inside the message column (height, theming, or
load failure), keep the current card and say so. A working link beats a broken
calendar.

## Build steps

- [x] 1. **Fix the field read.** Add `result` to `ToolCall`, add the accessor, use it
   in `ToolCards`. *Done when:* the captured `ToolCallCompleted` payload parses
   to a `booking` object, and asking to book renders the card in the browser.

- [x] 2. **Embed the calendar.** Add the dependency, render the embed in
   `BookingCard.tsx` with the link retained. *Done when:* the calendar appears
   inline in the chat, a slot can be selected, and blocking the Cal script still
   leaves a working link.

## Correction: the embed package was replaced

The first attempt at step 2 used `@calcom/embed-react` behind `next/dynamic`.
It threw `ChunkLoadError` on render in dev: the package ships ESM-only `.mjs`
in a package without `"type": "module"`, and webpack advertised a chunk it then
served as 404. The production build hid this by inlining the module into the
page bundle instead of splitting it, so the build passing proved nothing.

Replaced with Cal.com's embed script loaded through `next/script`, calling
`Cal("inline", { elementOrSelector, calLink, config })` against a ref -- the
same call the React package made, without the unchunkable module. The npm
dependency is removed; it was only a ~2KB wrapper around this script.

An intermediate attempt used `data-cal-link`, which opens Cal's popup. That was
a misread of the requirement: the calendar belongs *inline in the chat message*,
so the visitor picks a slot without leaving the conversation. Inline mode is
what the card does now.

Two layout consequences of living in the message column:

- The booking card takes the full column width (`w-full`), not the `max-w-[88%]`
  the other bubbles use. The column is `max-w-3xl` (768px); 88% of it left the
  calendar too narrow.
- The embed uses `layout: "column_view"`, Cal's narrow-container layout.
  Verified against the live script: it auto-switches to a mobile layout below
  768px and forwards any other layout value to the booking page, which returns
  200 for `column_view`.

The link out to cal.com is kept below the calendar. The embed is third-party
script in an iframe, so a MutationObserver watches for the iframe and a 10s
timeout collapses the card to link-only if it never arrives.

## Correction 2: embed.js requires a loader, and the model was drawing the form

**The empty card.** Loading `embed.js` with a plain script tag produced a card
that reported "the calendar could not load". The script's own last lines are:

    const h = window.Cal;
    if (!h || !h.q) throw new Error("Cal is not defined. This shouldn't happen");

It does not bootstrap itself. `window.Cal` must already exist as a queueing stub
*before* it loads, or it throws on parse. That stub is what
`@calcom/embed-snippet` installs and what the React wrapper ran before mounting.
`frontend/src/lib/calEmbed.ts` now reproduces it: `loadCalApi()` installs the
stub, injects the script once per page, and queues calls made before it lands.

**Cal.com Atoms were considered and rejected.** Cal's own docs put
`@calcom/atoms` in maintenance mode ("no new atoms are planned"), and it is
built for a different problem: OAuth-connected users managing *their own*
scheduling inside a host app. This card needs anonymous visitors booking the
owner's calendar, which is what the embed does without an OAuth flow.

**Hallucinated UI markup.** A live run emitted a literal `<form></form>` into
the reply text, and a reported run produced a long run of empty ```json blocks.
The model is told a form appears and some runs try to draw it. Two changes:

- `core/persona.py` gains a text-channel rule that the interface is not the
  model's to draw, naming the exact failure modes. Voice is unaffected.
- `core/guardrails.py` gains `strip_ui_markup`, wired into `clean_output`, since
  a persona rule is a strong prior and not a guarantee. It removes form/input/
  label/button tags and empty fenced blocks, while leaving real code blocks and
  the booking URL intact.

The empty-fence removal took two corrections, both caught by the reported
output rather than by the first test:

1. The first version anchored on exactly three backticks. Live output used
   **six**, so the pattern chewed the fences off and left `json {}` behind as
   visible text -- worse than the leak. Fence runs are now matched as `` `{3,} ``.
2. Treating the next fence run as the block's closer then made
   ``` ``````json {} ``````json ``` parse as one block with a real body. That
   output is consecutive *openers* with no closers, so a fence run carrying a
   language tag is now read as a new opener. This needed a scan over fence runs
   rather than a single regex.

Covered by ten cases including the exact reported paste (strips to empty),
three- and six-backtick loops, unterminated fences, and real python/json/js
blocks, which survive with their fences intact.

Verified across three consecutive live lead runs and one booking run: zero
markup leaks, correct payload emitted every time.

## Correction 3: the `{}` blocks were the UI's, not the model's

The reported "```json {}" blocks appeared on every tool call. They were not
model output at all, and the backend guardrail could never have caught them:
the frontend was generating them from protocol data.

`getJsonMarkdown(content)` wrapped any non-string content in a ```json fence,
and it was called from two places:

- `useAIStreamHandler.tsx` -- for any streamed chunk whose `content` was not a
  string, appended straight into the message bubble.
- `useSessionLoader.tsx` -- for any *stored* message whose content was not a
  string, on session replay.

Tool messages carry `tool_args: {}` for a no-argument tool, and both
`get_booking_link` and `capture_lead` take no arguments. So every tool call
produced an empty `{}` block, and a replayed session reproduced one per call.

Both call sites are removed, along with the now-unused helper. Protocol data is
not visitor-facing text; there is no case where dumping it into the bubble is
correct.

`stripEmptyFences` in `lib/toolPayload.ts` also cleans message content on the
way to the screen, so sessions already saved with these blocks render correctly.
It uses the same fence-run scan as the backend, for the same reason: the leak
used six-backtick fences, and a regex assuming balanced ``` fences left
`json {}` behind as visible text.

## Booking link configuration

The booking URL is already a single setting: `CALCOM_BOOKING_URL` in the root
`.env`, read via `core/config.py`. It flows to the persona, the tool result, the
UI payload and the embedded calendar, so changing that one line changes all of
them. Note `config.py` calls `load_dotenv(override=True)`, so the `.env` value
wins over a shell environment variable.

## Calendar layout: the problem was height, not width

Reported as "a bit too wide". The screenshots showed the opposite cause: the
month grid rendered, then a large gap, then the slot list far below it, cropped
behind a scrollbar. Narrowing would have made that worse.

Two causes, both fixed:

- **`column_view` stacks the slot list under the calendar.** `month_view` puts
  it beside. Cal falls back to its own mobile layout under 768px anyway, so
  `month_view` is the correct choice for a wide container.
- **The 620px fixed height cropped it.** Cal's embed reports its own size and
  resizes the iframe as the visitor moves through the flow.

Removing the height outright then broke the embed entirely ("The calendar could
not load here"): the container was `overflow-hidden` with no height, so it
collapsed to 0px and Cal had nothing to render into. It carries `min-h-[560px]`
now -- a floor with no ceiling, so the embed shows immediately and can still
grow.

Two related failure-path bugs found at the same time:

- The failed state applied `hidden` (`display:none`) to the container, which
  would have stopped Cal rendering into it even if the script arrived a moment
  later. It is collapsed with `h-0` and kept in the layout instead.
- The iframe watcher stopped once it declared failure, so a late-arriving embed
  was never noticed. It now keeps observing and can recover; only the first
  pass may declare failure.

The chat column is `max-w-3xl` (768px), which is *exactly* Cal's mobile
breakpoint, so the card could never get the wide layout while confined to it.
The booking card now breaks out of the column with negative margins
(`lg:-mx-16`, `xl:-mx-24`), giving the embed 868-932px on desktop and clearing
the breakpoint. Below `lg` the margins collapse to 0 and Cal's mobile layout
takes over, which is built to stack.

- [x] **Build step 3 — rate-limit the public endpoints (repairs F-05)**

`/audit` opened **F-05 [P1]**: `/api/leads` is public, unauthenticated and
unthrottled, and every POST both writes a Postgres row and emails the owner's
own mailbox. `/api/voice/tool` shares the exposure. This step repairs it.

Add a small in-process, per-IP limiter in `backend/core/rate_limit.py` and apply
it to both endpoints. No new dependency: a fixed-window counter over
`request.client.host` is enough at this traffic level, and slowapi would pull in
a limiter framework for two routes.

Constraints:

- Rejections return the same readable `{ok, message}` shape the lead form
  already renders on failure, with HTTP 429, not a raw framework error.
- Honour `X-Forwarded-For`'s first hop when present, because Heroku terminates
  TLS at a router and `request.client.host` would otherwise be one shared
  proxy address for every visitor.
- The store must be bounded. An unbounded dict keyed on client IP is itself a
  memory-growth vector on a public endpoint.
- Never raise on the hot path, per the project's non-raising tool contract.

**Done when:** repeated POSTs past the limit return 429 with a readable message,
a request under the limit still succeeds, and the limiter is proven to expire
its window rather than blocking permanently.

## Verify

Run the app (`npm run dev:all`) and, in the browser:

1. Ask "I'd like to book a chat" — the booking card renders, with the inline
   calendar and a working link. No JSON or sentinel text anywhere on screen.
2. Say "take my details" — the lead form renders; submitting inserts exactly one
   Postgres row.
3. Reload the session — both still render from stored runs, not bare pills.
4. Open voice and ask to book — the link is still spoken naturally, with no
   sentinel read aloud.

Browser verification is required to close this fix. It is the step feature 14
skipped, and skipping it is why these bugs shipped.

## Findings

### tool-card-result-field/F-01 [P1] closed - Three agent-name fallbacks still say "Realtime Voice Assistant"

**File:** frontend/src/components/chat/ChatArea/ChatArea.tsx:25
**Found:** 2026-09-18 by /audit (scope: changed; lens: quality)
**Why it matters:** The rebrand changed the two fallbacks inside
`components/voice/` but missed the three in `components/chat/` that actually
feed them: `ChatArea.tsx:25`, `ChatInput.tsx:24-25`, and `Sidebar.tsx:263`.
These are not dead defaults. `activeAgentName` resolves from
`agents.find(a => a.id === <?agent= query param>)?.name`, and the param is
empty until `useChatActions` has fetched the agent list and auto-selected
`agents[0]`. During that window, and on every load where the backend is
unreachable, the chat header, the transcript export prefix, and the voice
control bar all render "Realtime Voice Assistant" instead of "Clyde". The
transcript case is the worst of the three: `ChatArea.tsx:33` bakes the name
into copied text the visitor keeps.
**Suggested fix:** Change the fallback string to `'Clyde'` in all three files.
**Resolution:** Fixed 2026-09-18 by /audit repair. Fallback set to `'Clyde'` in ChatArea.tsx:23, ChatInput.tsx:24 and Sidebar.tsx:262. A repo-wide grep for "Realtime Voice Assistant" now returns nothing across backend/ and frontend/src/. Closed 2026-09-19 by /audit (scope: current; all lenses): re-read all three call sites — ChatArea.tsx:23, ChatInput.tsx:24 and Sidebar.tsx:262 each resolve to 'Clyde'; repo-wide grep still returns 0.

### tool-card-result-field/F-02 [P2] closed - The second registered agent is still named "Realtime Voice Assistant"

**File:** backend/server.py:97
**Found:** 2026-09-18 by /audit (scope: changed; lens: quality)
**Why it matters:** Only `text_agent` was renamed to Clyde. `voice_agent`
(`server.py:95-110`) keeps its old name and is registered in
`AgentOS(agents=[text_agent, voice_agent])` at `server.py:934`, so it appears
in the frontend's agent picker as a selectable second identity. Both agents
share `persona.py`'s `_IDENTITY`, which now states "You are Clyde" — so
selecting it produces an agent labelled "Realtime Voice Assistant" in the UI
that introduces itself as Clyde. One assistant presenting under two names is
exactly the split-identity problem `persona.py`'s module docstring says this
project already fixed once.
**Suggested fix:** Rename `voice_agent` to `"Clyde"` as well, or give it a
label that reads as the same assistant on a different channel.
**Resolution:** Fixed 2026-09-18 by /audit repair. voice_agent renamed to "Clyde" (server.py:101) with a comment recording why both agents share one name. The same agent in the MCP server (voice_mcp/voice_agent_server.py:113) was renamed too — it was outside the original finding and would otherwise have kept the old name. Closed 2026-09-19 by /audit (scope: current; all lenses): server.py:179 and server.py:200 both read name="Clyde".

### tool-card-result-field/F-03 [P2] closed - LiveKit fallback path was not rebranded

**File:** frontend/src/components/voice/LiveKitVoiceModal.tsx:1598
**Found:** 2026-09-18 by /audit (scope: changed; lens: quality)
**Why it matters:** The rebrand deliberately skipped `LiveKitVoiceModal.tsx` on
the stated grounds that no visitor sees it. That premise is wrong:
`VoiceModal.tsx:25-32` branches on `NEXT_PUBLIC_VOICE_PROVIDER === 'livekit'`,
and `AGENTS.md` documents that flag as a supported fallback. Whenever it is
set, visitors get `agentName = 'Realtime Voice Assistant'` plus "Deepgram Voice
Bridge", "Nova-3 STT / Flux TTS" and "Deepgram Flux TTS" — the full pre-rebrand
vendor copy the change set out to remove.
**Suggested fix:** Either apply the same copy pass to the LiveKit modal, or
confirm the fallback is retired and delete the branch. Leaving it as a
reachable path with stale branding is the state to avoid.
**Resolution:** Fixed 2026-09-18 by /audit repair. LiveKitVoiceModal.tsx: agent-name fallback, sr-only DialogTitle, header label, badge, three status messages, connect toast and visualizer label rebranded. `mode=` deliberately kept LiveKit-identifying ("LiveKit voice") because VoiceAgentControlBar derives `isLiveKit` from it. The sr-only DialogTitle in the *active* AssemblyAIVoiceModal.tsx:179 was also stale and fixed. Closed 2026-09-19 by /audit (scope: current; all lenses): LiveKitVoiceModal.tsx re-read; no stale name remains repo-wide.

### tool-card-result-field/F-05 [P1] closed - /api/leads is public, unauthenticated and unthrottled

**File:** backend/server.py:445
**Found:** 2026-09-19 by /audit (scope: current; lens: security)
**Why it matters:** Every POST writes a row to Postgres (`_insert_lead`) and
sends an email to `LEAD_NOTIFY_EMAIL` (`leads.py:63`). There is no
authentication, no rate limit, no CAPTCHA and no origin check — `grep` for
`rate_limit|slowapi|limiter` across `server.py` returns nothing. A trivial
loop against the endpoint fills the leads table and floods the owner's inbox,
and the SMTP account is the owner's own. The feature spec called for this
("Consider basic abuse resistance; this writes to Postgres from an
unauthenticated public form") and it was not implemented. Field lengths are
capped, which bounds each request's size but not the request count.
**Suggested fix:** Add a per-IP rate limit on `/api/leads` — a small in-process
counter keyed on `request.client.host` with a short window is enough given the
expected volume, and avoids a new dependency. Return the same readable
`{ok, message}` shape on rejection so the form's existing failure path renders
it. `/api/voice/tool` shares the exposure and is worth the same treatment.
**Resolution:** Fixed 2026-09-19 by /implement. Added `backend/core/rate_limit.py`: an in-process fixed-window per-IP counter with a bounded store (`_MAX_TRACKED=4096`, LRU eviction), keyed on the first `X-Forwarded-For` hop so Heroku's router is not treated as one client. Applied to `/api/leads` (5 per 300s, HTTP 429 + `Retry-After` with the same `{ok, message}` shape the form renders) and `/api/voice/tool` (60 per 60s, returning a speakable string so the agent recovers aloud). Limits live in `core/config.py` per the standards. Verified over HTTP: requests 1-3 passed and 4-5 returned 429 at limit=3; a second IP was unaffected; window expiry releases the block; the store stays at 4096 entries under 4596 distinct clients; a valid lead still saved exactly one row. Closed 2026-09-19 by /audit (scope: current; all lenses): re-read `core/rate_limit.py` and both call sites. The limiter runs before any side effect on each endpoint; `check()` is synchronous so it is atomic under asyncio (50 concurrent requests at limit 10 allowed exactly 10, no lost updates); the non-raising contract holds against a request whose `.headers` raises; keys are capped at 64 chars and empty/whitespace/comma-only forwarded values fall back to `request.client.host`. The residual eviction weakness is tracked separately as F-07, which does not reinstate this finding: the unthrottled path is gone.
