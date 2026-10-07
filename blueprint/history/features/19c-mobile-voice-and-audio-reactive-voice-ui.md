# Feature: Mobile voice and audio-reactive voice UI

**From build-plan:** feature 19c
**Build attempt:** 1
**Branch:** feature/mobile-voice-and-audio-reactive-voice-ui
**Type:** Feature
**Status:** verified

## Goal

Make the AssemblyAI voice session work reliably on phone browsers (iOS Safari
16.4+, Android Chrome) and replace the current bar visualizer with a premium,
audio-reactive aura ring and liquid controls, without regressing desktop voice.

## Design reference

Approved mockups in [prototypes/](../../prototypes/):

- **Visual + controls (authoritative):** [voice-aura.html](../../prototypes/voice-aura.html)
  - aurora ring shader, per-state colours and motion, frosted glass dock with
    goo-filter liquid controls (squish on press, seeping droplet while
    listening, red-swelling mic blob when muted), beam + grain scene.
- **States, copy and layouts:** [voice-phone-states.html](../../prototypes/voice-phone-states.html)
  (tap to start, connecting, listening, thinking, speaking, muted, dropped after
  screen lock, mic blocked on iPhone Safari and Android Chrome, landscape) and
  [voice-desktop.html](../../prototypes/voice-desktop.html) (lg+ modal, aura left,
  transcript right, `M` / `Esc` hints). These still draw the old orb; the aura
  replaces it everywhere.
- **Tokens:** [theme.css](../../prototypes/theme.css) `:root` block.

The aura shader is our own code using the published technique (a ring traced
through layered turbulence, accumulated with bloom and tone-mapped). Do not copy
LiveKit's `AgentAudioVisualizerAura` source: its header licenses it under
Polyform Non-Resale 1.0.0, not Apache-2.0.

## In scope

1. **Tokens.** Port the voice-state colours and control size from
   `prototypes/theme.css` into `frontend/src/app/globals.css` `@theme`:
   listening `#38bdf8`, thinking `#a78bfa`, speaking `#f48c06`, muted
   `#64748b`, error `#f43f5e`, faint text `#8391a7`, voice control 56px.
2. **Aura visualizer** (`VoiceAura`), a WebGL fragment shader on a `<canvas>`:
   - inputs: `state` and a level getter returning 0–1; colour/speed/size/
     turbulence/pulse eased per state as in `voice-aura.html`;
   - speaking swells with the reply level, listening with the mic level;
   - the render loop writes uniforms directly (no React state per frame), caps
     device pixel ratio at 2, pauses while `document.hidden`, and releases the
     GL context on unmount;
   - `prefers-reduced-motion: reduce` → one still frame per state change;
   - no WebGL → a static CSS radial ring in the state colour;
   - decorative: `aria-hidden`; state is conveyed by the status text.
3. **Gesture-safe start (iOS).** The sheet opens on a **Start talking** screen.
   The button's click handler creates and `resume()`s the `AudioContext`
   synchronously, before any `await` (token fetch, worklet load,
   `getUserMedia`), then runs the rest of `start()`. Applies at every width.
4. **Drop detection and recovery.** When the page becomes visible again, or the
   socket closes unexpectedly, or the mic track fires `ended`:
   - if the WebSocket is not `OPEN`, or the mic track is `ended` → enter a
     **dropped** state: "The call dropped" + Reconnect (starts a fresh session
     from the same tap path) + Back to chat (closes the sheet);
   - if only the `AudioContext` is suspended → resume it silently (existing
     behaviour).
   Turns already mirrored to the chat stay there; no session resume (AssemblyAI
   resume window) is attempted.
5. **Error states with a way out**, replacing toast-only errors:
   - **mic blocked** (`NotAllowedError` / `PermissionDeniedError` /
     `SecurityError`): browser-specific instructions (iOS Safari: aA → Website
     Settings → Microphone: Allow; Chrome/Android: site-settings icon left of
     the address → Permissions → Microphone: Allow; other browsers: generic
     "allow microphone access in your browser settings"), Try again + Type
     instead;
   - **no mic / other / service errors**: the existing session messages, Try
     again + Back to chat.
6. **Layout.**
   - Below `lg`: full-screen sheet (`h-dvh`, notch/home-bar safe-area padding),
     status chip top, aura centred and sized `min(two-thirds of width, ~40% of
     height)`, status label + live line under it, liquid dock at the bottom.
     Short/landscape screens (height < 500px): aura left, transcript right.
   - `lg`+: centred modal as `voice-desktop.html` (aura left, transcript right).
   - Transcript: last turns, `aria-live="off"`; only the status text is a
     `role="status"` live region (state changes and Clyde's finished replies).
     Fade the transcript top with a gradient overlay, not `mask-image`.
   - The booking card keeps today's behaviour (Cal.com `BookingCard` inline in
     the transcript, mirrored to chat).
7. **Controls (liquid dock).**
   - Mic toggle: labelled "Mic on / Mic off", `aria-pressed`, `M` shortcut on
     devices with a keyboard (ignored while focus is in a text field).
   - **End**: ends immediately, no confirmation; `Esc` also ends.
   - **Type instead**: ends the session, closes the sheet, focuses the chat
     input via the store's `chatInputRef`.
   - ✕ close shows only on the start, dropped and error screens; during a
     session End is the only exit.
   - All targets ≥ 44px (dock buttons 56px), visible focus rings, press
     feedback with no layout shift, goo filter purely decorative behind crisp
     real buttons.
8. **Remove the old bars UI** from the AssemblyAI path: `AssemblyAIVoiceModal`
   stops using `VoiceVisualizer` and `VoiceAgentControlBar` and the raw
   `State: speaking` chip. Both files stay because `LiveKitVoiceModal` still
   imports them.

9. **Chat polish borrowed from assistant-ui (Part B, added at the user's
   request).** Patterns only, rebuilt on the existing components: no
   `@assistant-ui/react` dependency, no runtime swap, no backend change.
   assistant-ui is MIT; any adapted snippet keeps a source comment.
   - **Sticky auto-scroll:** the thread follows new tokens only while the
     visitor is at the bottom; scrolling up stops following.
   - **Jump-to-latest** button (44px, labelled) when scrolled up; click
     smooth-scrolls to the end and resumes following.
   - **Composer:** Stop button replaces Send while a reply streams (cancels
     the existing stream); Send disabled when empty; Enter / Shift+Enter kept.
   - **Message action bar** on agent replies: Copy (with "Copied" feedback);
     visible on hover with a pointer, always visible on touch.
   - **Message layout:** consistent role alignment, max width, spacing and
     streaming caret, following assistant-ui's thread proportions.
   - The same sticky-scroll behaviour is used by the voice transcript.

## Out of scope

- The dormant LiveKit modal and worker (no changes).
- Backend, token endpoint, AssemblyAI session config, persona.
- AssemblyAI session resume after a drop (we start a new session).
- Booking slide-up panel from `voice-phone-booking.html` (Cal.com card stays
  inline).
- The "agent loses context between turns" bug (separate `/fix`).
- New dependencies: no `@assistant-ui/react`, Three.js, OGL, Rive or LiveKit
  Agents UI packages.
- assistant-ui's runtime, `init`, thread list, branching and attachments.

## Build loop

`workflow.stepReview: "feature"`, `checkpointCommits: "disabled"`: build all
steps, run the checks after each, then one review packet at the end. No
checkpoint commits; `/complete` makes the single feature commit.

## Build steps

- [x] **1. Tokens + `VoiceAura` component.** Port the tokens. Add
  `frontend/src/components/voice/VoiceAura.tsx` (shader, state easing, level
  getter prop, reduced-motion and no-WebGL fallbacks, hidden-tab pause).
  Not wired into the modal yet.
  **Done when:** typecheck, lint and prettier pass; a temporary dev render (or
  the modal in step 3) shows the ring in each state colour; no console errors.
- [x] **2. Session: gesture-safe start, levels, drop detection, typed errors.**
  In `frontend/src/lib/voice/AssemblyAISession.ts`:
  - `start()` creates and resumes the `AudioContext` before its first `await`;
  - add `getMicLevel()` / `getReplyLevel()` (0–1 RMS from the existing
    analysers; 0 when absent);
  - add a `dropped` state: on visibility return, unexpected socket close after
    ready, or mic track `ended` → cleanup and report `dropped` (not `error`);
  - report errors with a kind: `'mic-blocked' | 'no-mic' | 'other'` plus the
    existing message, instead of the caller inferring from text.
  **Done when:** typecheck passes; the existing desktop voice flow still
  connects, speaks and ends (manual check against the running app).
- [x] **3. Modal redesign.** Rebuild `AssemblyAIVoiceModal.tsx`: start screen,
  connecting, listening/thinking/speaking/muted, dropped, mic-blocked and
  error screens; sheet below `lg`, modal at `lg`+, landscape split; liquid
  dock (new `VoiceDock.tsx` in `components/voice/`), keyboard shortcuts, close
  rules, Type instead focus, live-region rules, transcript fade.
  **Done when:** at 390px and 1440px every state renders as the mockups
  (states forced via the session callbacks where a real one can't be
  triggered); no horizontal scroll at 360px; all controls ≥ 44px; focus is
  trapped in the dialog and returns to the opener on close.
- [x] **4. Verify.** Typecheck, lint, prettier, production build. Browser
  evidence at 360/390/768/1024/1440px. Real voice session on desktop: connect,
  talk, mute/unmute, interrupt, End, Type instead. Real phone (by the user):
  iPhone Safari start + reply audio + lock/unlock → dropped → Reconnect;
  Android Chrome the same; mic denied → mic-blocked screen.
  **Done when:** all automated checks pass, screenshots attached, and the
  phone results are recorded as observed by the user (or listed as not
  observed).

- [x] **5. Sticky scroll + jump-to-latest.** Add a
  `useStickToBottom` hook in `frontend/src/hooks/` (follow while at bottom,
  release on user scroll up, resume on jump). Use it in `Messages.tsx` and the
  voice transcript; add the Jump-to-latest button.
  **Done when:** while a long reply streams, scrolling up stops following and
  shows the button; clicking it returns to the end and follows again.
- [x] **6. Composer Stop + message actions + layout.** Stop button while
  streaming (wired to the existing stream's cancel; add one if missing), empty
  Send disabled, Copy action on agent replies, layout/spacing pass.
  **Done when:** Stop ends a streaming reply and the input is usable
  immediately; Copy puts the reply text on the clipboard and shows "Copied";
  checks at 390 and 1440px.
- [x] **7. Final verification** for both parts (replaces step 4's gate):
  typecheck, lint, prettier, production build, browser evidence, real voice
  and text sessions.

## Files / areas

- `frontend/src/app/globals.css` (tokens)
- `frontend/src/components/voice/VoiceAura.tsx` (new)
- `frontend/src/components/voice/VoiceDock.tsx` (new)
- `frontend/src/components/voice/AssemblyAIVoiceModal.tsx` (rewrite of the view)
- `frontend/src/lib/voice/AssemblyAISession.ts` (start order, levels, dropped, error kinds)
- Read-only callers: `ChatArea.tsx`, `Sidebar.tsx`, `ChatInput.tsx` (open the
  modal via `VoiceModal`; props unchanged), `store.ts` (`chatInputRef`).
- Part B: `frontend/src/hooks/useStickToBottom.ts` (new),
  `components/chat/ChatArea/Messages/Messages.tsx`, `MessageItem.tsx`,
  `ChatInput/ChatInput.tsx`, `hooks/useAIStreamHandler.tsx` (cancel only if missing).
- `prototypes/` is deleted at `/complete` after the tokens are ported.

## Data / contracts

- `VoiceSessionState` gains `'dropped'`. Full set: `idle | connecting |
  listening | thinking | speaking | dropped | error`. Muted stays a separate
  boolean (`isMuted`), not a session state.
- `onStateChange(state, message?, kind?)` where `kind` is
  `'mic-blocked' | 'no-mic' | 'other'` and is present only with `'error'`.
- `getMicLevel(): number`, `getReplyLevel(): number`, both clamped 0–1, safe to
  call in any state.
- `VoiceAura` props: `state: 'idle' | 'connecting' | 'listening' | 'thinking' |
  'speaking' | 'muted' | 'dropped' | 'error'`, `getLevel: () => number`,
  `className?`. Muted, dropped and error render grey/rose and still.
- `VoiceModal` props (`isOpen`, `onClose`, `agentName`) are unchanged.
- No stored data, API or URL changes. Transcript text is rendered as React text
  nodes (no HTML injection).

## Testing

No unit or browser test runner is configured (`AGENTS.md`), so:

- `npm run typecheck`, `cd frontend && npm run lint`, `npm run format`, and
  `npm run build` (on a scratchpad copy if the dev server is running).
- Browser evidence via Claude in Chrome at the listed widths, with console
  checked.
- Real-device checks are done by the user and recorded as observed or not.

## Notes for the AI

- Keep per-frame work out of React: the aura's rAF loop reads `getLevel()` and
  writes uniforms; React only changes `state`.
- One WebGL context per open sheet; dispose on close. Don't create the canvas
  while the sheet is closed.
- iOS: nothing between the click and `new AudioContext()` / `resume()` may be
  async. Keep the existing worklet and echo-cancellation settings.
- Shader cost: cap DPR at 2 and keep the iteration count modest (≈ 32–36); if a
  phone stutters, lower iterations before anything else.
- Don't reintroduce the framer-motion `layout` bars or random-number motion.
- Follow `voice-aura.html` for feel; colours come from the ported tokens.

## Open questions

None. Decisions taken (reversible, recorded here):

- The Start talking screen appears at every width, because iOS needs the audio
  started inside a tap and one flow is simpler than two.
- Booking stays inline (Cal.com) rather than the slide-up panel mockup.

## Verification record

- Automated: production build, typecheck, Prettier pass; ESLint 0 errors, 1 warning.
- Desktop, observed by the user on localhost:3000: aura colours per state,
  live caption + history, voice-reactive motion (listening and speaking),
  booking calendar inline, Stop/Copy in text chat.
- Phone, observed by the user: voice sheet and dock (stray droplet removed).
- Not observed: phone lock/unlock → dropped → Reconnect; mic denied →
  mic-blocked screen; iOS Safari specifically.
- Known: chat input "Maximum update depth" error while typing predates this
  branch; to be handled by a separate /fix.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":14450,"specSha256":"af80ee8b188813144c012d353f6029e22c54f0370100220550a94dd9e61e2e68","branch":"refs/heads/feature/mobile-voice-and-audio-reactive-voice-ui","head":"8fbfe1533add34855a2511a28926e30d173260b1","baseRef":"refs/heads/master","baseCommit":"24044a9dc29c5a1ca3d30fbb9781459b70ab7c58","sourceTree":"0a97201434ab3ecb03a1545a521e9e3aa2730e1a","absentOptional":[]} -->
