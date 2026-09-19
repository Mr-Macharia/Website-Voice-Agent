# Feature 15: Booking card in voice mode

**Type:** Feature
**Feature ID:** 15 · **Build attempt:** 1
**Status:** verified — card confirmed rendering in the voice modal in a browser; mirroring gap found there and fixed
**Branch:** `feature/voice-booking-card`

## Why

A live voice session produced this:

> "You can grab a time here: cal dot com slash macharia, slash a i and
> automation consultation."

The slug is spelled out letter by letter, because `core/tools/booking.py:58`
tells the model to read the link as "cal dot com slash macharia" and stops
there, leaving it to improvise the rest. Nobody can transcribe that by ear, and
a visitor who mishears it does not reach the booking page.

Feature 14 solved exactly this in text chat: `get_booking_link` renders a card
with the Cal.com calendar embedded. Voice reads the same tool's return value
aloud instead. This feature puts the card on screen during a voice call, so the
visitor picks a slot rather than writing down a URL.

The groundwork is already in place, which is why this is small:

- Voice tool calls execute **client-side**, in React:
  `AssemblyAISession.handleToolCall` (`AssemblyAISession.ts:350`) receives
  `tool.call` and relays it to `/api/voice/tool`.
- `BookingCard` takes a plain `BookingPayload`, not a message object. It was
  built that way in feature 14 specifically so voice could reuse it unchanged.
- The modal already renders a scrolling transcript of `Turn` objects
  (`AssemblyAIVoiceModal.tsx:39`), so a card is one more turn kind.

## In scope

- The booking card rendered in the voice transcript when `get_booking_link`
  runs during a voice session.
- The spoken line shortened so the agent stops at `cal.com/macharia` and never
  spells out a slug. Verified: `https://cal.com/macharia` returns 200, so the
  short form is a real booking page, not a guess.

## Out of scope

- **The lead form in voice.** Typing into a form while the agent is listening
  is a different interaction problem (does the mic pause on focus?) and needs
  design, not assumption. `capture_lead` keeps its current spoken behaviour.
- The LiveKit modal. It is the dormant fallback path.
- Any change to what the agent says beyond the booking line.

## Build steps

- [x] **Return the payload to the browser without speaking it.**
   `core/adapters/assemblyai.py:278` currently returns
   `ui_payload.strip_payload(str(result))`, so the browser never sees the
   `url`. Return both parts instead: the stripped speakable string, and the
   parsed payload as a separate field. `/api/voice/tool` (`server.py:408`)
   passes it through as `{result, ui}`.

   `result` must stay **byte-identical** to what it returns today. It is what
   the agent reads aloud, and this feature must not change the spoken output
   except through step 4.

   *Done when:* `POST /api/voice/tool` with `get_booking_link` returns the same
   `result` string as before plus a `ui` object carrying the booking url, and
   a tool with no payload returns `ui: null`.

- [x] **Surface it to React.** Add one callback to `VoiceSessionCallbacks`
   (`AssemblyAISession.ts:33`) — the existing pattern — fired from
   `handleToolCall` when the response carries a `ui` payload. Parse it with the
   shared `parseToolPayload` so the validation (including the http/https URL
   check) is the same code the text chat uses.

   *Done when:* a voice booking call invokes the callback with a parsed
   `BookingPayload`, and a tool call without one does not fire it.

- [x] **Render the card as a transcript turn.** Extend `Turn`
   (`AssemblyAIVoiceModal.tsx:39`) with a card kind carrying the payload, and
   render `BookingCard` for it. Reuse the component unchanged; do not fork it.

   Constraints: the modal is narrower than the chat column, so the calendar
   will fall to Cal's mobile layout — that is correct there, not a bug. The
   card must not break the transcript scroll, and a second booking call in one
   session must not stack duplicate cards.

   *Done when:* asking to book by voice shows the card in the transcript with a
   working calendar, and asking twice does not render it twice.

- [x] **Shorten the spoken link.** In `core/tools/booking.py:58`, tell the model to
   say "cal dot com slash macharia" and stop — never to spell out the event
   slug. The card carries the full URL, so the spoken form only has to get them
   to the right page.

   *Done when:* a live voice booking speaks the short form with no
   letter-by-letter slug.

## Correction: the card was missing from the written transcript

Confirmed in the browser: the card renders in the voice modal. That session
also surfaced a gap the endpoint tests could not.

Voice already mirrors its spoken turns into the main chat panel
(`appendToChat`), so a session leaves behind a readable conversation. The card
was not mirrored, so the written record disagreed with what happened: the agent
offered a booking and no booking appeared. Asking for the same thing by text
produced a card, which made the inconsistency sharper.

`appendCardToChat` now writes the payload back as a `tool_calls[].result` entry
in the same marker form a text-mode tool produces, so the existing `ToolCards`
path renders it with no voice special case. It fires only when the modal
actually added a card, so the dedupe guard covers both surfaces and a second
booking request cannot mirror a duplicate.

Verified by round-tripping the exact string `appendCardToChat` writes through
`toolResultText` + `parseToolPayload` — the same functions the chat uses — which
returns the booking payload. Fixing this also surfaced a real
`react-hooks/exhaustive-deps` warning on the session effect: the new callback
was missing from its dependency array, which would have let a stale closure
stop mirroring silently.

## Files / areas

| Area | Path |
|---|---|
| Voice tool return | `backend/core/adapters/assemblyai.py:278` |
| Voice tool endpoint | `backend/server.py:408` |
| Session callbacks | `frontend/src/lib/voice/AssemblyAISession.ts:33,350` |
| Transcript + Turn | `frontend/src/components/voice/AssemblyAIVoiceModal.tsx:39` |
| Spoken wording | `backend/core/tools/booking.py:58` |

**Reuse, do not rebuild:** `BookingCard.tsx`, `parseToolPayload`
(`lib/toolPayload.ts`), `lib/calEmbed.ts`, and the existing
`VoiceSessionCallbacks` pattern.

## Verify

1. Open voice, say "I want to book a meeting." The card appears in the
   transcript with the calendar, and the agent says the short link with no
   spelled-out slug.
2. Ask again in the same session — no duplicate card.
3. Text chat still renders its booking card unchanged (shared tool path).
4. Ask for something else by voice (`search_about_owner`) — no card, no
   change in spoken output.
5. Block `app.cal.com` in devtools and book again — the card falls back to the
   link, matching text-chat behaviour.

## Notes

- `provision_agent.py` bakes the persona and tool descriptions into the stored
  AssemblyAI agent. Step 4 changes a tool's return string, not its description,
  so it needs **no** re-provision. Confirm this during the step; if it turns out
  the description changed, re-provision with `--update`.
- The Heroku proxy runs the voice model conversation and is currently behind
  master. Voice wording changes will not fully match local until it is deployed.
- F-07 (rate-limit eviction) is open and touches `/api/voice/tool`, which this
  feature modifies. Do not fix it here; keep the diffs separate.
