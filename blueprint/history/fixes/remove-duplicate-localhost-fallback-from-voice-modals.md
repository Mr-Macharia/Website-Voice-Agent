# Fix: Remove duplicate localhost fallback from voice modals

**Type:** Fix
**Status:** verified
**Branch:** fix/remove-duplicate-localhost-fallback-from-voice-modals
**Fixes:** F-11

## The problem

Two voice call sites still append their own `|| 'http://localhost:7777'`
fallback to `selectedEndpoint`:

- `frontend/src/components/voice/AssemblyAIVoiceModal.tsx:137` (primary voice path)
- `frontend/src/components/voice/LiveKitVoiceModal.tsx:732` (legacy fallback path)

F-06 removed the same pattern from `Messages.tsx`. The store
(`frontend/src/store.ts:15`) already guarantees `selectedEndpoint` is a
non-empty string, initialized from `NEXT_PUBLIC_AGENT_OS_URL`, with localhost
only as the build-time fallback, and it is deliberately not persisted to
`localStorage`. The duplicate fallbacks are dead today, and if that contract
ever changes they would quietly bring back the stale-localhost bug.

## The fix

Read `selectedEndpoint` directly at both call sites, matching `Messages.tsx`.
Keep everything else as it is:

- LiveKit: keep the `.replace(/\/+$/, '')` trailing-slash trim and the
  `http` → `ws` conversion.
- AssemblyAI: keep how `endpoint` is passed into `AssemblyAISession`.

No behavior change is expected. The only localhost fallback left is in
`store.ts`.

## Build steps

- [x] **1. Remove both fallbacks.** Edit the two lines above so `endpoint`
  derives from `selectedEndpoint` only.
  **Done when:** `grep -rn "localhost:7777" frontend/src` matches only
  `store.ts`, and `npm run typecheck` and `cd frontend && npm run lint` pass.

## Verify

- `npm run typecheck`, `cd frontend && npm run lint`, and
  `npx prettier --check` on the two touched files.
- Manual: `npm run dev:all`, open the voice modal (AssemblyAI default), and
  confirm the session connects and the agent responds.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":1814,"specSha256":"fcc6b2b115664d308e038e9c97feab1c8575eb5152a0cd50abac0bffe25285a7","branch":"refs/heads/fix/remove-duplicate-localhost-fallback-from-voice-modals","head":"3530c19667ceb62cffbbefb058ff28851572d5d2","baseRef":"refs/heads/master","baseCommit":"3530c19667ceb62cffbbefb058ff28851572d5d2","sourceTree":"062f2a5b7c01cb5bf21f1a312410e7c03f4cc01e","absentOptional":[]} -->
