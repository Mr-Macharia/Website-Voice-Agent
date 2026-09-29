# Fix: Route LiveKit token minting through the rate-limited backend

**Type:** Fix
**Status:** verified
**Branch:** fix/route-livekit-token-minting-through-the-rate-limited-backend
**Fixes:** F-14

## The problem

There are two routes that mint LiveKit tokens, and the modal prefers the
unprotected one.

| Route | Rate-limited | Agent dispatch | Used by the modal |
|---|---|---|---|
| Next.js `frontend/src/app/api/livekit/token/route.ts` | No | Yes | First |
| Python `backend/server.py:570` | Yes (`scope="livekit_token"`, 30 per 300 s, from F-10) | No | Only if the first fails |

The Next route runs as a Vercel serverless function. Those instances share no
memory, so the Python limiter can never cover it. Each token it signs is valid
for 1 hour, grants join/publish, and dispatches the agent into a room the
client names.

The Next route is first only because it adds the agent dispatch. The worker
registers as an explicit-dispatch agent
(`livekit_worker.py:309`, `agent_name="voice-agent"`), so a token without the
dispatch gets a room with no agent in it.

**Exposure:** only when `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and a LiveKit URL
are set on Vercel. AssemblyAI is the default voice path.

## The fix

Make the Python endpoint the only token route:

1. Give the Python token the same agent dispatch. The installed `livekit-api`
   supports this directly: `AccessToken.with_room_config` with
   `api.RoomConfiguration` and `api.RoomAgentDispatch` are all present
   (confirmed against the backend venv).
2. Point the modal at the backend only.
3. Delete the Next route, so no unthrottled minting path is left on Vercel.

The agent name is currently the literal `"voice-agent"` in the worker and in
the Next route's `LIVEKIT_AGENT_NAME || 'voice-agent'` fallback. That env var
is not set anywhere. Replace both with one constant `LIVEKIT_AGENT_NAME` in
`backend/core/config.py`, used by the worker's `rtc_session` decorator and the
token endpoint. That way the dispatch name and the worker's registration
cannot drift apart. It is a code constant, not an env var: nothing configures
it today.

**Must not break:**
- The unique room per session (`voice-agent-room-<uuid>`), which dispatch
  depends on.
- The modal's `isConfigured` check on the token response. Keep the response
  shape `{token, url, room, identity, name}` unchanged.
- The AssemblyAI voice path, which this fix does not touch.

**Behavior change to know about:** the modal has no special handling for 429.
Any non-OK token response, a throttled one included, drops the visitor
silently to the legacy WebSocket bridge (`LiveKitVoiceModal.tsx:1673`).
Today a throttled Python call is never reached, because the unthrottled Next
route answers first. After this fix, a visitor over the limit gets the bridge
instead of LiveKit. That is acceptable for this fix; surfacing a
"too many sessions" message is a separate change.

**Out of scope:**
- The client choosing its own `room` and `identity`. The rate limit already
  bounds how many tokens get minted.
- Rate-limiting the legacy `/ws/voice` bridge.
- Any 429 UI in the modal.

## Build steps

- [x] **1. Dispatch the agent from the Python token.** Add
  `LIVEKIT_AGENT_NAME = "voice-agent"` to `core/config.py`. Use it in
  `livekit_worker.py`'s `@server.rtc_session(agent_name=...)`, and in
  `generate_livekit_token` via
  `.with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=LIVEKIT_AGENT_NAME)]))`.
  **Done when:** decoding a token minted by the endpoint (a short local script,
  no dev server) shows a `roomConfig` whose `agents` contains `voice-agent`, and
  the rate limit and 429 response are unchanged.

- [x] **2. Use the backend only and delete the Next route.** In
  `LiveKitVoiceModal.tsx`, replace the two-fetch fallback with a single
  `fetch(\`${selectedEndpoint}/api/livekit/token?room=${roomName}\`)`. Delete
  `frontend/src/app/api/livekit/token/`. In `docs/deployment.md` (lines 40 and
  50), say the `LIVEKIT_*` variables belong on the backend (Heroku) only, and
  not on Vercel.
  **Done when:** `grep -rn "api/livekit/token" frontend/src` finds only the
  backend-URL call; `npm run typecheck`, `cd frontend && npm run lint`, and
  `cd frontend && npm run build` pass; and the build's route list no longer
  includes `/api/livekit/token`.

## Verify

- **Dispatch works:** set `NEXT_PUBLIC_VOICE_PROVIDER=livekit`, run backend,
  worker and frontend, open the voice modal, and confirm the agent joins and
  speaks. The worker log shows it received the job.
- **Throttle holds:** the 31st request to `/api/livekit/token` within 300 s
  returns 429 with `Retry-After`.
- **Default path unaffected:** with the provider unset, AssemblyAI voice
  connects and replies.

## Deployment note

After merge, remove `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and `LIVEKIT_URL`
from Vercel if they are set there. The frontend no longer reads them.
`NEXT_PUBLIC_LIVEKIT_URL` is also unused by the frontend once the route is
gone; confirm with a grep during step 2 before recommending its removal.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":5067,"specSha256":"8f158d4dd978561fc97cf21bfab751823856e66a5b44210b0a25d991d0745592","branch":"refs/heads/fix/route-livekit-token-minting-through-the-rate-limited-backend","head":"c9fa69b4aec1e88148433c7ee4caa328e19deffa","baseRef":"refs/heads/master","baseCommit":"ba522a6ad29341bdcee5b637ed962ea1d29d7a66","sourceTree":"30253fd215dea80ad324d45634bf5dea6ba15de0","absentOptional":[]} -->

## Findings

### route-livekit-token-minting-through-the-rate-limited-backend/F-14 [P2] closed - The Next.js LiveKit token route mints unthrottled tokens on Vercel

**File:** frontend/src/app/api/livekit/token/route.ts
**Found:** 2026-09-29 by /fix F-10 (scope: frontend/src/app/api/livekit; lens: security)
**Why it matters:** `LiveKitVoiceModal.tsx:1641` calls this same-origin route
*first* and only falls back to the Python `/api/livekit/token` when it
fails, so this is the primary LiveKit token path. It signs a 1-hour token
with room-join/publish grants and embeds an agent dispatch, and accepts a
client-chosen `identity` and `room`. It has no rate limit, and Vercel's
serverless functions share no memory, so the in-process Python limiter
cannot cover it. Exposure is conditional: the route returns 500 unless
`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` and a LiveKit URL are set on Vercel,
and the default voice path is AssemblyAI.
**Suggested fix:** Either keep LiveKit credentials off Vercel unless the
fallback is actively in use (and say so in `docs/deployment.md`), or route
the fallback's token minting through the rate-limited Python endpoint once
it can embed the same agent dispatch.
**Resolution:** Verified by independent review (fresh subagent, claude-opus-5-5) at c9fa69b.
The Next route is deleted, the modal fetches only `${selectedEndpoint}/api/livekit/token`
(rate-limited, scope `livekit_token`), and a locally minted token decodes with
`roomConfig.agents=[{agentName: 'voice-agent'}]` from the shared `LIVEKIT_AGENT_NAME`.

## Independent review

**Status:** passed
**Target commit:** c9fa69b4aec1e88148433c7ee4caa328e19deffa
**Base commit:** ba522a6ad29341bdcee5b637ed962ea1d29d7a66
**Base ref:** master
**Spec hash:** 8f158d4dd978561fc97cf21bfab751823856e66a5b44210b0a25d991d0745592
**Prepared by:** claude
**Builder model:** claude-opus-5-5
**Requested reviewer:** claude
**Requested model:** claude-opus-5-5
**Requested execution:** automatic
**Requested at:** 2026-09-29T21:39:39Z
**Workflow:** regular
**Check required:** no
**Reviewer adapter:** claude
**Reviewer model:** claude-opus-5-5
**Reviewer context:** fresh subagent
**Actual execution:** automatic
**Reviewed at:** 2026-09-29T21:40:37Z
**Scope:** current
**Lenses:** quality, security, performance, tests
**Verdict:** passed
**Check result:** not-required

## Commands

- `npm run typecheck`: pass
- `cd frontend && npm run lint`: pass
- `cd backend && uv run python -c <mint token with RoomAgentDispatch and decode>`: pass (roomConfig.agents=[{agentName: 'voice-agent'}])
- `cd backend && uv run python -c <ast.parse server.py, livekit_worker.py>`: pass
- Automated tests: unavailable (no test runner configured)

## Evidence

- HEAD = target c9fa69b; merge-base(master, HEAD) = ba522a6; spec SHA-256 matches; only review.md dirty.
- Delta: route.ts deleted; modal fetches backend only; server.py adds dispatch after unchanged rate-limit/429 block; worker and token share core_config.LIVEKIT_AGENT_NAME; response shape unchanged.
- No remaining `/api/livekit/token` references to the Next route in frontend/src.

## Findings

- F-14 closed (verified)
- F-15 [P3] open: unused `livekit-server-sdk` frontend dependency

## Remaining risk

- No automated test runner; the endpoint's rate limit and dispatch are not covered by tests.
- Frontend build not run; live LiveKit dispatch not exercised end to end (Check not required).
- Throttled visitors silently fall back to the legacy WebSocket bridge (accepted in spec).
- Pre-existing: client-chosen room/identity and blanket 500 detail leaking exception text (out of scope).
