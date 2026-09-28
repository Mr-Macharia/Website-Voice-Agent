# Findings

> **Generated file.** The findings ledger: review findings raised by `/audit`
> against the work in progress, each with a durable ID, severity (P0-P3), and
> status. `/implement` marks repaired findings `fixed`, a later `/audit` pass
> moves them to `closed`, and `/complete` refuses to merge while any P0 or P1
> finding is `open` or `fixed`, then archives resolved findings with the work
> and resets this file.

### F-09 [P3] unverified - LiveKitVoiceModal inlines a Next.js API route fetch, not through src/api

**File:** frontend/src/components/voice/LiveKitVoiceModal.tsx:1641
**Found:** 2026-09-28 by /audit (scope: current; lens: quality)
**Why it matters:** Encountered while auditing F-06's fix, outside its scope.
`fetch(`/api/livekit/token?room=${roomName}`)`, with a fallback to
`${selectedEndpoint}/api/livekit/token`, is not the AgentOS backend pattern
`coding-standards.md`'s `src/api/` rule targets (that rule is about calls to
the Python backend; this primary call is to a same-server Next.js route).
Unverified rather than open: it is inside the LiveKit fallback path, which is
out of scope for both F-06 and this pass, and it is not certain the standard
was intended to cover Next.js API routes as well as the Python backend.
**Suggested fix:** If `src/api/` is meant to cover this class of call too,
extend `APIRoutes` or add a sibling convention for local routes; otherwise
mark it explicitly out of scope in `coding-standards.md`.
**Resolution:**
