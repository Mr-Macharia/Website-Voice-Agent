# Fix: Voice reply audio underruns

**Type:** Fix
**Status:** verified
**Branch:** fix/voice-reply-audio-underruns

## The problem

Reply audio in the AssemblyAI voice modal sounds glitchy. `/debug` ran
2026-09-30 and found two likely causes. It could not reproduce the glitch or
measure it live.

1. **No playback lead.** `AssemblyAISession.playChunk`
   (`frontend/src/lib/voice/AssemblyAISession.ts:502-507`) schedules each
   24 kHz reply chunk on a `nextPlayTime` cursor. When a chunk arrives after the
   queue has drained, the cursor snaps to `ctx.currentTime` and the chunk
   starts immediately, with no cushion. Every late chunk becomes an audible gap
   and often a click, and on an uneven connection this repeats throughout the
   reply.
2. **About 375 microphone messages a second on the main thread.**
   `public/worklets/pcm-processor.js` posts every 128-frame render quantum
   (about 2.7 ms at 48 kHz). `sendAudio` base64-encodes, JSON-wraps and sends
   each one. That load competes with decoding and scheduling reply chunks,
   which makes late chunks more likely.

## The fix

1. **Playback lead.** When a chunk arrives after the queue has drained
   (`nextPlayTime < now`), schedule it at `now + PLAYBACK_LEAD_S` instead of
   `now`. `PLAYBACK_LEAD_S` is a new named constant of 0.15 s, with a comment
   explaining the trade-off. Chunks that arrive while audio is still queued
   keep scheduling back to back, with no added delay. The first word of each
   reply and each recovery after a stall become 150 ms later, in exchange for
   no gap on every late chunk.
2. **Batch mic frames.** The worklet collects resampled PCM16 samples and posts
   once it holds at least 1200 samples, which is 50 ms at 24 kHz. The batch
   size is a named constant. The main-thread send path stays the same, now
   called about 20 times a second instead of about 375.

**Must not break:**
- **Barge-in.** `flushOutput()` still stops every queued source at once and
  resets the cursor. The next reply then gets the lead again.
- **Mute.** A muted mic sends nothing, as today. The worklet may keep a partial
  batch while muted, which is at most 50 ms of audio and harmless.
- **The output analyser** that drives the visualizer.
- **Tool calls, the booking card in voice mode, and the LiveKit modal.** The
  LiveKit modal doesn't use this worklet or session.

**Out of scope:**
- False-interrupt tuning (`interruption_delay`).
- Server-side audio settings.
- Any voice UI change.

## Build steps

- [x] **1. Add the playback lead and batch the mic frames.** Make fix items 1
  and 2 in `AssemblyAISession.ts` and `public/worklets/pcm-processor.js`.
  **Done when:**
  - `npm run typecheck`, `cd frontend && npm run lint` and
    `npx prettier --check` on both files pass.
  - `cd frontend && npm run build` passes.
  - Reading the diff shows that a drained queue schedules at
    `now + PLAYBACK_LEAD_S`, a non-drained queue is unchanged, and the worklet
    posts only once a batch reaches 1200 samples.

## Verify

Manual, because the glitch is audible and can't be checked by a tool. Run
`npm run dev:sh:all` and open the voice modal:
- **Replies play smoothly.** Ask a question that gets a long answer. It should
  play without the earlier crackles or gaps.
- **Barge-in still works.** Talk over a reply and it stops promptly.
- **Response delay is acceptable.** The only added latency should be about
  150 ms before the agent starts speaking.
- **Transcription is unaffected.** Your words still appear in the transcript
  normally with the batched mic audio.

If the glitch persists with headphones on, the cause is not playback. In that
case go back to `/debug` and look at false interrupts.


<!-- blueprint:completion {"schemaVersion":1,"specBytes":3702,"specSha256":"8d7d6c40ed760f6a7c9deb6a3b7aca1662196244203f758c0eef485137ed3f28","branch":"refs/heads/fix/voice-reply-audio-underruns","head":"1f430703c73aa2eddca4b4d2613add30e96e7b6c","baseRef":"refs/heads/master","baseCommit":"1f430703c73aa2eddca4b4d2613add30e96e7b6c","sourceTree":"a7b6616288a0b8b3d1828d0c0f8bcc9e4a0b3e9b","absentOptional":[]} -->

## Completion note

Automated checks passed: typecheck, lint, prettier on both files, and build. A worklet simulation posted 20 batches of 1200 samples per second at 48 kHz and 19 at 44.1 kHz. The audible result was **not** listening-tested before merge; if the glitch persists, debug false interruptions next.
