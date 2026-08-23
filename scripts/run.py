#!/usr/bin/env python3
"""
Run both backend services together for effective live voice streaming.

Starts:
  1) FastAPI + Agno + Deepgram Flux TTS server  (backend/server.py → http://localhost:7777)
  2) LiveKit WebRTC worker                        (backend/livekit_worker.py dev → joins LiveKit rooms)

Optionally also starts:
  3) Next.js frontend                             (frontend → http://localhost:3000) with --with-frontend / -f

Usage:
  python scripts/run.py                  # backend + worker
  python scripts/run.py -f               # backend + worker + frontend
  python scripts/run.py --worker-only    # only worker
  python scripts/run.py --backend-only   # only backend
  python scripts/run.py --frontend-only  # only frontend
  python scripts/run.py --with-frontend --port 7777 --frontend-port 3000

Features:
  - Uses `uv run` if available, falls back to `python`
  - Colored prefixed logs: [backend] [worker] [frontend]
  - Graceful shutdown on Ctrl+C (SIGINT/SIGTERM) — kills all children
  - Waits for backend /api/info before reporting ready
  - Validates .env keys (warns if DEEPGRAM_API_KEY / LIVEKIT / XAI missing)
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
import shutil
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
COLORS = {
    "backend": "\033[38;5;208m",  # orange
    "worker": "\033[38;5;39m",   # blue
    "frontend": "\033[38;5;114m", # green
    "reset": "\033[0m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "yellow": "\033[33m",
}

def has_uv() -> bool:
    return shutil.which("uv") is not None

def has_pnpm() -> bool:
    return shutil.which("pnpm") is not None

def load_dotenv_keys() -> dict:
    keys: dict = {}
    for p in [ROOT / ".env", BACKEND_DIR / ".env", ROOT / ".env.example"]:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k not in keys:  # first wins (real .env before .example)
                    keys[k] = v.strip()
    return keys

def has_livekit_config(keys: dict | None = None) -> bool:
    if keys is None:
        keys = load_dotenv_keys()
    lk_url = os.getenv("LIVEKIT_URL") or keys.get("LIVEKIT_URL") or ""
    # Treat placeholder values as missing
    lk_url = lk_url.strip()
    if not lk_url:
        return False
    if "your-project" in lk_url or "placeholder" in lk_url or "example" in lk_url:
        return False
    return True

def env_warnings():
    keys = load_dotenv_keys()
    for k in ["DEEPGRAM_API_KEY","XAI_API_KEY","OPENAI_API_KEY","LIVEKIT_URL","LIVEKIT_API_KEY","LIVEKIT_API_SECRET"]:
        if not os.getenv(k) and not keys.get(k):
            if k in ("DEEPGRAM_API_KEY",):
                print(f"{COLORS['red']}[warn] {k} not set — STT/TTS will fail{COLORS['reset']}")
            elif k in ("LIVEKIT_URL",):
                print(f"{COLORS['yellow']}[warn] {k} not set — LiveKit WebRTC disabled, using Direct WS bridge (still works){COLORS['reset']}")
            elif k in ("XAI_API_KEY","OPENAI_API_KEY"):
                pass  # one of them needed; checked after loop
    if not (os.getenv("XAI_API_KEY") or keys.get("XAI_API_KEY") or os.getenv("OPENAI_API_KEY") or keys.get("OPENAI_API_KEY")):
        print(f"{COLORS['red']}[warn] Neither XAI_API_KEY nor OPENAI_API_KEY set — LLM will fallback to LiveKit Inference (requires LiveKit Cloud){COLORS['reset']}")
    if not has_livekit_config(keys):
        print(f"{COLORS['yellow']}[info] LiveKit worker will be skipped (no LIVEKIT_URL). Backend WS /ws/voice still provides full voice chat.{COLORS['reset']}")

def stream_output(name: str, proc: subprocess.Popen):
    color = COLORS.get(name, "")
    reset = COLORS["reset"]
    # Use binary + text
    assert proc.stdout is not None
    for line in iter(proc.stdout.readline, ""):
        if line == "":
            break
        # strip trailing newline, keep prefix
        sys.stdout.write(f"{color}[{name}]{reset} {line}")
        sys.stdout.flush()
    # also drain stderr if separate? we merged stderr→stdout

def wait_for_backend(port: int, timeout: int = 25):
    import urllib.request, urllib.error, json
    url = f"http://localhost:{port}/api/info"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    data = json.loads(r.read().decode())
                    print(f"{COLORS['dim']}✓ backend ready: {data.get('service')} @ {url}{COLORS['reset']}")
                    return True
        except Exception:
            pass
        time.sleep(0.8)
    print(f"{COLORS['yellow']}[wait] backend not responding at {url} after {timeout}s — check logs above{COLORS['reset']}")
    return False

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Run backend + LiveKit worker (+ optional frontend)")
    ap.add_argument("-f","--with-frontend", action="store_true", help="also start Next.js frontend")
    ap.add_argument("--backend-only", action="store_true", help="only run backend server")
    ap.add_argument("--worker-only", action="store_true", help="only run LiveKit worker")
    ap.add_argument("--frontend-only", action="store_true", help="only run frontend")
    ap.add_argument("--port", type=int, default=7777, help="backend port (default 7777)")
    ap.add_argument("--frontend-port", type=int, default=3000, help="frontend port (default 3000)")
    ap.add_argument("--worker-mode", default="dev", choices=["dev","start"], help="livekit_worker mode: dev (default) or start (prod)")
    args = ap.parse_args()

    if args.frontend_only:
        run_backend = False
        run_worker = False
        run_frontend = True
    elif args.backend_only:
        run_backend = True
        run_worker = False
        run_frontend = False
    elif args.worker_only:
        run_backend = False
        run_worker = True
        run_frontend = False
    else:
        run_backend = True
        run_worker = True
        run_frontend = bool(args.with_frontend)

    procs: list[tuple[str, subprocess.Popen]] = []

    def spawn(name: str, cmd: list[str], cwd: Path, env=None):
        print(f"{COLORS['dim']}→ starting {name}: {' '.join(cmd)} (cwd={cwd}){COLORS['reset']}")
        # Merge stderr into stdout for unified prefix
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        procs.append((name, p))
        t = threading.Thread(target=stream_output, args=(name, p), daemon=True)
        t.start()
        return p

    print(f"{COLORS['dim']}voice-agent runner — root={ROOT}{COLORS['reset']}")
    env_warnings()
    use_uv = has_uv()
    use_pnpm = has_pnpm()

    # Check LiveKit config early — if missing, disable worker gracefully
    keys = load_dotenv_keys()
    livekit_ok = has_livekit_config(keys)
    if run_worker and not livekit_ok and not args.worker_only:
        print(f"{COLORS['yellow']}[worker] Skipping LiveKit worker — LIVEKIT_URL not configured. Backend alone handles voice via /ws/voice (Direct WS bridge).")
        print(f"{COLORS['dim']}         To enable LiveKit: set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env, then rerun.{COLORS['reset']}")
        run_worker = False
    elif run_worker and args.worker_only and not livekit_ok:
        # worker-only mode with no config should still fail fast with helpful message
        print(f"{COLORS['red']}[error] LIVEKIT_URL is required for worker-only mode. Set it in .env or root .env.{COLORS['reset']}")
        print(f"{COLORS['dim']}  Example: LIVEKIT_URL=wss://your-project.livekit.cloud{COLORS['reset']}")
        return 1

    backend_env = os.environ.copy()
    # Ensure unbuffered python output
    backend_env["PYTHONUNBUFFERED"] = "1"
    # Avoid uv VIRTUAL_ENV mismatch warning when root .venv vs backend/.venv
    # Use --active to target the active environment; we handle by removing VIRTUAL_ENV for uv calls
    # (uv will then use the project environment at BACKEND_DIR/.venv or ROOT/.venv correctly)
    backend_env.pop("VIRTUAL_ENV", None)

    try:
        if run_backend:
            if use_uv:
                cmd = ["uv", "run", "--active", "python", "server.py"]
            else:
                cmd = [sys.executable, "server.py"]
            spawn("backend", cmd, BACKEND_DIR, env=backend_env)
            # give uv a moment to install/lock before starting worker
            time.sleep(2)
            wait_for_backend(args.port, timeout=25)

        if run_worker:
            if use_uv:
                cmd = ["uv", "run", "--active", "python", "livekit_worker.py", args.worker_mode]
            else:
                cmd = [sys.executable, "livekit_worker.py", args.worker_mode]
            # slight delay so backend is ready before worker joins rooms
            if run_backend:
                time.sleep(1.5)
            spawn("worker", cmd, BACKEND_DIR, env=backend_env)

        if run_frontend:
            # frontend env: ensure NEXT_PUBLIC_LIVEKIT_URL etc are read from root .env if present
            if use_pnpm:
                cmd = ["pnpm", "dev", "--port", str(args.frontend_port)]
                # pnpm dev in frontend/package.json already sets -p 3000, but allow override via env PORT
                # Use npx next dev -p explicitly for custom port
                if args.frontend_port != 3000:
                    cmd = ["pnpm", "exec", "next", "dev", "-p", str(args.frontend_port)]
            else:
                # fallback npm
                if shutil.which("npm"):
                    cmd = ["npm", "run", "dev"]
                else:
                    print(f"{COLORS['red']}[frontend] neither pnpm nor npm found{COLORS['reset']}")
                    cmd = []
            if cmd:
                spawn("frontend", cmd, FRONTEND_DIR)

        if not procs:
            print("Nothing to run. Use --help")
            return 1

        # Print ready banner
        time.sleep(0.5)
        print("\n" + "="*60)
        print(f"  Voice Agent — services running")
        if run_backend:
            print(f"  • Backend (FastAPI + Deepgram Flux) → http://localhost:{args.port}  (/api/info, /docs, /ws/voice)")
        if run_worker:
            print(f"  • LiveKit worker (flux-brooke-en)     → mode={args.worker_mode}  (joining LiveKit rooms)")
        if run_frontend:
            print(f"  • Frontend (Next.js)                  → http://localhost:{args.frontend_port}")
        print(f"  Stop: Ctrl+C")
        print("="*60 + "\n")

        # Wait for any proc to exit, or Ctrl+C
        def handle_sig(sig, frame):
            print(f"\n{COLORS['dim']}Received {signal.Signals(sig).name}, shutting down...{COLORS['reset']}")
            for name, p in procs:
                if p.poll() is None:
                    try:
                        # try graceful SIGTERM, then SIGKILL
                        p.terminate()
                    except Exception:
                        pass
            # give 4s for graceful, then kill
            time.sleep(2)
            for name, p in procs:
                if p.poll() is None:
                    try:
                        p.kill()
                    except Exception:
                        pass
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_sig)
        signal.signal(signal.SIGTERM, handle_sig)

        # Monitor loop: backend is critical; worker/frontend are optional
        # If worker exits (e.g., bad LiveKit creds), keep backend alive.
        while True:
            time.sleep(1)
            for name, p in procs:
                ret = p.poll()
                if ret is not None:
                    color = COLORS.get(name, "")
                    print(f"\n{color}[{name}] exited with code {ret}{COLORS['reset']}")
                    if name == "backend":
                        # backend is critical — stop everything
                        for n2, p2 in procs:
                            if p2.poll() is None and n2 != name:
                                try:
                                    p2.terminate()
                                    time.sleep(1)
                                    if p2.poll() is None:
                                        p2.kill()
                                except Exception:
                                    pass
                        sys.exit(ret if ret != 0 else 1)
                    elif name == "worker":
                        # worker optional — log and keep backend/frontend running
                        print(f"{COLORS['yellow']}[worker] LiveKit worker stopped. Backend /ws/voice still serves voice chat.")
                        print(f"{COLORS['dim']}         Fix LIVEKIT_URL/KEY/SECRET and rerun with --worker-only or restart.{COLORS['reset']}")
                        # remove from list so we don't loop on it
                        procs = [(n, pr) for n, pr in procs if n != "worker"]
                        if not procs:
                            sys.exit(ret)
                        # continue monitoring remaining procs
                    elif name == "frontend":
                        print(f"{COLORS['yellow']}[frontend] frontend stopped.{COLORS['reset']}")
                        procs = [(n, pr) for n, pr in procs if n != "frontend"]
                        if not procs:
                            sys.exit(ret)
            if not procs:
                sys.exit(0)
            # keep looping

    except KeyboardInterrupt:
        print("\nInterrupted, shutting down...")
        for _, p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for _, p in procs:
            try:
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass
        return 0

if __name__ == "__main__":
    sys.exit(main())
