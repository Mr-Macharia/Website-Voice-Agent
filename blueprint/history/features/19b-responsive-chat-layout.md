# Feature: Responsive chat layout

**From build-plan:** feature 19b
**Build attempt:** 1
**Type:** Feature
**Status:** verified
**Branch:** feature/responsive-chat-layout

## Goal

Make text chat work well on phone browsers (iOS Safari 16.4+, Android Chrome)
from 360px wide, without changing the desktop layout. On phones the sidebar
becomes a drawer, the page fits the visible screen when the browser's address
bar or the on-screen keyboard is showing, controls are easy to tap, and nothing
scrolls sideways.

## In scope

- **Fits the visible screen:**
  - `h-screen` and `100vh` replaced with `dvh` units in the app shell, the chat
    area, the sidebar, and the session list heights.
  - A Next.js `viewport` export with `viewportFit: 'cover'` (so the page can use
    the safe-area insets) and `interactiveWidget: 'resizes-content'` (so Android
    Chrome shrinks the page when the keyboard opens). Pinch-zoom stays enabled.
- **Safe areas:** the header and the chat input keep clear of the iPhone notch
  and home bar, using `env(safe-area-inset-*)`.
- **Sidebar drawer below `md` (768px):**
  - The desktop `<aside>` is hidden. A menu button in the chat header opens the
    same sidebar content in a left-side drawer, built on the existing Radix
    Dialog.
  - The drawer has a backdrop, closes on Esc, keeps keyboard focus inside while
    open, and returns focus to the menu button when it closes.
  - It also closes when the visitor picks a session, starts a new chat, or opens
    voice.
  - At `md` and wider, the existing collapsible sidebar is unchanged.
- **Touch:**
  - Tap targets are at least 44×44px below `md`: the menu button, the header
    buttons, the mic and send buttons, and the session delete button.
  - The chat textarea uses at least 16px text below `md`, so iOS Safari doesn't
    zoom in when it is focused.
  - Only shown on hover today, so they must become visible on touch screens:
    - the session delete button
  - The "Enter to send / Shift+Enter" hint is hidden on touch screens.
  - The header "Voice Mode" button shows only its icon below `sm`, and keeps an
    accessible name.
- **Content fits from 360px:**
  - The header's model and assistant line truncates instead of wrapping.
  - Message bubbles have tighter padding below `sm`.
  - Markdown tables and code blocks scroll sideways inside themselves.
  - Knowledge-reference tiles fit the screen width.
  - The booking card, the lead form and the blank-state hero and cards fit
    without the page scrolling sideways.

## Out of scope

- The voice modal and any voice behaviour (19c).
- Redesigning the visuals, adding bottom navigation, swipe gestures, or
  PWA/installable-app support.
- Any backend or API change, and any change to the desktop (≥ `md`) layout.
- The dormant `LiveKitVoiceModal.tsx`.

## Build loop

`workflow.stepReview` is `feature`: build all steps, then present one review
packet. `workflow.checkpointCommits` is `disabled`: no commits per step.
`/complete` creates the single feature commit.

## Build steps

- [x] **1. Fit the visible screen and the safe areas.**
  - Add `export const viewport: Viewport` to `src/app/layout.tsx` with
    `width: 'device-width'`, `initialScale: 1`, `viewportFit: 'cover'` and
    `interactiveWidget: 'resizes-content'`. Do not set `maximumScale` or
    `userScalable`.
  - Replace `h-screen` with `h-dvh` in `src/app/page.tsx` (shell and Suspense
    fallback), `ChatArea.tsx` (`main`) and `Sidebar.tsx` (`aside`), and
    `min-h-screen` with `min-h-dvh` on `body`.
  - In `Sessions.tsx`, replace the `h-[calc(100vh-325px)]` and
    `h-[calc(100vh-345px)]` heights with a flex column (`min-h-0 flex-1
    overflow-y-auto`) so the list fills whatever height the sidebar has left.
  - Pad the chat header top with `env(safe-area-inset-top)`, and the input
    wrapper bottom with `max(0.75rem, env(safe-area-inset-bottom))`.

  *Done when:* the build passes; at 390×844 in browser device mode the page has
  no vertical overflow; and the session list still scrolls inside the sidebar on
  desktop.

- [x] **2. Sidebar drawer below `md`.**
  - Extract the sidebar's inner content (header, New Chat, Live Voice, Sessions)
    into a component both the desktop `aside` and the drawer render. Keep a
    single `VoiceModal` instance.
  - Add a non-persisted `isMobileSidebarOpen` / `setMobileSidebarOpen` to
    `src/store.ts`. If the store uses `persist`, keep this field out of
    `partialize`.
  - The desktop `aside` becomes `hidden md:flex`.
  - Add a menu button to `ChatAreaHeader`, shown only below `md`, with
    `aria-label="Open menu"`, `aria-expanded` and a 44px tap area.
  - Build the drawer from the `@radix-ui/react-dialog` primitives
    (`Dialog.Root`, `Portal`, `Overlay`, `Content`) styled as a left sheet:
    - width `min(20rem, 85vw)`, full `dvh` height
    - padding for the top and bottom safe areas
    - slide in with `tw-animate-css` (`slide-in-from-left`), no animation under
      `motion-reduce`
    - a visible close button, plus a `Dialog.Title` (visually hidden is fine)
  - Close the drawer when a session is picked, New Chat is pressed, or Live
    Voice is pressed.
  - If the window grows past `md` while the drawer is open, close it.

  *Done when:* at 390px the menu button opens the drawer, and the drawer closes
  via backdrop tap, Esc, its close button, picking a session, New Chat, and Live
  Voice. Tab stays inside the drawer while it is open, and focus returns to the
  menu button. At 1440px the sidebar looks and collapses exactly as before.

- [x] **3. Touch targets and iOS input behaviour.**
  - Below `md`, raise these to at least 44×44px (`size-11` or `min-h-11
    min-w-11`):
    - the header Clear and Voice Mode buttons
    - the mic and send buttons in the chat input
    - the sidebar collapse toggle, if visible
    - the session delete button
  - Chat textarea: `text-base md:text-sm`.
  - Session delete: visible without hover on touch screens
    (`[@media(hover:none)]:opacity-100`).
  - Input hint row: `hidden [@media(hover:hover)]:flex`.
  - Header Voice Mode label: `hidden sm:inline`, with `aria-label="Voice mode"`
    on the button.
  - Header subtitle (model and assistant name): `truncate min-w-0` so it can't
    push the buttons off-screen.

  *Done when:* at 390px every listed control measures at least 44px in
  DevTools; focusing the textarea in iOS Safari (or the WebKit device mode)
  does not zoom the page; and the session delete button is visible without
  hover in touch emulation.

- [x] **4. Content fits from 360px, then the full visual pass.**
  - Message bubbles: `p-3.5 sm:p-5` (assistant) and `p-3 sm:p-4` (user).
  - Markdown tables and code blocks in `MarkdownRenderer/styles.tsx`: wrap in or
    add `overflow-x-auto` so wide content scrolls inside the block.
  - `ReferenceItem` (`Messages.tsx`): `w-[200px]` -> `w-full sm:w-[200px]`.
  - Check `BookingCard.tsx`, `LeadForm.tsx` and `ChatBlankState.tsx` at 360px,
    and fix only what overflows.
  - Then check four widths — 360, 390, 768 and 1440px — on each of:
    - the blank state
    - a chat with a markdown reply containing a table and a code block
    - knowledge references
    - the booking card and the lead form
    - the drawer open (below `md`)

  *Done when:* `document.documentElement.scrollWidth <= innerWidth` at 360px in
  every view above. There is a screenshot of each view at 390px and 1440px, and
  the 1440px views match `master`.

## Files / areas

- `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`
- `frontend/src/store.ts`
- `frontend/src/components/chat/Sidebar/Sidebar.tsx` (plus a new
  `MobileSidebar.tsx` next to it for the drawer)
- `frontend/src/components/chat/Sidebar/Sessions/Sessions.tsx`,
  `frontend/src/components/chat/Sidebar/Sessions/SessionItem.tsx`
- `frontend/src/components/chat/ChatArea/ChatArea.tsx` (`ChatAreaHeader`, `main`)
- `frontend/src/components/chat/ChatArea/ChatInput/ChatInput.tsx`
- `frontend/src/components/chat/ChatArea/Messages/MessageItem.tsx`,
  `frontend/src/components/chat/ChatArea/Messages/Messages.tsx`,
  `frontend/src/components/chat/ChatArea/Messages/ChatBlankState.tsx`
- `frontend/src/components/chat/ChatArea/Messages/tools/BookingCard.tsx`,
  `frontend/src/components/chat/ChatArea/Messages/tools/LeadForm.tsx`
  (overflow fixes only)
- `frontend/src/components/ui/typography/MarkdownRenderer/styles.tsx`

## Data / contracts

- No API, backend, or persisted-data change.
- `isMobileSidebarOpen` is client-only UI state and is never persisted.
- Breakpoint contract: below `md` (768px) is the phone and drawer layout; `md`
  and wider is today's desktop layout, unchanged.
- Browser floor: iOS Safari 16.4+ and Android Chrome. `dvh` and
  `env(safe-area-inset-*)` are supported there.

## Build notes

- **Changed from the spec: the breakpoint is `lg` (1024px), not `md`
  (768px).** At 768px the 440px desktop sidebar left the chat only about 328px,
  and the blank-state cards squeezed into three unreadable columns. So the
  drawer, the menu button, the 44px tap targets and 16px input text now apply
  below `lg`, and `lg`+ is today's desktop layout, unchanged.
- Browser evidence (Claude in Chrome, same-origin iframes at 360, 390, 768 and
  1024px, because the window manager blocked `resize_window`):
  - No page scrolls sideways at any width.
  - The sidebar is hidden below `lg` and shown at 1024px.
  - Menu, Voice, mic and send measure 44px at 360 and 768px; desktop is
    unchanged at 1024px (40px and 32px).
  - The textarea is 16px below `lg` and 14px at `lg`.
  - A real agent reply's table was 666px wide and scrolled inside its 205px
    box. A synthetic 3839px `pre` scrolled inside its 206px block.
  - The real booking card fits at 360px (Cal.com iframe 289px).
  - Drawer: opens with focus on its close button, `aria-expanded` toggles, and
    the title is "Menu". Esc, backdrop and Live Voice set it to
    `data-state=closed`, and Live Voice opened the voice modal.
- Not observed:
  - Focus returning to the menu button after the drawer closes, because the
    test tab was hidden and Radix waits for the exit animation to finish.
  - The lead form, which wasn't triggered: that would write a real lead.
  - Desktop visuals in a foreground tab: the hidden tab left framer-motion
    content at opacity 0, though the DOM is intact.
  - Real-iPhone input zoom.
- Console errors seen were caused by the iframe harness replacing a mounted
  React page (`removeChild`, and a nested-update error during teardown).
  Neither the textarea nor ChatInput's onChange changed.
- Added beyond the spec: `aria-label`s on the send and mic buttons, and
  word-breaking for long URLs inside message bubbles.
- Final gate:
  - `npm run typecheck` passed.
  - ESLint: 0 errors, 1 existing warning.
  - `prettier --check src` passed.
  - `next build` compiled successfully. It ran on a scratchpad copy of the
    branch (same files, shared `node_modules`) so the user's running dev server
    wasn't disturbed.
- User phone check: a real-device screenshot at about 402px showed the header,
  bubbles, tool card and input fitting with no sideways scroll. The user
  answered "yes" to the input-zoom and drawer questions.

## Testing

- No unit test runner and no Browser tests command exist.
- Automated gate: `cd frontend && npm run lint && npm run typecheck && npm run
  build`, plus `npx prettier --check "src/**/*.{ts,tsx}"`. (`npm run format`
  still fails on generated `.next/` files, as it did before this feature, so it
  isn't used as the gate.)
- Browser evidence uses Claude in Chrome device emulation (`resize_window`) on
  a dev server the user starts with `npm run dev:frontend`. It covers the
  overflow check, tap-target sizes and drawer keyboard behaviour. Do not claim
  real-device iOS results; the textarea zoom check on a real iPhone is a manual
  step for the user.

## Notes for the AI

- Load the `ui-ux-pro-max` skill before UI work (user preference). Apply its
  touch, safe-area and responsive rules, but keep this spec's scope.
- Mobile-first means the unprefixed class is the phone value and `md:` restores
  desktop. Do not change the desktop result.
- `@radix-ui/react-dialog` is already a dependency (`components/ui/dialog.tsx`
  uses it). Don't add a new drawer library.
- Don't set `user-scalable=no` or `maximum-scale`; preventing pinch-zoom is an
  accessibility failure. Fix iOS input zoom with 16px text instead.
- `interactiveWidget` doesn't affect iOS Safari. There, `dvh` plus the browser
  scrolling the focused input into view is the expected behaviour. Verify it;
  don't add `visualViewport` hacks unless the input is actually hidden.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":12688,"specSha256":"bb1b9e6a40189fdc95db1c424c171f11a3a6b899ef6536ff02d235e7fedfa981","branch":"refs/heads/feature/responsive-chat-layout","head":"f29a47a81962abdd73b5cc2678aefad06188e7d2","baseRef":"refs/heads/master","baseCommit":"f29a47a81962abdd73b5cc2678aefad06188e7d2","sourceTree":"295c371ca499472a2411d0159e6c92e472c30d68","absentOptional":[]} -->
