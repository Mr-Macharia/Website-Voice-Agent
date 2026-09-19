# Fix: Centralize the agent name and voice-mode label

**Type:** Fix
**Status:** verified
**Branch:** fix/centralize-agent-name-literals
**Fixes:** F-04

## The problem

Two display strings are hardcoded across the frontend, so a copy edit has to
find every site and missing one splits the label between components.

`"Portfolio voice agent"` — **four** sites (the finding said three; it predates
the Clyde rebrand and missed the LiveKit one):

| File | Line | Context |
|---|---|---|
| `voice/AssemblyAIVoiceModal.tsx` | 277 | Rendered in the modal header |
| `voice/AssemblyAIVoiceModal.tsx` | 370 | Passed as `mode` to the control bar |
| `voice/VoiceAgentControlBar.tsx` | 22 | Default `mode` prop |
| `voice/LiveKitVoiceModal.tsx` | 1326 | Rendered in the legacy modal header |

`'Clyde'` — **six** sites, as the fallback when no agent name is available:

| File | Line |
|---|---|
| `chat/ChatArea/ChatArea.tsx` | 24 |
| `chat/ChatArea/ChatInput/ChatInput.tsx` | 24 |
| `chat/Sidebar/Sidebar.tsx` | 80 |
| `voice/AssemblyAIVoiceModal.tsx` | 59 |
| `voice/VoiceAgentControlBar.tsx` | 21 |
| `voice/LiveKitVoiceModal.tsx` | 1598 |

The agent is named in `backend/core/persona.py`, so the frontend fallback is a
mirror of a backend value that cannot be imported across the service boundary.
Centralizing does not make it authoritative, but it does make the mirror single.

`LiveKitVoiceModal.tsx` is legacy but still reachable: `VoiceModal.tsx:25`
selects it when `NEXT_PUBLIC_VOICE_PROVIDER=livekit`. It is in scope — leaving
one file behind is the exact failure mode this fix exists to prevent.

## The fix

Add one module holding both constants and import it at all ten sites. There is
no existing constants file under `frontend/src/components/voice/`, and the
strings are used from `chat/` as well as `voice/`, so the module belongs in
`frontend/src/lib/` alongside the other shared modules (`toolPayload.ts`,
`calEmbed.ts`, `modelProvider.ts`), not inside either component folder.

Use `SCREAMING_SNAKE_CASE`, per `coding-standards.md` for module-level constants.

**Must not break:**

- Rendered text is byte-identical in every one of the ten places. This is a
  refactor: nothing a visitor sees may change.
- The fallback semantics at each `'Clyde'` site. Each is the right-hand side of
  a `||` after a lookup that can legitimately return a name; keep the lookup and
  replace only the literal.
- The `mode` prop on `VoiceAgentControlBar` stays optional with the same
  default.
- Prop names, component signatures and the LiveKit path all stay as they are.

**Out of scope:** renaming the agent, changing either string's wording, removing
the LiveKit modal, and reconciling the frontend fallback with
`backend/core/persona.py`. Each is a product decision, not a refactor.

## Build steps

- [x] **Step 1 — Add the constants and replace all ten literals.**
      Create `frontend/src/lib/agentIdentity.ts` exporting
      `DEFAULT_AGENT_NAME` (`'Clyde'`) and `VOICE_MODE_LABEL`
      (`'Portfolio voice agent'`), each with a short comment saying the agent's
      real name comes from `backend/core/persona.py` and this is the fallback
      used when the backend has not answered yet.
      Replace all four `"Portfolio voice agent"` and all six `'Clyde'` literals
      with imports. Grep afterwards to confirm no literal survives outside the
      new module.
      **Done when:** `grep -rn "Portfolio voice agent\|'Clyde'" frontend/src`
      returns only `lib/agentIdentity.ts`; `npm run typecheck`,
      `cd frontend && npm run lint` and `cd frontend && npm run build` all pass.

## Verify

Static checks carry most of this fix — it is a literal-for-constant swap with no
behavior change. Confirm in the browser that the visible text is unchanged:

1. **Chat header.** Load the app with the backend running. The agent name
   beside the chat reads exactly as before (the live agent name, or `Clyde`
   before the backend answers).
2. **Voice modal.** Open the Live Voice Agent. The header still reads
   `Portfolio voice agent`, and the control bar shows the same agent name as
   the chat.
3. **Backend down.** Stop the backend and reload. The fallback `Clyde` appears
   where a live name would be, exactly as before this change.

The LiveKit path (`NEXT_PUBLIC_VOICE_PROVIDER=livekit`) is edited but not
exercised; the build and typecheck are its coverage, and the change there is the
same mechanical swap.

`npm run validate` is broken independently of this work (it shells out to
`pnpm`, which is not installed). Run the checks individually via `npm`.
Prettier resolves its Tailwind plugin only when run from `frontend/`.

## Findings

### centralize-agent-name-literals/F-04 [P3] closed - "Portfolio voice agent" is duplicated as a literal in three places

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
**Resolution:** Fixed on `fix/centralize-agent-name-literals`. Added
`frontend/src/lib/agentIdentity.ts` exporting `DEFAULT_AGENT_NAME` and
`VOICE_MODE_LABEL`, and replaced every literal with an import. The count was
larger than this entry recorded: four `"Portfolio voice agent"` sites (the
entry missed `LiveKitVoiceModal.tsx`, whose line numbers had drifted since the
Clyde rebrand) and six `'Clyde'` sites spanning chat as well as voice. A grep
now finds both strings only in the new module, and both constant values are
byte-identical to the literals they replaced.

Closed by /audit 2026-09-20 (scope: current; all four lenses). Re-reviewed the
repaired code: `grep` for either string across `frontend/src` returns only
`lib/agentIdentity.ts`; both constant values verified byte-identical to the
originals; every `?.name ||` lookup and the `teamId` ternary are intact at all
ten call sites; `npm run typecheck` exits 0. The docblock's claim that the name
originates in `backend/core/persona.py` was verified against that file. No new
defect was introduced in the repaired files.
