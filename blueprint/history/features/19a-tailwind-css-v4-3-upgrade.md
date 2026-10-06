# Feature: Tailwind CSS v4.3 upgrade

**From build-plan:** feature 19a
**Build attempt:** 1
**Type:** Feature
**Status:** verified
**Branch:** feature/tailwind-css-v4-3-upgrade

## Goal

Move the frontend from Tailwind CSS v3.4 to v4.3 with no intended visual or
behavioural change, so 19b (responsive chat layout) and 19c (mobile voice) are
written in v4 syntax from the start.

## In scope

- `tailwindcss` `^3.4.1` -> `^4.3.3`; add `@tailwindcss/postcss`; PostCSS uses
  that plugin instead of `tailwindcss`.
- Theme moves from `frontend/tailwind.config.ts` into a CSS `@theme` block in
  `frontend/src/app/globals.css` (colors, font families, the `xl`/`2xl`/`3xl`
  radii, the `class` dark-mode variant). The JS config is deleted once nothing
  references it.
- `@tailwind base/components/utilities` -> `@import 'tailwindcss'`.
- `tailwindcss-animate` -> `tw-animate-css` so the Radix dialog, select and
  tooltip `animate-in`/`fade-*`/`zoom-*`/`slide-*` classes keep working.
- v3 -> v4 utility renames across `frontend/src/` (for example `shadow-sm` ->
  `shadow-xs`, `shadow` -> `shadow-sm`, `rounded` -> `rounded-sm`, `blur` ->
  `blur-sm`, bare `ring` -> `ring-3`, `outline-none` -> `outline-hidden`,
  `flex-shrink-0` -> `shrink-0`, `flex-grow` -> `grow`).
- v3 base-style parity: default border color, button cursor, placeholder color.
- Tooling: `prettier-plugin-tailwindcss` pointed at the v4 stylesheet;
  `components.json` updated for a config-less v4 setup.

## Out of scope

- Any responsive or mobile change (19b, 19c). Existing `h-screen`/`100vh` stay.
- Redesign, new tokens, or restyling. Tidying the arbitrary hex classes
  (`bg-[#0a0f1e]` and similar) into tokens.
- Changes to the hand-written CSS in `globals.css` beyond what v4 requires
  (orbs, glass panels, scrollbar, grid dots stay as they are).
- Behavioural edits to `LiveKitVoiceModal.tsx`; it gets the mechanical class
  renames only, like every other file.
- Upgrading Next.js, React, ESLint or Prettier.
- Fixing the pre-existing `npm run format` failure on `.next/` output (see
  Testing).

## Build loop

`workflow.stepReview` is `feature`: build all steps, then present one review
packet. `workflow.checkpointCommits` is `disabled`: no commits per step.
`/complete` creates the single feature commit.

## Build steps

- [x] **1. Run the official upgrade.** On the feature branch with a clean tree,
  run `npx @tailwindcss/upgrade@4.3` from `frontend/` (it requires a clean
  working tree). Read its full diff before keeping it. Confirm it installed
  `tailwindcss@^4.3`, added `@tailwindcss/postcss`, rewrote
  `postcss.config.mjs`, migrated the theme to `@theme`, replaced the
  `@tailwind` directives, and renamed utilities. Lockfile stays
  `package-lock.json` (npm only; no `pnpm-lock.yaml` or `yarn.lock`).
  *Done when:* `package.json` shows `tailwindcss` 4.3.x, `cd frontend && npm
  run build` succeeds, and the diff contains only Tailwind-migration changes.

- [x] **2. Replace the animation plugin.** Uninstall `tailwindcss-animate`,
  install `tw-animate-css`, add `@import 'tw-animate-css';` after the Tailwind
  import in `globals.css`, and remove any leftover `@plugin` or `plugins`
  reference to the old package.
  *Done when:* `tailwindcss-animate` is absent from `package.json` and the
  lockfile, the build succeeds, and the dialog, select and tooltip in
  `src/components/ui/` still animate open and closed in the browser.

- [x] **3. Restore v3 base behaviour and tidy the theme.** Check the migrated
  `@theme` block against the old `tailwind.config.ts`: every color, font family
  and radius present with the same value. Make sure these are kept:
  - Default border color matches v3 (`gray-200` equivalent), unless the upgrade
    tool already added its compatibility base rule.
  - `cursor: pointer` on buttons, which v4 removed.
  - The `border` color token. It is `rgba(var(--color-border-default))`, which
    reads the comma-separated `--color-border-default` from `:root`. It must
    still resolve to `rgba(255,255,255,0.08)` in the built CSS.
  - The `class` dark-mode variant, as `@custom-variant dark`.

  Delete `tailwind.config.ts` if nothing references it. Set
  `"tailwind": { "config": "" }` in `components.json`. Add
  `tailwindStylesheet: './src/app/globals.css'` to `prettier.config.cjs`, and
  upgrade `prettier-plugin-tailwindcss` within 0.6.x if v4 class sorting needs
  it.
  *Done when:* there is no reference to `tailwind.config` in the frontend except
  history, `npx prettier --check "src/**/*.{ts,tsx}"` passes, and a computed
  style check in the browser shows the `border-border` color as
  `rgba(255, 255, 255, 0.08)`.

- [x] **4. Sweep for missed renames and verify visually.** Grep `frontend/src`
  for v3-only class names the tool can miss: classes built in template
  strings, `cn()` or `clsx` arguments, and string constants. Then check the app
  at desktop width (1440px) and phone width (390px) against `master`. Use the
  dev server or a production build, with a screenshot for each:
  - chat blank state
  - sidebar and session list
  - a streamed assistant message with markdown (code block, table)
  - booking card and lead form, if reachable
  - the AssemblyAI voice modal opened; no mic session is needed

  *Done when:* no v3-only class names remain, and every view looks the same as
  on `master`. A small change that can't be avoided (such as v4's slightly
  different shadow scale) counts only if the review packet lists it.

## Files / areas

- `frontend/package.json`, `frontend/package-lock.json`
- `frontend/postcss.config.mjs`
- `frontend/tailwind.config.ts` (removed)
- `frontend/src/app/globals.css`
- `frontend/components.json`, `frontend/prettier.config.cjs`
- `frontend/src/components/**`, `frontend/src/app/**`: mechanical class renames
  only. Notably `ui/dialog.tsx`, `ui/select.tsx` and `ui/tooltip/tooltip.tsx`
  for the animation classes.

## Data / contracts

None. No API, storage, env var or backend change. Browser support rises to
Tailwind v4's baseline: Safari 16.4+, Chrome 111+, Firefox 128+. That matches
the iOS Safari 16.4+ floor in the project plan.

## Build notes

- Steps 1-4 done. Step 4 evidence is partial: the rename sweep found no
  v3-only classes; the built CSS was checked for the border token, the
  animation classes and the button cursor; one user desktop screenshot of the
  blank-state chat matched the pre-upgrade look apart from the two buttons
  fixed below. Markdown, tool cards, voice-modal animation and 390px views
  were not screenshot-compared; the user chose to complete. The voice-modal
  breakage the user reported mid-conversation predates this upgrade (the voice
  files only got equivalent renames) and moves to 19c.
- Beyond the spec: the upgrade tool also swapped some arbitrary hex classes for
  theme tokens with identical values, for example `bg-[#0a0f1e]` ->
  `bg-background` and `text-[#f48c06]` -> `text-accentGold`. Kept, pending
  review.
- Regression found in a user screenshot and fixed: the sidebar "Live voice
  agent" button and the chat-input mic button rendered pale peach.
  `tailwind-merge` 3 didn't recognise v3's `bg-gradient-to-*` as a gradient, so
  it had been silently dropping the Button's default `bg-primary` (#fafafa).
  With v4's `bg-linear-to-*` the white base stays under a 20% gradient. Both
  buttons now carry an explicit `bg-transparent`.
- The tool bumped `prettier-plugin-tailwindcss` to 0.8.1, which crashes on
  Prettier 3.4.2. Pinned back to `^0.6.14`, per the spec.

## Testing

- No unit test runner and no Browser tests command exist, so verification is
  the frontend checks plus manual browser evidence.
- Baseline on `master` before this feature:
  - `npm run lint` passes, with one existing `no-page-custom-font` warning.
  - `npm run typecheck` passes.
  - `prettier --check "src/**/*.{ts,tsx}"` passes.
  - `npm run format`, and therefore `npm run validate`, already fails, but only
    on generated `.next/types/*` files because there is no `.prettierignore`.
    That failure is not caused by this feature and is not fixed here.
- Final gate: `npm run lint`, `npm run typecheck`, `npx prettier --check
  "src/**/*.{ts,tsx}"`, and `npm run build` all pass. Step 4 adds the
  screenshot comparison.
- Do not claim visual parity without the step 4 screenshots.

## Notes for the AI

- The upgrade tool refuses to run on a dirty tree. Commit nothing by hand;
  stash or keep the branch clean before step 1.
- v4 detects class sources automatically, so the old `content` globs need no
  replacement. Classes built from fragments, such as `` `bg-${x}` ``, are
  still not detected. Leave existing behaviour as it is.
- `tailwind-merge` 3.x already supports v4 class names. Do not change `cn()`.
- In v4, `@layer base` in `globals.css` still works. Keep the existing reset
  and font rules in it.
- LiveKit is dormant. Make no behavioural edits in `LiveKitVoiceModal.tsx`
  beyond what the tool renames.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":8968,"specSha256":"ff4ddcad3d3899ce85e0b3ed41275fb82ed287e36c5b50e7a86a7fc50936ad61","branch":"refs/heads/feature/tailwind-css-v4-3-upgrade","head":"51ab5562e4c3f26b8741ac33dc70cc5c8e39e9be","baseRef":"refs/heads/master","baseCommit":"51ab5562e4c3f26b8741ac33dc70cc5c8e39e9be","sourceTree":"374babe1ac7f7963ac174da91f8063be5d5b9d51","absentOptional":[]} -->
