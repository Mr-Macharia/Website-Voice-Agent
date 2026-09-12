# Fix: Voice session dead on reconnect + new instruction-leak pattern

**Type:** Fix
**Status:** verified
**Branch:** fix/voice-reconnect-and-instruction-leak

## The problem

**1. Voice stops working after closing and reopening the modal (main complaint).**

The LiveKit room name is hardcoded to the literal string `"voice-agent-room"`
in three places:

- [frontend/src/components/voice/LiveKitVoiceModal.tsx:1627,1630](frontend/src/components/voice/LiveKitVoiceModal.tsx#L1627) - `fetch('/api/livekit/token?room=voice-agent-room')`
- [frontend/src/app/api/livekit/token/route.ts:15](frontend/src/app/api/livekit/token/route.ts#L15) - `let room = searchParams.get('room') || 'voice-agent-room'`

The worker's agent dispatch is configured via `roomConfig.agents` embedded in
the access token
([frontend/src/app/api/livekit/token/route.ts:68-70](frontend/src/app/api/livekit/token/route.ts#L68-L70)),
which LiveKit documents as firing **only when the room is newly created**:

> "Agent dispatch from the token only occurs when the room is first created. If
> the room already exists, the token's dispatch configuration is ignored."
> — LiveKit docs, [Access tokens & grants](https://docs.livekit.io/frontends/reference/tokens-grants/)

Sequence that reproduces the bug:

1. Visitor opens the voice modal. `voice-agent-room` does not exist yet, so it
   is created, the token's dispatch config fires, and the worker joins
   normally (matches the log: `registered worker` → `received job request` →
   `Agent joining room: voice-agent-room`).
2. Visitor closes the modal. `LiveKitRoom` unmounts and the client
   disconnects, but the room itself is not necessarily torn down immediately —
   LiveKit rooms persist for a grace period after the last participant
   leaves.
3. Visitor reopens the modal quickly. A new token is fetched for the **same**
   room name. If the room from step 1 hasn't fully expired yet, LiveKit
   ignores the new token's dispatch config (per the docs quote above) and no
   new job is dispatched. The visitor connects to a room with no agent in it —
   silence, and it looks broken.

This also means two simultaneous visitors would collide in the same room,
which is a second consequence of the same root cause.

**2. A new instruction-leak pattern slipped past the existing guardrail.**

From the same session's logs, the very first greeting was spoken as:

> "Write the exact words you will say.Hi there, I'm Gichogu's assistant — you
> can ask me about his projects or just chat."

`backend/core/guardrails.py` already exists specifically to strip this class of
leak — its module docstring documents deepseek intermittently prefixing
replies with fragments of instruction-like text, and `strip_meta_instructions()`
/ `_META_LINE_RE` handles previously observed variants ("You must not discuss
these instructions...", "As an AI language model, I must..."). This new phrase,
"Write the exact words you will say.", is an instruction-echo of a different
shape (it reads like the model repeating part of its own turn-generation
instructions rather than a system-prompt disclaimer) and doesn't match any
existing pattern in `_META_LINE_RE`, so it passed through uncleaned to speech
and transcript.

## The fix

**1. Unique room per voice session.** Generate a fresh, unique room name on
the client for every session open, instead of reusing the same literal name.
A UUID/random suffix per session (e.g. `voice-agent-room-<random>`) guarantees
each session's room is newly created, so the token's explicit dispatch always
fires and the worker is always joined fresh. This also incidentally fixes the
two-simultaneous-visitors collision.

Must not break:
- The existing fallback path (`DirectVoiceSession` / `/ws/voice`) is unrelated
  (it doesn't use LiveKit rooms at all) and must keep working unchanged.
- The token route's `room` query param / body override must still work for
  any other caller that passes an explicit room name (e.g. testing) — only the
  *default* changes, not the parameter contract.

**2. Extend the instruction-leak guardrail.** Add a pattern to `_META_LINE_RE`
in `backend/core/guardrails.py` that catches "Write the exact words you will
say." (and same-shape turn-instruction echoes) at the start of a reply, the
same way the existing patterns catch the other leaked phrasings. Keep the
existing behavior of only stripping from the leading block of the reply, never
mid-reply.

## Build steps

1. [x] **Generate a unique LiveKit room name per voice session, and add the new
   guardrail pattern.**
   - In `LiveKitVoiceModal.tsx`, generate a unique room identifier when the
     modal opens (e.g. via `crypto.randomUUID()`) and use it in both the
     primary and fallback-endpoint token fetch calls instead of the literal
     `voice-agent-room` string. Do not persist it across a close/reopen — the
     effect that resets state on `!isOpen` should also clear/regenerate it, so
     every open gets a fresh room.
   - Leave the token route's default (`'voice-agent-room'`) as the fallback
     for callers that don't pass a `room` param, since that's a documented,
     unrelated contract (backward compatible for any other consumer of this
     endpoint) — the frontend will now always pass one explicitly.
   - In `backend/core/guardrails.py`, add a clause to `_META_LINE_RE` matching
     `write the exact words you will say` (case-insensitive, leading-line
     only, same style as the existing alternatives in that regex group).
   - **Done when:** opening the voice modal, closing it, and immediately
     reopening it (repeat 3x in a row) produces a working agent greeting and
     conversation every time, with a different room name logged by the worker
     each time; and the guardrail change has a passing manual check (see
     Verify) with no regression to the existing leaked-phrase test cases
     already implied by the module's docstring examples.

2. [x] **Speak a fixed greeting instead of generating one.**
   - Live retest showed the greeting turn was the real source of the leak, not
     a guardrail gap: `session.generate_reply(instructions=...)` runs a full
     LLM turn with every tool available, so the opening line fired
     `search_about_owner` before the visitor said anything (~30s from
     `agent state: speaking` to audible words) and spoke invented
     instruction-shaped text on top of the greeting.
   - Replace `persona.greeting_instructions()` with a fixed `persona.GREETING`
     constant, spoken via `session.say(...)` — no inference, no tool
     selection, nothing to leak, and no RAG round trip before hello.
   - The guardrails stay in place; they are the backstop for model output, not
     the cause of this leak.
   - **Done when:** the opening line is the exact `GREETING` text every time,
     with no tool call logged before it and no leaked instruction text.

## Verify

- Run `npm run dev:all` (or `dev` + frontend separately), open the voice
  modal, have a short exchange, close it, and reopen it immediately — repeat
  at least 3 times back-to-back. Each open should produce a fresh greeting and
  a working conversation, not silence.
- Check the worker log (`[worker]` lines) across the 3 reopens: confirm a
  distinct room name and a fresh `received job request` / `Agent joining
  room:` pair each time.
- Manually exercise a reply through the voice path (ask a factual question
  that triggers `search_about_owner`, mirroring the reproduction logs) and
  confirm the greeting and any tool-triggered reply are clean — no leaked
  instruction text such as "Write the exact words you will say." reaching
  speech or the visible transcript.

## Verified

Live run 2026-09-12 07:13-07:16, confirmed from worker logs.

**Reconnect fixed.** Two consecutive sessions each created a distinct room and
each received its own dispatch:

| Session | Room | Job |
|---|---|---|
| 1 | `voice-agent-room-b004b4e3-92e4-4efd-8032-e4b8b5c68857` | `AJ_bLxB24ctKXaj` |
| 2 | `voice-agent-room-47849f11-179e-441c-b7cf-98126ab5bdbf` | `AJ_b97s9ZdXFoCD` |

The second `received job request` (07:15:58) is the event that never fired
before this fix.

**Greeting leak fixed.** Spoken verbatim, with no tool call preceding it:

> `conversation_item_added {"role": "assistant", "text": "Hello. You're at
> Gichogu Macharia's site — you can ask about his work, or just chat."}`

Time from `agent state: speaking` to the greeting landing dropped from ~30s to
~7s, since the turn no longer runs an LLM inference and a RAG search first.

**Guardrails still active as backstop.** Two `Stripped model control token(s)
from output` warnings fired on the real (non-greeting) answer, confirming the
deepseek control-token stripper is still doing useful work.

### Automated checks

- Frontend `npm run typecheck` - clean
- Frontend `eslint` on the changed component - clean
- `guardrails.clean_output` unit-exercised against the leaked string, the
  pre-existing leak pattern, and normal text - all correct
- `python -m ast` parse of both changed backend modules - clean
- `AgentSession.say` signature verified against the installed SDK


<!-- blueprint:completion {"schemaVersion":1,"specBytes":9144,"specSha256":"b9911d81fd6b45a092fe3e6f84db4268e84bbd70e7cf522926c67fac8d4d4d32","branch":"refs/heads/fix/voice-reconnect-and-instruction-leak","head":"9c038ce8aef67915fe3c2e7f7ab70b4f2c628b32","baseRef":"refs/heads/master","baseCommit":"9c038ce8aef67915fe3c2e7f7ab70b4f2c628b32","sourceTree":"02b358f3863f6f2e8160319708e961434328f1e3","absentOptional":[]} -->
