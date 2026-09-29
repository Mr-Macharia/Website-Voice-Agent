# Fix: Fix Vercel frontend deploy and drop dead frontend config

**Type:** Fix
**Status:** verified
**Branch:** fix/fix-vercel-frontend-deploy-and-drop-dead-frontend-config

## The problem

**Deploy is broken.** The Vercel project uses Root Directory `frontend`, but
the repo-root `vercel.json` still sets `installCommand: "cd frontend && npm
install"`, `buildCommand: "cd frontend && npm run build"` and
`outputDirectory: "frontend/.next"`. Vercel applied it, and the build failed
(commit `c601705`: `cd: frontend: No such file or directory`). The file was
written for building from the repo root, and it overrides the dashboard.

**Dead config left behind by F-14** (found while answering which environment
variables the frontend needs):
- `frontend/src/app/api/stt/route.ts` has no callers in `frontend/src`. It is a
  public, unthrottled route that spends Deepgram credit whenever
  `DEEPGRAM_API_KEY` is set on Vercel.
- `frontend/next.config.ts` still inlines `NEXT_PUBLIC_LIVEKIT_URL`, which
  nothing reads any more. Its comment still describes the deleted LiveKit
  token route.
- `docs/deployment.md` describes the root `vercel.json` (line 47) and lists
  `DEEPGRAM_API_KEY` as a Vercel variable (line 52).

## The fix

1. Delete the root `vercel.json`. The Root Directory setting already does its
   job.
2. Delete the `api/stt` route.
3. In `next.config.ts`, remove the `env` block and reword the comment. Keep
   `loadRootEnv()`, because local dev still needs `NEXT_PUBLIC_AGENT_OS_URL`
   from the root `.env`.
4. Rewrite the Vercel section of `docs/deployment.md` to match:
   - Root Directory is `frontend`.
   - Install Command is overridden to `npm install`, so Vercel does not
     choose pnpm from the stray `pnpm-lock.yaml`.
   - Build Command and Output Directory stay on their defaults.
   - The only variable is `NEXT_PUBLIC_AGENT_OS_URL`, with
     `NEXT_PUBLIC_VOICE_PROVIDER` optional.

**Must not break:** local `npm run dev:all`, which still loads the root `.env`,
and `npm run build`.

**Out of scope:**
- F-15. Removing `livekit-server-sdk` changes lockfiles, and
  `pnpm-lock.yaml` has an unreviewed diff on disk.
- Choosing a single lockfile.
- Any Heroku change.

## Build steps

- [x] **1. Remove the dead config and fix the docs.** Delete `vercel.json` and
  `frontend/src/app/api/stt/`. Trim `next.config.ts`. Update
  `docs/deployment.md`.
  **Done when:**
  - `grep -rnE "process\.env\.(DEEPGRAM|LIVEKIT|NEXT_PUBLIC_LIVEKIT)"
    frontend/src frontend/next.config.ts` returns nothing. (The LiveKit modal's
    warning text still names the backend variables, and that is expected.)
  - `npm run typecheck`, `cd frontend && npm run lint` and
    `cd frontend && npm run build` pass.
  - The build's route list shows no `/api/stt`.

## Verify

- After merge and push, Vercel (Root Directory `frontend`, Install Command
  `npm install`, `NEXT_PUBLIC_AGENT_OS_URL` set) builds successfully.
- The deployed site loads, chat replies, and the voice modal connects.
- `/api/stt` and `/api/livekit/token` on the Vercel domain return 404.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":3067,"specSha256":"f778f39631b24e67324966b2658eaa134f73543949a0d7a8dfb0ffd69d0bbecc","branch":"refs/heads/fix/fix-vercel-frontend-deploy-and-drop-dead-frontend-config","head":"c601705b6769ec79f0f9226c1f318542ecaa1e2c","baseRef":"refs/heads/master","baseCommit":"c601705b6769ec79f0f9226c1f318542ecaa1e2c","sourceTree":"34a1f3c487631b9f7188d2915bc6284d106e8b59","absentOptional":[]} -->
