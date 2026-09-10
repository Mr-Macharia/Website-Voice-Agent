import fs from 'fs'
import path from 'path'
import type { NextConfig } from 'next'

// The project keeps a single source of truth for secrets in the repo-root
// .env, but Next.js only auto-loads .env files from the frontend directory.
// Without this, LIVEKIT_API_KEY/SECRET fall back to the "devkey" defaults and
// the browser gets "invalid API key" from LiveKit Cloud.
function loadRootEnv() {
  const rootEnv = path.join(__dirname, '..', '.env')
  if (!fs.existsSync(rootEnv)) return

  for (const rawLine of fs.readFileSync(rootEnv, 'utf8').split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue

    const eq = line.indexOf('=')
    if (eq === -1) continue

    const key = line.slice(0, eq).trim()
    let value = line.slice(eq + 1).trim()

    // Strip matching surrounding quotes.
    const first = value[0]
    if (
      value.length >= 2 &&
      (first === '"' || first === "'") &&
      value[value.length - 1] === first
    ) {
      value = value.slice(1, -1)
    }

    // Anything already in the real environment wins.
    if (process.env[key] === undefined) process.env[key] = value
  }
}

loadRootEnv()

const nextConfig: NextConfig = {
  // Multiple lockfiles exist above this directory, so Next would otherwise
  // infer the home directory as the workspace root. Pin it to this project.
  outputFileTracingRoot: path.join(__dirname),
  devIndicators: false,
  // NEXT_PUBLIC_* must be inlined at build time; it is read from the root .env
  // above, after Next has already done its own env loading.
  env: {
    NEXT_PUBLIC_LIVEKIT_URL:
      process.env.NEXT_PUBLIC_LIVEKIT_URL || process.env.LIVEKIT_URL || ''
  }
}

export default nextConfig
