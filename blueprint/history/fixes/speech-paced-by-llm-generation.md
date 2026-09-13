# Fix: Speech paced by LLM generation, not by prosody

**Type:** Fix
**Status:** verified
**Branch:** `fix/speech-paced-by-llm-generation`

## The problem

The agent's spoken audio pauses unnaturally at sentence boundaries. The pauses
track how fast the LLM is generating text rather than how the sentence should
sound, so a slow token burst becomes an audible mid-answer gap that reads as a
glitch. The voice itself is fine; only the timing is wrong.

The cause is in `backend/livekit_worker.py`:

- `_sanitize_stream` (lines ~181-205) buffers the LLM token stream and refuses
  to emit anything until it sees a `[.!?]\s` sentence boundary. It was written
  that way so a URL split across chunks could still be matched by the
  `guardrails` regex.
- `VoiceAgent.tts_node` feeds that buffered generator to
  `Agent.default.tts_node`.
- Deepgram `TTSv2` declares `TTSCapabilities(streaming=True)`
  (`livekit/plugins/deepgram/tts_v2.py:111`) and runs its own
  `basic.WordTokenizer` over incoming text (line 121), streaming words to
  Deepgram's socket as they arrive. Because it is already streaming, the SDK's
  default `tts_node` does **not** wrap it in `StreamAdapter`
  (`livekit/agents/voice/agent.py:564`) — correctly so, since TTSv2 does its
  own streaming.

So the only buffering in the pipeline is `_sanitize_stream`'s, and it is keyed
to sentence punctuation. Each sentence is withheld for its entire generation
time and then delivered in a single burst, starving a TTS that is built to
consume words continuously. The gap between bursts is LLM latency
played back as silence. The existing `LK_AUDIO_QUEUE_MS` playback buffer does
not help: it smooths *synthesis* running behind playback, not *text* arriving
late.

This is a separate defect from the earlier "slow audio generation" stutter and
from the prompt leak; both of those fixes stay as they are.

## The fix

Stop making prosody wait on punctuation, and give the TTS a proper pacer.

1. **Release text on a boundary the guardrail actually needs, not on sentence
   punctuation.** The only reason to buffer is so a URL is not split across
   chunks. A URL never contains whitespace, so holding back just the trailing
   partial token is sufficient: emit everything up to the last whitespace, keep
   the unterminated tail. Sentence punctuation stops being a gate, so words
   flow to Deepgram continuously and Deepgram's own word tokenizer paces the
   speech.
2. **Do not add `SentenceStreamPacer`.** Verified against the installed SDK
   while implementing: `SentenceStreamPacer` is only ever attached inside
   `StreamAdapter` (`tts/stream_adapter.py:91`), which drives a *non-streaming*
   TTS via `synthesize()` one sentence at a time. Deepgram `TTSv2` instead holds
   a persistent websocket and sends each word as its own `Speak` frame
   (`tts_v2.py:390-394`), synthesizing continuously. The pacer's job is to
   *withhold* text so it can batch it — exactly the behaviour causing these
   gaps. Adding it would make the symptom worse, and wrapping TTSv2 in
   `StreamAdapter` would bypass its websocket entirely. Step 1 alone restores
   continuous prosody by letting Deepgram's own word tokenizer pace the speech.

Must not break:

- **The chat transcript and popup text stay exactly as they are.** Only the TTS
  path's chunking changes. `transcription_node` keeps its own sanitizing pass
  and keeps emitting the visitor-facing text.
- **URL guardrails must still hold.** No fabricated link may reach either the
  spoken audio or the transcript. The whitespace-boundary rule must be proven to
  still catch a URL split across token chunks.
- **Markdown stripping stays** in the speech path only.
- Existing `_widen_playback_buffer`, `_widen_interruption_timeout`, the Flux STT
  turn-taking settings, and the fixed `session.say()` greeting are unrelated and
  stay untouched.

### Considered and rejected

| Option | Why not |
| --- | --- |
| Raise `LK_AUDIO_QUEUE_MS` further | Buffers audio, not text. The dead air is missing text, so a bigger audio queue just delays the same gap. |
| Turn on `preemptive_tts` | Explicitly disabled earlier for a good reason: it starts synthesis before the RAG round trip returns and causes the stutter this codebase already fixed. |
| Drop `_sanitize_stream` entirely | Fastest speech, but removes the URL guardrail from the spoken path. Not acceptable. |
| Add `SentenceStreamPacer` | Verified during implementation: it only attaches to non-streaming TTS and works by withholding text to batch it. Deepgram TTSv2 already streams word-by-word; the pacer would worsen the gaps. |
| Buffer whole paragraphs before speaking | Smooth prosody, but adds seconds of latency before the agent starts talking. |

## Build steps

**Step 1 - stream on word boundaries** — [x] done

- Rewrite `_sanitize_stream` to flush on the last whitespace rather than on
  `[.!?]\s`, retaining only the unterminated trailing token, and still flushing
  the remainder when the source ends.
- Keep `transcription_node` behaviour unchanged.
- Comment the change in the file's established style: state the measured symptom
  and why the boundary moved, so the next reader does not "restore" the sentence
  gate.

*Done when:* the worker starts clean, the agent speaks a multi-sentence answer
with no silent gap at sentence boundaries, and the popup transcript still shows
the same text it does today.

## Round 2 — measured findings after live testing

Live testing showed the first fix helped but did not remove the problem: tone
still shifts with generation speed, and the greeting stutters too. Worker logs
and direct measurement against Deepgram overturn the premise both the earlier
playback-buffer patch and Step 1 were built on.

### Evidence

- **The fixed greeting stutters.** At 07:36:45 the log shows ~20
  `flush audio emitter due to slow audio generation` lines while speaking
  `persona.GREETING` via `session.say()`. No LLM is involved in that text, so
  text arrival rate cannot be the cause.
- **Deepgram is faster than realtime, not slower.** Measured directly against
  `flux-brooke-en` at 24kHz:

  | Text feed pattern | Audio | Wall | Ratio | Max frame gap |
  | --- | --- | --- | --- | --- |
  | All words at once | 18.24s | 13.39s | **1.36x** | 0.19s |
  | Word every 50ms (fast LLM) | 17.36s | 11.62s | **1.49x** | 0.24s |
  | Word every 120ms (slow LLM) | 22.16s | 16.71s | **1.33x** | 0.24s |

  This contradicts the `_widen_playback_buffer` comment, which claims ~0.77x and
  is the entire justification for the 1000ms buffer.

- **The 1000ms buffer causes the flushes it was meant to prevent.**
  `RoomIO.capture_frame` awaits `AudioSource.capture_frame`
  (`voice/room_io/_output.py:98-107`), which blocks until the queue drains. At
  `queue_size_ms=1000` that backpressure stalls frame delivery. `AudioEmitter`'s
  flush timer (`tts/tts.py:1053-1058`) interprets the stall as slow synthesis
  and force-flushes mid-utterance, ending the Deepgram segment early. A
  segment boundary mid-sentence is heard as a tone/pacing break.

### The round 2 fix

Revert `_widen_playback_buffer` to the SDK's 200ms default. It was written
against a measurement that no longer holds, and at 1.3-1.5x synthesis the extra
cushion buys nothing while actively triggering mid-utterance flushes. Keep the
patch function and the `LK_AUDIO_QUEUE_MS` escape hatch so the value can be
raised again if a slower region ever needs it, but default it to 200.

Step 1 (word-boundary streaming) stays: it is independently correct and is what
lets Deepgram's own tokenizer pace the words.

### Not addressed here

The log also shows `transcript_delay` of 0.56s and 1.37s on user turns, and a
1.13s interruption detection delay — the "takes time before it is sent to the
agent" symptom. That is STT/turn-taking latency, a separate concern from TTS
pacing, and is scoped out of this fix rather than bundled in. It needs its own
`/fix` once this one is confirmed.

**Step 2 - restore the SDK default playback buffer** — REVERTED, see round 3

- Default `LK_AUDIO_QUEUE_MS` to 200 instead of 1000.
- Rewrite the comment block to record the measured 1.3-1.5x ratio and the
  backpressure mechanism, so the 1000ms value is not reintroduced.

*Done when:* the worker logs no `flush audio emitter due to slow audio
generation` lines during the greeting, and speech holds an even tone.

## Round 3 — round 2 reverted, STT turn-commit fixed

### Round 2 was wrong and is reverted

Testing at `queue_size_ms=200` produced the same `flush audio emitter due to
slow audio generation` lines as at 1000ms: same ~305ms cadence, same count
during the greeting. The buffer was not causing them, so the round 2 change
fixed nothing and is reverted to 1000ms.

The deeper error was method: those are DEBUG lines from the emitter's flush
timer arming and re-arming on a streaming TTS, and they were treated as proof
of a fault without ever being correlated against what the user actually hears.
The isolated measurement (1.33-1.49x realtime, 0.24s max frame gap) says the
TTS path is healthy. The comment block now records both the disproven 0.77x
claim and the negative 200ms result so neither is retried.

**The audible glitch is still unexplained.** It is not attributed to the TTS
path on current evidence, and no further change is made to that path on
speculation. Reproducing it needs wall-clock timestamps from the user at the
moment it occurs.

### The STT delay is understood and fixed

Distinct, real, and diagnosable from the logs:

| Turn | Speech start | Transcript | Delay |
| --- | --- | --- | --- |
| 1 | 07:49:59.6 | 07:50:09.7 | **5.88s** |
| 2 | 07:50:24.2 (4 bursts to 07:50:51) | 07:50:54.5 | **2.76s**, all bursts merged into one |
| 3 | — | — | 0.003s |

`eot_threshold` was 0.8 and `eot_timeout_ms` 4000, both above the SDK defaults
(0.7 / 3000, per `deepgram/stt_v2.py:88-90`). When speech did not clear the 0.8
confidence bar the turn never closed, and each new burst restarted the wait —
so a turn spoken in four bursts over ~30s emitted one merged transcript at the
end. That is the "text delays, then sends several requests at once" symptom.

Note: these values predate this fix; they were not introduced by rounds 1-2.

**Step 3 - restore documented EOT defaults** — [x] done

- `eot_threshold` 0.8 -> 0.7, `eot_timeout_ms` 4000 -> 3000.
- `eager_eot_threshold` stays 0.6 (SDK requires eager <= eot; 0.6 <= 0.7 holds,
  verified by constructing STTv2 with these values).

*Done when:* `transcript_delay` stays well under a second on normal turns, and
consecutive utterances commit as separate turns instead of merging.

## Round 4 — STT confirmed fixed, and the glitch is root-caused

### Round 3 verified

`transcript_delay` dropped to **0.85s** and **0.034s** (was 5.88s / 2.76s), with
no merged turns. The EOT change worked.

### The glitch: a spoken tool preamble, not TTS pacing

The log finally shows the mechanism. Around the `search_about_owner` call:

| Time | Event |
| --- | --- |
| 07:59:27.334 | `executing tool search_about_owner` |
| 07:59:28.153 | agent -> **speaking** |
| 07:59:31.991 | says *"I'll look up what Gichogu works on and what exactly he's done."* |
| 07:59:31.992 | speaking -> **thinking** (stops mid-turn) |
| 07:59:33.727 | thinking -> **speaking** (resumes after ~1.7s of silence) |
| 08:00:05.084 | delivers the real answer |

The agent speaks a filler preamble, halts, waits ~1.7s, then starts a second
utterance. Two separate TTS segments with a hard stop between them — heard as
an unnatural pause and a tone change at the resume. It tracks generation speed
because the gap is the tool round trip.

This was never a TTS problem, which is why three TTS-side changes did not fix
it. The measured 1.33-1.49x synthesis rate was accurate all along.

### Why the prompt does not stop it

`persona.py` already forbids this twice — line 129 ("Do not narrate what you are
about to do", naming "I'll check his background" almost verbatim) and line 220
("Never say 'let me check'"). The model ignores both. This is precisely the case
`guardrails.py` was written for: *"Prompt instructions are not a reliable
control surface for this model."* So enforce it in code, as with URLs.

**Step 4 - suppress spoken tool preambles** — [x] done

- Extend `core/guardrails.py` with a preamble matcher, applied through the
  existing `clean_output` path so speech and transcript stay consistent.
- Match only a leading announce-then-act sentence ("I'll look up...", "let me
  check...", "I'll search for..."). Anchored at the start and bounded to one
  sentence, so it cannot eat a real answer that happens to contain similar words.
- If the preamble is the entire message, the result is empty and no audio
  segment is produced — removing the stop/restart rather than relocating it.

*Done when:* a tool-backed question produces one continuous utterance, with no
speaking -> thinking -> speaking transition between a filler line and the answer.

Known limit: a reply that genuinely opens "I'll look into ..." is also stripped.
That is the announce-then-act shape the rule targets, and a real answer rarely
begins that way, so the matcher is left strict rather than weakened.

## Round 4 verified

Confirmed from the 08:05 session log.

| Check | Result |
| --- | --- |
| Tool preamble | **Gone.** At the 08:05:43 `search_about_owner` call the agent goes `thinking -> speaking` once (08:05:47) with no filler line and no speaking->thinking->speaking bounce. |
| STT delay | **Holding.** `transcript_delay` 0.457s and 0.440s. |
| Turn merging | None observed. |
| URL / control-token guardrails | Still firing normally (`Stripped model control token(s)`). |

User reports the voice is "definitely improved".

### Observed but deliberately NOT fixed here

These are visible in the same log and are separate concerns. Recording them so
they are not lost, and so the next person does not re-diagnose them from
scratch:

1. **LLM time-to-first-token, ~11.6s.** At 08:05:32.172 the agent enters
   `thinking`; the tool call is not issued until 08:05:43.788. The tool itself
   then takes 1.5s. That leading gap is Bedrock latency before the first token,
   not TTS and not retrieval. It is the largest remaining source of dead air.
   Worth its own `/fix` (model choice, prompt size, or a filler strategy that
   does not re-introduce the two-segment stutter).
2. **Interruption detection delay ~1.3s** (`detection_delay=1.306`,
   `probability=0.743`). The caller is cut in on later than ideal.
3. **`stt end of speech received while vad is still in a speech segment`**
   warnings persist. Flux EOT and Silero VAD disagree on boundaries. Harmless
   so far, but it is the seam where turn-taking bugs would appear.

None of these are regressions from this fix.

## Verify

0. **Round 3 focus:** confirm speech commits promptly — watch `transcript_delay`
   in the worker log; it should be well under a second, and two separate
   utterances should produce two transcripts, not one merged one.
1. Run `npm run dev:all`, open http://localhost:3000, start a voice session.
2. Ask something that produces a long multi-sentence answer (e.g. a RAG question
   about the owner's background). Listen specifically at sentence boundaries:
   speech should run continuously at a natural pace, with no pause that grows
   when the model is slow.
3. Confirm the chat panel and popup transcript still display the full answer
   text, unchanged from current behaviour.
4. Guardrail regression: ask a question that tempts a booking link. Confirm no
   invented URL is spoken **or** written, and that a legitimate allowlisted link
   from `get_booking_link` still comes through intact in the transcript.
5. Watch worker logs: no new `flush audio emitter due to slow audio generation`
   lines beyond what is already seen today.

---

## Archive annotation

- **Completed:** 2026-09-12
- **Type:** Fix
- **Branch:** `fix/speech-paced-by-llm-generation`
- **Original HEAD at archival:** `4b6d5082fd6d06d634eb170df9f6ccf27e967b00`
- **Local base:** `4b6d5082fd6d06d634eb170df9f6ccf27e967b00` (master)
- **Verified spec bytes:** 15850
- **Verified spec SHA-256:** `99ed9effd61a9163631f49a29477b6ed4ab2eacd9c2442bbf48fce40e9323a53`

### Files changed

| File | Change |
| --- | --- |
| `backend/livekit_worker.py` | `_sanitize_stream` flushes on last whitespace instead of sentence punctuation; EOT thresholds returned to SDK defaults (0.7 / 3000); playback-buffer comment rewritten to record measurements |
| `backend/core/guardrails.py` | Added `strip_tool_preamble`, wired into the existing `clean_output` chain |

### Checks run

- `npm run typecheck` — passed
- Guardrail regression, 7 checks — passed (text fidelity across chunk sizes 1/2/3/5/13; fabricated URL stripped in `https://` and bare-domain form including at end-of-stream; allowlisted URL preserved; markdown stripped; words emitted before sentence end)
- Tool-preamble matcher: 10 preamble variants stripped, 7 legitimate phrasings preserved
- `livekit_worker` + `core.guardrails` import cleanly under the project venv
- Live session confirmation at 08:05 (see Round 4 verified)

### Findings

_No findings were recorded against this fix._

### Independent review

_Not selected. `qualityGates.regular.independentReview` is `when-sensitive`; the user reviewed the sensitivity assessment during `/complete` and determined the change was not sensitive: `strip_unapproved_urls` and the host allowlist are unmodified and remain outermost in `clean_output`, and the URL guardrail was re-verified by the regression checks above._
