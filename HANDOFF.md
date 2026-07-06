# CHAOS MERCHANT - PROJECT HANDOFF DOCUMENT

**Current Date:** 2026-07-06
**Branch:** `claude/session-handoff-review-bawvji` (this session's designated branch; the prior session's `claude/github-abundant-aho-c2btu7` branch/main-sync claim could not be verified against `origin/main`, which is still at the repo's initial commit - see note below)
**Current model:** `claude-sonnet-5`
**Status:** First real-hardware run happened and produced broken output (1 MP4 instead of 7, ~7s unformatted video, no captions/effects/branding). Working through a 5-bug punch list from that run, one at a time, with a debrief + individual push after each fix. **All 5 bugs are now fixed.**
**Next Action:** the 5-bug punch list is complete. Next real milestone is another clean hardware run to confirm all 5 fixes actually resolve what was seen in production (see "Assets needed" and Bug 4's caveat below). After that, the two queued DIRECTION DECISIONS (format pivot, autonomous sourcing) are next, but only once the user explicitly asks to start scoping them.

**Branch/remote note:** `origin/main` and `claude/session-handoff-review-bawvji` are kept in sync throughout this session (fast-forward pushes after each bug). Bug 5 is committed on this branch and should be pushed to `main` the same way once reviewed.

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

**Bug 3 - Captions cut off at the bottom of the screen.**
Root cause was two layers deep. The obvious one: `render_captions()` hardcoded caption position to `video_clip.h - SAFE_MARGIN - 100` (a flat 160px from the bottom regardless of frame height), which overflows for taller/multi-line captions. The deeper one, found while tracing the pipeline per the spec: moviepy 2.x's `TextClip` renders via Pillow directly and, unlike moviepy 1.x's ImageMagick-backed version, has **no built-in default font** - a missing/invalid `font` path makes every `TextClip` construction raise. The previous code only passed `font` to `TextClip` when `CAPTION_FONT_PATH` was set in `.env`; on a machine without that env var, every single caption segment would silently fail (each exception logged individually via `logger.exception`, but with no aggregate signal) and the video would export fine, just with zero captions. This is almost certainly the deeper explanation for "no captions" in the original broad bug report, not just the position cutoff.
Fix:
1. Position: captions now anchor at **80% down from the top of the frame**, clamped so the caption's own rendered height never pushes its bottom edge closer than **80px** to the bottom edge.
2. Font: new `_resolve_font_path()` tries `CAPTION_FONT_PATH` first, then falls back through a real candidate list (DejaVu/Liberation on Linux - the same DejaVu path `BrandingOverlay`'s watermark code already assumes exists - then common macOS system font paths). If nothing is found, logs one loud, actionable error at construction time instead of the loop repeating the identical failure per segment.
3. Silent-failure fixes: `render_captions()` now distinctly logs "ALL segments failed" vs "N of M segments failed" instead of relying on per-segment exception logs alone to convey that.
4. Post-export verification: new `CaptionSynchronizer.verify_captions_in_export()` reopens the finished MP4 and samples frames at caption-active timestamps, checking for bright pixels inside the exact band captions were placed in (tracked via `self.last_caption_band`) - mirrors the "verify the artifact, don't trust the writer" pattern already used for `VideoExporter.export_mp4()`'s atomic-write fix. Wired into `produce_single_short()`: a short whose captions composited in-process but didn't survive to the actual export file now gets a clear error logged and is excluded from that short's `'captions'` applied-features entry.
Verified via a fake-object harness (moviepy/numpy/PIL stubbed enough to import the module; the sandbox's real DejaVu font was exercised through the actual fallback chain): font resolution across env-var-set/env-var-missing/nothing-found paths, `render_captions()` refusing to loop through every segment when no font resolved, y-position clamping across short/medium/very-tall captions (with a regression check proving the *old* formula could push a tall caption's bottom edge past the frame entirely), and `verify_captions_in_export()`'s band detection against synthetic bright/dark frames plus its empty-timeline and no-band short-circuits.
Change is in `agents/video_production.py` only (`CaptionSynchronizer` class and the caption step of `produce_single_short()`).

**Bug 4 - Video goes black and silent after 30 seconds despite the clip being longer.**
The bug report framed this as a clip-vs-voiceover duration reconciliation bug (video getting cut down to voiceover length). Tracing `AudioProcessor.prepare_audio()` found that reconciliation logic already did the right thing, even before this session's fixes: voiceover is trimmed when longer than the clip, never the reverse, and `CompositeAudioClip` is explicitly given the clip's own duration (not the voiceover's) via `.with_duration(clip_duration)`, so a short voiceover is followed by continued background music/silence rather than the track ending early. That logic predates Bug 1/2 and is **not** the mechanism behind the reported symptom.
The real mechanism is almost certainly upstream of audio entirely: a source video's duration metadata (what ffprobe/moviepy report) can overstate how much of the file is actually decodable - a known gotcha with some camera/screen-recording muxing where the container header claims more frames than the stream contains. Reading past the real content doesn't raise an exception; it silently returns black frames. The audio track, built correctly to the clip's full *claimed* duration, also has nothing real to play past that same point (there's no legitimate source content driving it either), so it goes silent at the same instant the video goes black - producing exactly "content, then black and silent for the remainder" even though every duration variable *downstream* is internally consistent. The input file itself was lying about its own length.
Fix:
1. New `ClipExtractor._detect_playable_duration()`: samples frames spread across the clip's claimed duration and looks for a trailing run of near-black frames. Deliberately requires the **last 3 samples** to all be black (not just the final one) before concluding there's an undecodable tail, so a single legitimately dark moment near the end of real footage (e.g. gaming footage at night) can't cause a false truncation. `extract_clip()` truncates to the last confirmed non-black sample when a genuine trailing gap is found, with a loud `logger.error`, instead of exporting a declared-but-undecodable tail.
2. Hardened the (already-correct) reconciliation in `produce_single_short()` with explicit assertions: right after `prepare_audio()`, and again after captions/color-grading/branding, if the audio or final video's duration doesn't match the clip's own duration, it's forced back via `.with_duration()` and logged as an error. This makes a future regression in that compositing chain structurally visible instead of silently shipping a truncated Short, even though nothing currently triggers it.
3. Added the requested detailed logging: clip duration, the voiceover's original (pre-trim) duration, and the final audio/video duration are now logged together at two points - right after audio prep and again immediately before export - so any mismatch is directly visible in the logs instead of needing to be pieced together from separate lines.
Verified via a fake-object harness (moviepy/numpy stubbed enough to import the module): no truncation when content is bright throughout, correct truncation on a genuine trailing black gap, no truncation when every sample is black (indistinguishable from a legitimately all-dark clip, so it doesn't guess), and no false truncation from a single dark blip near the end.
Change is in `agents/video_production.py` only (`ClipExtractor` and the audio-prep/pre-export logging in `produce_single_short()`).
**Caveat:** the black-frame-tail detector is a heuristic based on sampled frame brightness, not a certainty - it's the most plausible mechanism given the exact symptom described ("real content for ~30s then black and silent for the rest"), but it hasn't been confirmed against the actual source file from the original broken run (that file wasn't available in this environment). The new detailed duration logging will make it obvious on the next real hardware run whether this was the actual cause: if the logs show `clip`/`final_audio`/`final video` durations all matching and equal to the *original* clip duration (not truncated) and the exported file still goes black partway through, that would point to a decode issue the sampling heuristic didn't catch, rather than a duration-arithmetic bug - worth a follow-up look if so.

**Bug 5 - Output count: fewer Shorts produced than clips detected.**
Confirmed `clip_intelligence.py`'s clip detection/selection is not the culprit (`select_top_clips()` correctly returns all N detected segments when fewer than 7 exist - "found 3 clips" correctly produces a 3-long `top_clip_indices`). The loss happens entirely downstream, across three compounding issues:
1. **The big one:** `core/pipeline.py`'s Step 6 (Quality Control) handling raised an exception and aborted the ENTIRE pipeline run whenever `qc_result['status'] == 'error'` - which is the batch's *worst* per-clip result, not "everything is broken." If even 1 of 3 clips had any QC issue, **Step 7 (Output Packaging) never ran for any of the 3 clips** - the other two clips' videos existed on disk in `output_dir` from Step 4, but never got organized into the deliverable batch folder, which looks exactly like "fewer shorts than clips detected" (or zero, depending on what the user was counting). This directly contradicts CLAUDE.md's own documented QC design (route to a manual_review *queue*, implying packaged output that needs review - not "nothing gets packaged"). The error log line itself was also silently broken: it read `qc_result.get('errors')`, a key that never existed at that nesting level (the real errors are nested at `qc_result['qc_result']['issues']['errors']`), so it always logged `[]` regardless of what actually failed.
2. QC's content-similarity check only ever compared **one** title against channel history - `seo_manifest.get('best_title')`, which `pipeline.py` only ever populates from the *first successful clip's* SEO result. A title collision on clip 1 alone could flag the entire batch's uniqueness check while clips 2 and 3's genuinely distinct topics were never evaluated on their own merits at all - a real "QC failing for a fixable/wrong reason," exactly what was asked to be checked for.
3. QC's caption-presence detector hardcoded its frame-scan region to the **bottom 15%** of the frame - correct for the *old* caption position, but Bug 3 (this session) moved captions up to 80% down from the top with an 80px bottom margin, which can sit entirely above that old 15% band. Bug 3's fix had silently turned into a *new* QC false positive: genuinely-captioned videos reporting "no captions detected."

Fix:
1. `core/pipeline.py`: QC failures are now logged loudly (reading the real nested error path) and per-clip QC failure files are written, but the batch **always proceeds to packaging** - a batch with QC issues gets packaged with `routing=manual_review` instead of not existing at all.
2. `quality_control.py`: content similarity now runs once **per clip** against that clip's own `per_clip` SEO result, not the batch's first-successful-clip title.
3. `quality_control.py`: the caption-detection region now reads `CaptionSynchronizer.CAPTION_TOP_RATIO` directly (imported from `video_production.py`) instead of a second, independently-hardcoded guess, so the two can't silently drift apart again.
4. Throughout `video_production.py`'s `produce_single_short()`/`produce_all_shorts()`: every step now logs with an explicit `[Short N/M]` tag (previously ambiguous when multiple clips' logs interleaved in the same run), the hardcoded `/7` in per-short logs is now the real batch size, and **every failure - production or QC - now writes a dedicated, human-readable error file directly into the output folder** (`video_{stem}_{NNN}_ERROR.txt` for production failures, `video_{stem}_{NNN}_QC_ERROR.txt` for QC failures) stating the short number, clip index, failed step, and exact reason, instead of a clip just disappearing with the explanation buried in a log stream.
5. QC's per-video/per-caption/per-similarity results are now keyed by the **real** `short_number` (via `video_manifest['short_results']`) rather than a positional index that silently misattributes results to the wrong clip once any clip upstream has already failed production.
6. `output_packaging.py`'s similarity-check aggregation updated to summarize the new per-clip list (worst-result-wins, like the other per-video aggregations) instead of reading only the first entry.

On the "adjust thresholds vs. fix the underlying issue" question specifically: the caption-region and content-similarity-scope problems were fixed at the root (they were flat-out wrong, not just strict), not by loosening thresholds. `AUDIO_SYNC_TOLERANCE` (±0.3s) and duration bounds (15-45s) were reviewed and left alone - nothing found suggests they're miscalibrated; audio/video duration should already match to well under a frame's width given Bug 4's reconciliation work.
Verified via a fake-object harness: `VideoProducer._write_short_error_file` produces a correctly-formatted file with short number/clip index/step/reason; `quality_control.py` correctly imports and uses the live `CaptionSynchronizer.CAPTION_TOP_RATIO` constant; `Pipeline._write_qc_failure_files` writes one QC error file per genuinely-failing short (combining video + caption + similarity reasons) and none for a short that passed everything.
Change spans `agents/video_production.py`, `agents/quality_control.py`, `agents/output_packaging.py`, and `core/pipeline.py`.

### Assets needed before these can be tested for real

**`assets/music/` currently contains only a README - no actual audio files.** Bugs 1 and 2 cannot be meaningfully tested on real hardware until royalty-free music tracks are actually dropped into that folder (supported formats: `.mp3/.wav/.m4a/.aac/.ogg/.flac`). Without any tracks present, `BackgroundMusicLibrary.load_for_short()` degrades to `None` and the pipeline runs voiceover-only - which will falsely look like Bug 1 is "fixed" (no source audio, but also no music) without actually exercising the ducking/base-level logic in Bug 2 at all.

---

## BUGS STILL OUTSTANDING

None - all 5 bugs from the original punch list are fixed as of this update. See "Bugs fixed today" above for Bug 5's debrief (the most recently closed). Next step is a clean hardware run to confirm all 5 fixes actually resolve what was seen in production, not just in mocks/fake-object harnesses - see the caveats under Bug 4 and Bug 5 above for what specifically to watch for in that run's logs.

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
2. `git log --oneline -15` and `git status` to confirm exactly which fixes have landed, and on which branch/remote - see the "Branch/remote note" at the top; don't assume `main` is in sync without checking.
3. All 5 bugs are fixed. Once the user has real music files in `assets/music/`, the next real milestone is another clean hardware run to confirm Bugs 1-5 actually resolved what was seen in production, not just in mocks - pay particular attention to: Bug 4's new duration logging (its fix was a best-effort heuristic that couldn't be validated against the original broken source file - see its caveat above), and Bug 5's per-clip `*_ERROR.txt`/`*_QC_ERROR.txt` files (confirm they actually appear in `output_dir` for any clip that doesn't make it, and that a QC issue on one clip no longer prevents the others from being packaged).
4. The format-template pivot and autonomous clip-sourcing decisions are queued behind the bug list - don't start scoping either until the user explicitly asks for it.

---

## DOCUMENT META

**Document created:** 2026-07-02
**Last updated:** 2026-07-06, bugfix session complete (Bug 5, the last of the 5-bug punch list, fixed and committed)
**Status:** All 5 bugs from the real-hardware-run punch list are fixed. Next milestone: a clean hardware re-run to confirm the fixes hold outside fake-object test harnesses. Two direction decisions (format pivot, autonomous sourcing) recorded but not yet scoped or implemented.
