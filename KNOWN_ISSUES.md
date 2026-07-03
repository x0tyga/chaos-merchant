# Known Issues

Every issue found across this project's development, with current status. "Fixed" means the code was corrected and verified against mocked dependencies (this dev sandbox has no network access to install real `moviepy`/`ffmpeg`/`anthropic`/etc.) - **not** verified against a live end-to-end hardware run unless explicitly noted otherwise.

Last updated: 2026-07-03, after the post-first-run hardening session (Categories 1-6 below).

---

## From the first real-hardware test run

The pipeline's first run on actual hardware produced broken output: 1 MP4 instead of up to 7, a ~7-second unformatted video, no captions/effects/branding, and output dumped as a loose file instead of an organized batch folder. Root-caused via code trace (no logs were available from that run - different machine).

| Issue | Root Cause | Status |
|---|---|---|
| 1 video instead of 7 | Two independent causes: (a) `clip_intelligence.py` can legitimately return fewer than 7 segments for atypical/short source footage - not itself a bug; (b) `video_production.py`'s per-clip loop swallowed exceptions into a `status: 'error'` result with only `str(e)` logged, so 6 of 7 clips could fail silently with no pipeline-level error surfaced | **Fixed** - failures now logged with full tracebacks (`logger.exception`); `produce_all_shorts()`'s status is `error`/`partial`/`success` based on actual vs. expected count, not just "any video exists" |
| 7-second unformatted video | `quality_control.py` hardcoded `MIN_DURATION=15`/`MAX_DURATION=45` as Python constants instead of reading the same `MIN_CLIP_DURATION`/`MAX_CLIP_DURATION` env vars `clip_intelligence.py` uses - if those vars were ever overridden, QC and clip selection disagreed about what's valid | **Fixed** - both now read the same env vars, single source of truth |
| No captions/effects/branding | Captions/color-grading/branding were each wrapped in a broad `try/except` that silently no-op'd on any failure, and the returned `features` list was **hardcoded** to always claim all four applied regardless of what actually happened - the manifest could not be used to detect this | **Fixed** - each step's applied/not-applied state is now determined by identity comparison (did the clip object actually change), aggregated into real per-batch `features_applied_in_all_shorts`/`features_applied_in_any_short` lists |
| Wrong output folder structure | Not actually a bug in `output_packaging.py` - QC's duration-constant mismatch (above) tripped a hard FAIL on the 7s video, so the pipeline raised before Step 7 (Output Packaging) ever ran; the raw MP4 `video_production.py` writes straight to the output root (by design - packaging is what organizes it afterward) was all that was left behind | **Fixed as a consequence of the QC fix above** |
| Zoom punches, intro/outro cards | Confirmed via grep: these do not exist anywhere in the codebase | **Not a bug - never built.** Not on the current roadmap; flagging so it isn't mistaken for a regression |

## Bugs found auditing the moviepy 2.x migration (same session)

`agents/quality_control.py` still imported `from moviepy.editor import VideoFileClip` (moviepy 1.x API) after `video_production.py` had already been migrated to moviepy 2.x - QC was broken on `main` and would have failed before ever reaching the checks meant to catch the issues above.

| Issue | Status |
|---|---|
| QC's moviepy 1.x import | **Fixed** - `from moviepy import VideoFileClip` |
| `requirements.txt` still pinned `moviepy==1.0.3` | **Fixed** - pinned to `2.2.1`, matching what's actually required |
| QC only *warns* (doesn't error) when video count != 7 | **Confirmed intentional** - a legitimately-short source video producing fewer than 7 great clips isn't necessarily an error; user confirmed warning-only is correct |

## Setup / environment gotchas

| Issue | Status |
|---|---|
| Kokoro model files must be downloaded manually, no automated check for corrupt/partial downloads | **Fixed** - `setup.sh` downloads both files via `curl`, size-checks against a 1MB floor (a file that exists but is undersized means a corrupt/interrupted download or a 404 saved in place of the real binary) |
| ImageMagick's default security policy on many distros/Homebrew installs blocks the text/label/caption operations moviepy's `TextClip` needs, causing captions to fail with an opaque `PolicyError` | **Partially automated** - `setup.sh` detects and attempts to auto-patch `policy.xml` (requires `sudo`); prints manual fix instructions if that fails. **Never verified against a real ImageMagick install** in this sandbox |
| `main.py` didn't pre-flight-check for Kokoro model files, `ffmpeg`, or ImageMagick before starting the watcher/scheduler | **Fixed** - `verify_environment()` now checks all three, hard-blocking on `ffmpeg`/missing required env vars and warning loudly (with the exact fix) on Kokoro/ImageMagick issues |
| Google Trends has no stable official API | **Accepted, documented** - uses `pytrends-modern` (the actively-maintained fork; the original `pytrends` package hasn't been released since April 2023) as a best-effort source, with the existing PRAW/RSS fallback chain as a safety net if it fails |

## Incomplete implementations found and completed

| Gap | Status |
|---|---|
| Trend Intelligence's "gaming calendar" was unconditional hardcoded mock data, not just a fallback | **Fixed** - moved to user-editable `config/gaming_calendar.json`, auto-created empty with instructions; nothing can fetch event dates automatically, so this is honestly user-maintained, not fake |
| Competitor Monitor seeded `config/competitors.json` with placeholder `UC_example1`/`UC_example2` channel IDs on first run | **Fixed** - starts empty; add real competitors via `python -m agents.competitor_monitor add @Channel` or the dashboard's Trends page (both resolve a real channel ID via the Data API) |
| Script, voiceover, and SEO were generated **once per source video** and reused/cycled across all 7 output shorts - only the title varied | **Fixed** - each step now runs once per clip, using that clip's own engagement/audio data; each short has genuinely distinct script, voiceover audio, captions, and SEO metadata |
| Hook Library's `add_hook()`/`record_usage()` were fully built but called nowhere in the pipeline (dead code) | **Fixed** - `pipeline.py` logs every hook that made it into a produced short at production time (placeholder logging), and `agents/analytics_feedback.py` calls `record_usage()` with real YouTube performance data once it's available |
| `ChannelMemory.add_short()` was defined but never called anywhere - `channel_shorts` stayed permanently empty | **Fixed** - `pipeline.py` logs one row per confirmed-produced short; this is also what makes `ChannelMemory.mark_published()` (called by the Publisher module) able to find a row to link a real `youtube_id` to |
| `prompts/thumbnail_prompt.txt` (written by Thumbnail Research's weekly auto-updates) had no reader anywhere in the codebase | **Fixed** - `agents/thumbnail.py` now reads it (if present) and folds it into the brief-generation prompt |
| No persistent log file existed for the dashboard's Logs page to tail | **Fixed** - `main.py` now writes to `logs/chaos_merchant.log` via a `RotatingFileHandler` (10MB × 5 backups) in addition to stdout |
| No Claude API spend tracking existed - a dashboard "cost" widget would have been permanently $0.00 | **Fixed** - `core/cost_tracker.py` wired into all 7 real `.messages.create()` call sites across the codebase |

## Known limitations (accepted, not bugs)

| Limitation | Detail | Impact |
|---|---|---|
| Caption detection false positives | QC's frame analysis scans the bottom 15% of video for bright text on dark background; bright source-video UI elements (game menus, HUD) in that region can trigger false positives | Low - worst case, falsely flags a video for manual review; a human catches it there |
| Content similarity check inactive for ~14 days on a fresh channel | Requires channel history to compare against; a genuinely fresh channel has none yet | First batch(es) have no automated topic-repeat protection; acceptable for launch, real protection kicks in as `channel_shorts` accumulates |
| TikTok/Instagram publisher logic unverified against live endpoints | No approved TikTok developer app and no live Instagram Business token were available during development; both are built to each platform's documented API shape but only tested against hand-built fakes | Review current platform docs before ever setting `AUTO_POST_TIKTOK`/`AUTO_POST_INSTAGRAM=true` |
| Dashboard has no authentication | Deliberate scope decision for a single-user local tool | Don't bind `DASHBOARD_HOST=0.0.0.0` on a shared network without adding your own auth - Settings can read/write `.env` |
| Cost tracking is an estimate | `core/cost_tracker.py` computes cost from `response.usage` × a hardcoded per-model pricing table, not a billing API | Directionally accurate, not a substitute for checking your actual Anthropic invoice |

## Still unverified - needs a real end-to-end hardware run

Nothing in this project has network access to real `moviepy`/`ffmpeg`/`anthropic`/`kokoro-onnx`/`googleapiclient`/etc. in this dev sandbox. Every fix above was verified by exercising the affected code against hand-built fakes matching each library's documented API shape - not by running the real thing. Specifically still unverified:

- A clean pipeline run producing all 7 shorts with captions/ducking/color-grading/branding all actually applied, on real hardware, since the fixes in this session landed.
- Real Kokoro TTS timing and audio quality.
- Real ImageMagick caption rendering (with or without `setup.sh`'s policy auto-patch).
- Real Reddit/YouTube/Google Trends API responses (fetchers are wired correctly, but only exercised against mocked response shapes).
- Actual pipeline timing and memory footprint on the target hardware (Intel i3 Mac Mini).
- The dashboard actually running under real Flask/Werkzeug (Flask isn't installable in this dev sandbox either - verified via raw Jinja2 template rendering plus static route/endpoint cross-checks instead; see HANDOFF.md for detail).
- YouTube OAuth upload end-to-end with a real account and real video file.

**The next concrete action for this project is a clean, observed, end-to-end hardware run** - see HANDOFF.md's "Next Steps."
