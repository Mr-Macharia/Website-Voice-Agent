# Fix: Pass the voice transport as its own prop

**Type:** Fix
**Status:** verified
**Branch:** fix/voice-transport-prop
**Fixes:** F-09

## The problem

`VoiceAgentControlBar` makes one prop do two unrelated jobs.

`frontend/src/components/voice/VoiceAgentControlBar.tsx:25`

    const isLiveKit = mode.toLowerCase().includes('livekit')

`mode` is display text — it is rendered verbatim to the visitor at line 60 —
and it is simultaneously substring-tested to choose between a `Radio` icon
(LiveKit) and a `Zap` icon (AssemblyAI).

The three values passed today all resolve correctly, so **this is not a live
bug**:

| Call site | `mode` | `isLiveKit` |
|---|---|---|
| `AssemblyAIVoiceModal.tsx:371` | `VOICE_MODE_LABEL` (`"Portfolio voice agent"`) | `false` |
| `LiveKitVoiceModal.tsx:296` | `"LiveKit WebRTC"` | `true` |
| `LiveKitVoiceModal.tsx:1594` | `"LiveKit voice"` | `true` |

The risk is that the dependency is invisible from every call site. Since F-04
centralized the label, a copy edit now happens in `lib/agentIdentity.ts` — one
file removed from the substring test that silently depends on it. Renaming
`VOICE_MODE_LABEL` to anything containing "livekit", or renaming the two
LiveKit modes to drop the word, switches the icon with no type error, no
failing check, and nothing visibly broken until someone notices the wrong icon.

## The fix

Add an explicit `transport?: 'livekit' | 'assemblyai'` prop and select the icon
from it. `mode` goes back to being display text only.

The union type is the point: it makes the two supported transports explicit and
turns a future rename into a compile error instead of a silent icon swap.

**Default:** `'assemblyai'`, matching the current default `mode`
(`VOICE_MODE_LABEL`), so a call site that passes neither prop keeps today's
`Zap` icon.

**Must not break:**

- The rendered text is unchanged at every call site. `mode` still displays
  verbatim, and `isConnected ? mode : 'Connecting...'` keeps its behaviour.
- Each of the three call sites keeps the exact icon it shows today:
  AssemblyAI → `Zap`, both LiveKit sites → `Radio`.
- No change to mute, disconnect, or connection-status rendering.
- `mode` stays optional with its existing `VOICE_MODE_LABEL` default.

## Build steps

- [x] **Step 1 — Replace the substring test with a transport prop.**
      In `VoiceAgentControlBar.tsx`: add `transport?: 'livekit' | 'assemblyai'`
      to `VoiceAgentControlBarProps`, default it to `'assemblyai'` in the
      destructure, and replace the `isLiveKit` derivation with
      `transport === 'livekit'`. Keep the `mode` prop and its display use
      exactly as they are. Leave a short comment recording why the two are
      separate, so the coupling is not reintroduced.
      Then pass the prop at all three call sites:
      `AssemblyAIVoiceModal.tsx:365` → `transport="assemblyai"`;
      `LiveKitVoiceModal.tsx:290` and `:1588` → `transport="livekit"`.
      **Done when:** `grep -rn "includes('livekit')" frontend/src` returns
      nothing, all three call sites pass an explicit `transport`, and
      `npm run typecheck`, `cd frontend && npm run lint`, and
      `cd frontend && npm run build` all pass.

## Verify

Static checks first:

    npm run typecheck
    cd frontend && npm run lint
    cd frontend && npx prettier --check src/components/voice/VoiceAgentControlBar.tsx src/components/voice/AssemblyAIVoiceModal.tsx src/components/voice/LiveKitVoiceModal.tsx
    cd frontend && npm run build

Then in the browser, with `npm run dev:all` running:

1. Open the voice modal (default AssemblyAI path). The control bar reads
   `Portfolio voice agent` beside the orange `Zap` icon — unchanged from today.
2. Confirm the agent name and the `Connecting...` → connected text transition
   still behave as before.

The LiveKit modal is only reachable with `NEXT_PUBLIC_VOICE_PROVIDER=livekit`.
Exercising it is optional; if it is not run, say so rather than implying it was
verified. Its two call sites are covered by typecheck and by the `grep` in
Step 1.

## Findings

### voice-transport-prop/F-09 [P3] closed - The voice control bar derives behavior from a display string

**File:** frontend/src/components/voice/VoiceAgentControlBar.tsx:26
**Found:** 2026-09-20 by /audit (scope: current; lens: quality)
**Why it matters:** `const isLiveKit = mode.toLowerCase().includes('livekit')`
makes one prop do two jobs: `mode` is rendered verbatim to the visitor at line
60, and it is simultaneously parsed to choose which icon to show. The three
values passed today (`VOICE_MODE_LABEL`, `"LiveKit WebRTC"`, `"LiveKit voice"`)
all resolve correctly, so this is not a live bug. But the coupling is invisible
from the call sites: centralizing the label in `VOICE_MODE_LABEL` (this fix)
means a future copy edit happens in `lib/agentIdentity.ts`, one file removed
from the substring test that depends on it. Renaming the label to something
containing "livekit", or renaming the LiveKit modes to drop it, silently
switches the icon with no type error and nothing failing.
**Suggested fix:** Pass the transport as its own prop — for example
`transport?: 'livekit' | 'assemblyai'` — and keep `mode` purely for display.
Small and local: three call sites and one component. Not urgent, and out of
scope for the F-04 fix, which only moved literals.
**Resolution:** Fixed on `fix/voice-transport-prop`. `VoiceAgentControlBar`
now takes `transport?: 'livekit' | 'assemblyai'` and derives the icon from it
(`isLiveKit = transport === 'livekit'`); `mode` went back to display-only, with
a docblock on the prop recording that the icon must never be inferred from it
again. All three call sites pass an explicit transport:
`AssemblyAIVoiceModal.tsx:372` assemblyai, `LiveKitVoiceModal.tsx:297` and
`:1596` livekit -- preserving the exact icon each showed before. The default is
`'assemblyai'`, matching the existing default `mode`, so a caller passing
neither is unchanged. `grep -rn "includes('livekit')" frontend/src` now returns
nothing. typecheck, lint, prettier and build all pass.

Closed by /audit 2026-09-22 (scope: current; all four lenses). Re-reviewed the
repaired code rather than the repair note. Confirmed all three real call sites
pass an explicit `transport` (a fourth grep hit is the component's own
declaration), that no `toLowerCase().includes` or other `mode`-string parsing
survives anywhere in `frontend/src`, and that `mode` is now read only for
display. Compiled a throwaway probe passing `transport="LiveKit WebRTC"`: it
fails with TS2322, so the union rejects a display string at build time, which
is the guarantee the finding asked for. The probe was deleted. Security: the
prop is a compile-time literal, never user input. Performance: a per-render
`toLowerCase().includes()` became a strict equality. `npm run typecheck`
exits 0.
