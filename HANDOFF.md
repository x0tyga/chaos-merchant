# CHAOS MERCHANT - PROJECT HANDOFF DOCUMENT

**Current Date:** 2026-07-06
**Branch:** `claude/github-abundant-aho-c2btu7` (kept in sync 1:1 with `main` - every fix this session pushed to both)
**Current model:** `claude-sonnet-5` (switched mid-session from `claude-fable-5`, which was used for Bugs 1 and 2)
**Status:** First real-hardware run happened and produced broken output (1 MP4 instead of 7, ~7s unformatted video, no captions/effects/branding). Working through a 5-bug punch list from that run, one at a time, with a debrief + individual push to `main` after each fix. Bugs 1 and 2 fixed and pushed. Bugs 3-5 still outstanding.
**Next Action:** Resume Bug 3 (captions cut off at bottom of screen) - see "BUGS STILL OUTSTANDING" below for the exact spec. Do not skip ahead to Bug 4/5 without going through Bug 3 first, per the user's explicit one-at-a-time process.

---

## EXECUTIVE SUMMARY

### Where this session picked up

A prior hardening session (see git history before today) fixed a long list of setup/scaffolding/incomplete-implementation issues and did a full documentation + Docker pass. Today's session started from a **real hardware run** - the first time this pipeline had ever executed against real moviepy/ffmpeg/Kokoro instead of mocks - and it broke in five distinct ways. The user gave an explicit bug list and an explicit process: fix one bug at a time, in order, full root-cause debrief after each, push to `main` individually so the user can pull and test between fixes. That process is still in effect.

### Bugs fixed today

**Bug 1 - Original source video audio bleeding through underneath voiceover/music.**
Root cause: `AudioProcessor.prepare_audio()` in `agents/video_production.py` was still building final audio using the source video clip's own audio track - there was no real background-music infrastructure anywhere in the codebase, so whatever the "music" layer was actually doing, the source audio was never actually excluded from the composite.
Fix: two-part structural strip, not a volume-based patch.
1. Extracted clips get `.without_audio()` called immediately after extraction in `produce_single_short()`, before any reframe/composite step - the source audio is severed at the earliest possible point, structurally, so no downstream code path can accidentally reintroduce it.
2. Added a new `BackgroundMusicLibrary` class that loads a real royalty-free track from `assets/music/` (rotating by short number, looping/trimming to the clip's duration), and `prepare_audio()` was rewritten to build final audio exclusively from `voiceover_audio` + this explicit `background_music` parameter - it no longer reads `video_clip.audio` at all.
Verified via audio-lineage fake objects (each fake audio carries an origin-tag set like `{'srcaudio'}`, `{'voiceover'}`, `{'music:track.mp3'}` propagated through every operation) proving the final composited audio's lineage never contains `'srcaudio'`, with and without background music present, end-to-end through `produce_single_short()`.

**Bug 2 - Music way louder than voiceover (prior -6dB ducking wasn't enough, and music played at full volume outside the voiceover window entirely).**
Root cause: two compounding issues - insufficient ducking depth, and no base-level attenuation at all when no voiceover was playing (gain 1.0 = full volume the rest of the time). There was also a real risk (per a prior audit) that a `volumex`-style lambda could silently fail against moviepy's actual render pipeline and never get caught.
Fix: replaced `apply_music_ducking()` entirely with `apply_music_envelope()` - a full gain envelope: **-12dB base** (music's own volume) outside the voiceover, **-18dB duck** during it, with 0.25s linear ramps between the two so there's no audible click. Configurable via `MUSIC_BASE_DB`/`MUSIC_DUCK_DB` env vars, with defensive parsing (a typo'd `.env` value degrades to defaults with a logged warning, never crashes).
Critically, this also closes the exact silent-failure risk the user named: a new `_verify_envelope_callback()` step invokes the *actual* render callback moviepy will run at render time, immediately after constructing it, with synthetic frames at known timestamps (mid-voiceover, before/after, ramp midpoints) - and checks the measured gain against the expected value. If verification fails, `apply_music_envelope()` returns the original un-enveloped audio with `applied=False` and a loud `logger.error`, rather than silently shipping a broken envelope. This makes "ducking silently not applied" structurally detectable going forward instead of only discoverable by ear.
Verified via direct measurement of the real render callback (scalar and moviepy's actual batch/array call shape, mono and stereo), env var overrides, and confirming the verifier itself correctly rejects both a no-op callback and a wrong-gain-level callback while accepting the real one.

Both fixes are in `agents/video_production.py` only. `.env.example` gained `BACKGROUND_MUSIC_DIR`, `MUSIC_BASE_DB`, `MUSIC_DUCK_DB`. A new `assets/music/README.md` documents the folder's usage.

### Assets needed before these can be tested for real

**`assets/music/` currently contains only a README - no actual audio files.** Bugs 1 and 2 cannot be meaningfully tested on real hardware until royalty-free music tracks are actually dropped into that folder (supported formats: `.mp3/.wav/.m4a/.aac/.ogg/.flac`). Without any tracks present, `BackgroundMusicLibrary.load_for_short()` degrades to `None` and the pipeline runs voiceover-only - which will falsely look like Bug 1 is "fixed" (no source audio, but also no music) without actually exercising the ducking/base-level logic in Bug 2 at all.

---

## BUGS STILL OUTSTANDING

Work resumes here, in this order, one at a time, with a debrief + individual push after each.

### Bug 3 - Captions cut off at the bottom of the screen (up next)

**Current spec (this supersedes the original bug list's "85% from top" - the user refined it when giving the go-ahead):** move caption position up so captions sit at **80% from the top of the frame**, with a **minimum 80px margin from the bottom edge**.

Also required in the same pass:
- Full trace of the caption pipeline in `agents/video_production.py`'s `CaptionSynchronizer` class, from text generation (`generate_caption_timeline()`) through burned-in frame rendering (`render_captions()`), to confirm captions are genuinely appearing in the exported MP4 - not just processed and silently dropped.
- Fix any conditions where captions fail silently and the video exports without them.
- Check that the caption font is actually available on macOS, and that ImageMagick's policy isn't blocking text rendering (a known moviepy/ImageMagick gotcha - `TextClip` shells out to ImageMagick's `convert`, which ships with a default security policy that blocks text/label operations on many Linux distros and can also bite on macOS installs).
- Add a post-export verification step that samples frames from the finished video and confirms caption pixels are actually present (mirrors the same "don't trust the writer, verify the artifact" pattern already used for `VideoExporter.export_mp4()`'s atomic-write fix).

**Investigation status:** just started, paused immediately by the user's "stop everything" interrupt for this HANDOFF.md update. Only code reading has happened so far - zero edits made. The exact line identified as the root of the current cutoff is in `render_captions()`:
```python
text_clip.with_position(('center', video_clip.h - self.SAFE_MARGIN - 100))
```
This hardcodes captions 160px up from the bottom (`SAFE_MARGIN=60` + a flat `100`), regardless of video height - it needs to become a calculation anchored at 80% of `video_clip.h` from the top, clamped so it never sits closer than 80px to the bottom edge. ImageMagick policy, macOS font availability, silent-failure paths, and post-export frame verification have not been investigated yet at all.

### Bug 4 - Video goes black and silent after 30 seconds despite the clip being longer

Root cause not yet investigated. Per the original bug report: there's a duration mismatch between the video clip and the voiceover - something in the pipeline is reconciling the two by cutting the video down to the voiceover's length instead of letting the video play its full duration with voiceover covering only its own generated portion. Needs tracing through wherever clip duration and voiceover duration currently get reconciled in `agents/video_production.py` (likely in `produce_single_short()` or `AudioProcessor`/`CompositeVideoClip` duration handling) and a fix so the video always plays its full intended duration.

### Bug 5 - Output count: fewer Shorts produced than clips detected

Root cause not yet investigated. Per the original bug report: the per-clip loop appears to complete, but individual clips may be failing silently without clear logging, so fewer than the expected number of Shorts come out the other end with no visible explanation. Needs detailed per-clip logging added (clip number, current step, pass/fail, and why on failure) and any silent-failure paths found and fixed, so every clip either produces a Short or produces a clear, explanatory error in the logs/manifest.

---

## DIRECTION DECISIONS (made today, not yet implemented in code)

These are decisions the user has made about where the project is headed next. Neither has any corresponding code in the repository yet - both are documented here as decided-but-not-yet-built direction, to be scoped and implemented in future sessions.

### Format pivot: away from emotion-based reaction scripts, toward format templates

Moving away from the current script-generation approach (emotion-based reaction scripts) toward **multiple format templates**, at minimum:
- News recap
- Hidden details
- Ranking
- Comparison

...selected via a new **format selector agent**. No design work has been done yet on how the selector chooses a format per clip, how each template's prompt differs from the current `prompts/script_generation.txt` approach, or how this interacts with the existing per-clip script generation (`agents/script_voiceover.py`). This will need its own scoping pass before implementation starts.

### Autonomous clip sourcing: yt-dlp-based auto-sourcing

Moving away from requiring manual video drops into the input folder, toward the system **finding and downloading its own source footage** using `yt-dlp` (already a dependency in this codebase, currently used only by `agents/thumbnail_research.py` for trending-thumbnail scraping) from:
- Reddit
- YouTube
- Twitter

No design work has been done yet on sourcing criteria (what makes a video worth pulling), rate limits/ToS considerations per platform, dedup against already-processed content, or where in the pipeline this slots in relative to `watcher.py`'s current file-system-monitoring role. This will also need its own scoping pass before implementation starts.

---

## HOW TO RESUME THIS PROJECT

1. Read this HANDOFF.md top to bottom - it reflects the exact current state as of the interrupt that triggered this update.
2. `git log --oneline -15` and `git status` to confirm exactly which fixes have landed on `main`.
3. If the user hasn't given the go-ahead for Bug 3 yet, don't start it - the standing process for this bug list is one bug at a time, debrief, individual push, then wait for explicit go-ahead.
4. If Bug 3 is already underway or done per git log, move to Bug 4, then Bug 5, in that order.
5. Once all 5 bugs are fixed and the user has real music files in `assets/music/`, the next real milestone is another clean hardware run to confirm Bugs 1-5 actually resolved what was seen in production, not just in mocks.
6. The format-template pivot and autonomous clip-sourcing decisions are queued behind the bug list - don't start scoping either until the user explicitly asks for it.

---

## DOCUMENT META

**Document created:** 2026-07-02
**Last updated:** 2026-07-06, mid-bugfix-session (Bugs 1 and 2 of a 5-bug punch list fixed and pushed; Bug 3 investigation paused on explicit user interrupt to update this document)
**Status:** Active bug-fixing session in progress. Bugs 1-2 fixed, Bugs 3-5 outstanding, two direction decisions (format pivot, autonomous sourcing) recorded but not yet scoped or implemented.
