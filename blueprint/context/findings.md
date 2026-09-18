# Findings

> **Generated file.** The findings ledger: review findings raised by `/audit`
> against the work in progress, each with a durable ID, severity (P0-P3), and
> status. `/implement` marks repaired findings `fixed`, a later `/audit` pass
> moves them to `closed`, and `/complete` refuses to merge while any P0 or P1
> finding is `open` or `fixed`, then archives resolved findings with the work
> and resets this file.

### F-01 [P1] fixed - Three agent-name fallbacks still say "Realtime Voice Assistant"

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
**Resolution:** Fixed 2026-09-18 by /audit repair. Fallback set to `'Clyde'` in ChatArea.tsx:23, ChatInput.tsx:24 and Sidebar.tsx:262. A repo-wide grep for "Realtime Voice Assistant" now returns nothing across backend/ and frontend/src/.

### F-02 [P2] fixed - The second registered agent is still named "Realtime Voice Assistant"

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
**Resolution:** Fixed 2026-09-18 by /audit repair. voice_agent renamed to "Clyde" (server.py:101) with a comment recording why both agents share one name. The same agent in the MCP server (voice_mcp/voice_agent_server.py:113) was renamed too — it was outside the original finding and would otherwise have kept the old name.

### F-03 [P2] fixed - LiveKit fallback path was not rebranded

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
**Resolution:** Fixed 2026-09-18 by /audit repair. LiveKitVoiceModal.tsx: agent-name fallback, sr-only DialogTitle, header label, badge, three status messages, connect toast and visualizer label rebranded. `mode=` deliberately kept LiveKit-identifying ("LiveKit voice") because VoiceAgentControlBar derives `isLiveKit` from it. The sr-only DialogTitle in the *active* AssemblyAIVoiceModal.tsx:179 was also stale and fixed.

### F-04 [P3] open - "Portfolio voice agent" is duplicated as a literal in three places

**File:** frontend/src/components/voice/AssemblyAIVoiceModal.tsx:204
**Found:** 2026-09-18 by /audit (scope: changed; lens: quality)
**Why it matters:** The same display string is hardcoded at
`AssemblyAIVoiceModal.tsx:204`, `AssemblyAIVoiceModal.tsx:287`, and as the
default at `VoiceAgentControlBar.tsx:22`. The next copy edit has to find all
three, and missing one splits the label between the modal header and the
control bar. Minor, but the identical `agentName = 'Clyde'` default is now
duplicated across two components for the same reason.
**Suggested fix:** Lift both strings into a shared constant near the voice
components and import it. Not urgent.
**Resolution:**
