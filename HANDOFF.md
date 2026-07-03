# CHAOS MERCHANT - PROJECT HANDOFF DOCUMENT

**Current Date:** 2026-07-03
**Branch:** `main` (single branch — feature branches are deleted after merge, all work happens directly on main)
**Status:** Production pipeline complete, all known bugs fixed, ready for first real-hardware test
**Next Action:** Run the pipeline end-to-end on real hardware for the first time (see "FIRST TEST RUN" below)

---

## EXECUTIVE SUMMARY

### What changed since the last handoff

Two audit passes happened after the original build:

1. **Haiku QA/QC audit** found the production pipeline (Steps 1-9) was fully implemented but the scheduler had no agents registered, Trend Intelligence and Competitor Monitor used hardcoded mock data, and two parameter bugs existed in `pipeline.py`. Haiku applied fixes for all of these.

2. **Sonnet fresh-eyes code quality audit** was requested specifically because Haiku's fixes turned out to be unreliable. That audit found **17 real bugs**, several of them severe enough that the pipeline had never successfully completed a run:
   - A malformed escaped-quote string in `script_voiceover.py` was a straight-up `SyntaxError` — the file could not even be imported, which crashed every pipeline run at Step 2.
   - A bare `logger.info()` call with no arguments in `quality_control.py` crashed with `TypeError` on every single QC run, which meant Step 6 failed unconditionally and routed every video to manual review.
   - Captions never rendered (wrong MoviePy keyword argument + invalid color format).
   - Audio ducking crashed on any clip with background audio (wrong import path), and even when it didn't crash, it silently discarded the ducked background and used plain voiceover only.
   - Haiku's own "real API wiring" fix for Trend Intelligence used `'praw' in locals()` to check package availability — a scoping bug that meant the real Reddit/RSS fetchers were never actually reachable, so the system was still 100% mock data despite claiming otherwise.
   - Upload metadata files (`upload_metadata/*.json` — the files the upload checklist tells you to copy verbatim into YouTube Studio) contained hardcoded `"Gaming Moment N"` placeholders instead of the real Claude-generated SEO titles/hashtags.
   - The README's Quality Report table was hardcoded to show all-PASS regardless of actual QC results.
   - Several more (full list below).

All 17 have been fixed. Each fix was individually verified by actually executing the affected code path against mocked dependencies (this dev environment has no network access to pip-install the real `moviepy`/`anthropic`/`praw`/etc. packages), not just inspected as a diff. **This is the first time the pipeline is expected to be able to complete a full run** — it has never done so before now.

### ⚠️ One known architectural gap (not fixed, flagged for future work)

**Script and SEO generation happen once per source video, not once per individual clip.** `script_voiceover.py` generates a single script/voiceover from the top-3 clips' context, and `seo_optimizer.py` generates a single set of `{description, hashtags, tags, keywords}` for that one script. But `video_production.py` then produces **7 separate output shorts** from 7 different clips.

Practical effect: all 7 shorts in a batch share the same voiceover audio, the same burned-in captions, and the same description/hashtags/tags/keywords. Only the **title** varies across the 7 shorts — `output_packaging.py` cycles through the 5 Claude-generated title candidates so titles aren't identical, but that's real data being reused across shorts, not per-clip personalization.

This was true before this session and is **not** one of the 17 bugs fixed — it's a deeper design decision that would require generating a script+SEO pass per clip instead of per video. Flagging it here so it doesn't get mistaken for "done" the next time this project is picked up. If you want each of the 7 shorts to have a genuinely unique script, voiceover, and SEO metadata, that's the next architectural change to make, not a bug fix.

---

## THE 17 FIXES (Sonnet audit, this session)

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `agents/script_voiceover.py` | Malformed escaped triple-quotes made the file a `SyntaxError` — blocked every pipeline run at Step 2 | Rebuilt the ElevenLabs fallback as real, working code (was dead/commented) |
| 2 | `agents/quality_control.py` | Bare `logger.info()` with no args raised `TypeError` on every QC run | Removed/fixed the call |
| 3 | `agents/video_production.py` | Captions never rendered: `TextClip(text=...)` isn't valid in MoviePy 1.0.3 (needs `txt=`); `CAPTION_COLOR` was an RGB tuple, not a valid color string | Fixed the kwarg and the color format |
| 4 | `agents/video_production.py` | `AudioProcessor.prepare_audio()` imported `concatenate_audioclips` from the wrong module (uncaught `ImportError` on any clip with background audio) and discarded the ducked background even on the surviving path | Rebuilt using `CompositeAudioClip` so ducked background is genuinely mixed with voiceover |
| 5 | `agents/output_packaging.py` | `upload_metadata/*.json` had hardcoded `"Gaming Moment N"` placeholders instead of real SEO data | Pulls real title/description/hashtags/tags/keywords from `seo_manifest`, cycles the 5 title candidates across shorts |
| 6 | `agents/output_packaging.py` | README Quality Report table was hardcoded to all-PASS regardless of actual QC results | Computed dynamically from real `qc_result`, including a "NOT auto-cleared for publish" banner when routing fails |
| 7 | `core/pipeline.py` | `trending_topics`/`channel_history` were hardcoded to `[]`, so Trend Intelligence and Competitor Monitor data never reached script/SEO generation | Loads real data from `data/trend_intelligence_latest.json` and `ChannelMemory` |
| 8 | `agents/trend_intelligence.py` | `get_trends()` checked `'praw' in locals()` / `'feedparser' in locals()` — always `False` regardless of whether the packages were installed, so the real fetchers were unreachable dead code | Replaced with module-level `PRAW_AVAILABLE`/`FEEDPARSER_AVAILABLE` flags |
| 9 | `agents/trend_intelligence.py`, `agents/competitor_monitor.py` | `logger.warning()` called inside import-time `except` blocks before `logger` was defined — `NameError` at import time if `praw`/`feedparser`/`googleapiclient` were missing | Moved `logger = logging.getLogger(__name__)` above the try/excepts |
| 10 | `core/quality_test.py` | Imported `VoiceoverComparison`, which only existed inside the broken commented block from bug #1 — `ImportError` on every import | Built a real `VoiceoverComparison` class that runs both TTS engines and returns the shape `quality_test.py` expects |
| 11 | `core/memory.py` | Hooks were inserted with `status='new'` and nothing ever transitioned them to `'testing'`/`'proven_winner'`, so `get_top_performers()` and `ensure_diversity()` always returned empty | Added real status-transition logic plus the `auto_retire()` method CLAUDE.md documented but which didn't exist |
| 12 | `agents/quality_control.py` | `ContentSimilarityValidator` scanned `./channel_memory/`, but `pipeline.py` actually writes SEO metadata to `./output/` — the dedup check could never find anything | Fixed the directory; also added `exclude_filename` handling so the current video's own just-written file isn't compared against itself (which would have made every check a guaranteed 100%-duplicate false positive) |
| 13 | `core/scheduler.py` | `get_status()` called `len()` on `schedule.idle_seconds` (a number, not a collection) — `TypeError` whenever called | Uses `len(schedule.jobs)` for a real pending-job count |
| 14 | `core/memory.py` | `detect_series_opportunities()`'s percentile threshold computed `COUNT(*)` against all rows but applied the resulting `OFFSET` to a filtered (`ctr > 0`) subset — silently fell back to a meaningless default whenever any shorts were unmeasured | Computes the percentile in Python against the same filtered set |
| 15 | `agents/video_production.py` | `processing_times.export_total` was hardcoded to `0` even though real per-short timings were tracked and discarded | Aggregated properly, plus `wall_clock_total` and a per-short breakdown |
| 16 | `agents/video_production.py` | Dead, never-called `volume_envelope()` helper left over from an incomplete refactor | Removed (resolved as a side effect of fix #4) |
| 17 | (registration/wiring, from the earlier Haiku pass, re-verified in this audit) | Scheduler had no agents registered | Confirmed fixed and working: `main.py` registers `trend_intelligence` (daily 7am, priority 10) and `competitor_monitor` (every 3h, priority 50) |

Full technical detail on each fix, including the verification method used, is in the session transcript. The short version: nothing here was "looks done, isn't done" — every fix was proven by actually running the affected code, not just read.

---

## COMPLETE IMPLEMENTATION STATUS BY FILE

### CORE PIPELINE

| File | Status | Notes |
|------|--------|-------|
| `main.py` | ✅ Real | Entry point, registers scheduler jobs, initializes watcher, coordinates pipeline |
| `core/pipeline.py` | ✅ Real | Steps 1-9 orchestrator, checkpoint/recovery, now loads real trend/channel data (fix #7) |
| `core/memory.py` | ✅ Real | Hook Library + Channel Memory, hook status transitions now functional (fix #11), percentile query fixed (fix #14) |
| `core/scheduler.py` | ✅ Real, connected | QuotaTracker/JobTracker/ChaosScheduler all real; agents registered in `main.py`; `get_status()` fixed (fix #13) |
| `core/recovery.py` | ✅ Real | Checkpoint system |
| `core/quality_test.py` | ✅ Real | Now actually importable (fix #10) |
| `core/utils.py` | ✅ Real | Small helper functions |

### PRODUCTION AGENTS (Steps 1-9)

| Agent | Status | Notes |
|-------|--------|-------|
| `agents/watcher.py` | ✅ Real | File monitoring |
| `agents/clip_intelligence.py` | ✅ Real | Scene detection (OpenCV), engagement scoring (librosa) — untouched this session |
| `agents/script_voiceover.py` | ✅ Real | **Syntax error fixed (#1)**. Kokoro primary, ElevenLabs real fallback (was dead code before) |
| `agents/seo_optimizer.py` | ✅ Real | Untouched this session. Generates one script/SEO pass per video — see architectural gap above |
| `agents/video_production.py` | ✅ Real | Captions fixed (#3), audio ducking fixed (#4), timing tracking fixed (#15), dead code removed (#16) |
| `agents/thumbnail.py` | ✅ Real | Canva MCP with brief-only fallback — untouched this session |
| `agents/quality_control.py` | ✅ Real | Crash fixed (#2), content similarity directory fixed (#12) |
| `agents/output_packaging.py` | ✅ Real | Upload metadata now real (#5), QC report now real (#6) |

### INTELLIGENCE AGENTS (Steps 12-13)

| Agent | Status | Notes |
|-------|--------|-------|
| `agents/trend_intelligence.py` | ✅ Real, with graceful fallback | Real Reddit (PRAW) + RSS fetching, wired correctly now (#8, #9). Falls back to a small hardcoded trend list only if `praw`/`feedparser` are genuinely uninstalled or Reddit credentials aren't configured |
| `agents/competitor_monitor.py` | ✅ Real, with graceful fallback | Real YouTube Data API channel/video lookups. Falls back to mock competitor data only if `googleapiclient` is missing or `YOUTUBE_API_KEY` isn't set |

**Note:** "real, with graceful fallback" means the code path is genuinely wired to call real APIs — it is not guaranteed to have been exercised against the *actual* Reddit/YouTube/Google APIs yet, since this dev sandbox has no network access. First real-hardware run is also the first time these real API calls will fire for real.

### CONFIGURATION & DOCUMENTATION

| File | Status | Notes |
|------|--------|-------|
| `.env.example` | ✅ | Template only, no real credentials |
| `config/competitors.json` | ✅ | Auto-generated template on first run |
| `prompts/*.txt` | ✅ | Complete |
| `README.md` | ⚠️ Not reviewed this session | May reference old mock-data behavior for Steps 12-13; worth a pass |
| `TESTING_GUIDE.md` | ⚠️ Not reviewed this session | Same caveat |
| `CLAUDE.md` | ⚠️ Not reviewed this session | Documents `auto_retire()` which now genuinely exists (fix #11) — otherwise should still be accurate |
| `requirements.txt` | ✅ | All dependencies pinned |
| `.gitignore` | ✅ | Verified — excludes `.env`, `data/chaos_merchant.db` (+ WAL/SHM sidecars), `data/backups/`, `data/job_tracker.json`, `data/quota_tracker.json`, `data/checkpoints/`, trend/competitor cache files, `input/*`, `output/*`, `*.log` |

### ❌ Not Started (unchanged)

- Step 10: Analytics & Feedback (YouTube performance tracking)
- Step 11: Channel Memory Updates (YouTube API feedback loop)
- Step 14: Comment Mining (sentiment analysis)
- Step 17: Dashboard (Flask UI)
- Step 18: Publisher Module (auto-upload to YouTube)
- Step 19: Docker containerization

---

## DATA FLOW (verified against actual code, not assumed)

```
INPUT: source_video.mp4
  ↓
[Step 1: Clip Intelligence] agents/clip_intelligence.py
  Output key: top_clip_indices (NOT "top_7_clip_indices" — that name only
  appears in old docs/examples, the real field is top_clip_indices)
  ↓
[Step 2: Script + Voiceover] agents/script_voiceover.py
  ONE script + ONE voiceover audio file generated for the whole batch
  (uses top-3 clips as context, see architectural gap above)
  Now receives real trending_topics + channel_history (fix #7)
  ↓
[Step 3: SEO Optimizer] agents/seo_optimizer.py
  ONE set of {titles: [5], description, hashtags, tags, keywords}
  for the whole batch, not per-clip
  ↓
[Step 4: Video Production] agents/video_production.py
  Produces 7 separate MP4s from the 7 top clips, each reusing the SAME
  voiceover/captions from Step 2. Captions now actually burn in (#3).
  Audio ducking now actually works (#4).
  ↓
[Step 5: Thumbnail] agents/thumbnail.py
  Canva MCP if available, brief-only fallback otherwise
  ↓
[Step 6: Quality Control] agents/quality_control.py
  4 validations: video files, captions, content similarity, metadata.
  No longer crashes unconditionally (#2). Content similarity now scans
  the right directory and excludes self-comparison (#12).
  ↓
[Step 7: Output Packaging] agents/output_packaging.py
  upload_metadata/*.json now has real SEO data (#5).
  README Quality Report now reflects real QC results (#6).
  Output: output/batch_TIMESTAMP/ folder, ready for manual upload
```

---

## PRODUCTION READINESS: FIRST REAL HARDWARE TEST

### What's now expected to actually work (previously blocked)

- **The pipeline can complete a full run.** Before this session, it could not — bug #1 alone made Step 2 crash on every attempt.
- **Quality Control can pass.** Before this session, it could not — bug #2 made every QC run fail unconditionally, routing every video to manual review regardless of quality.
- **Captions burn into video.** Before this session, they silently never rendered.
- **Audio ducking actually ducks.** Before this session, background music was always discarded.
- **Upload metadata has real titles/hashtags.** Before this session, every video would have been titled "Gaming Moment N".

### What's still unverified (this sandbox has no way to check)

- **Real MoviePy 1.0.3 behavior.** All fixes were verified against mocked MoviePy objects that faithfully mirror the documented API (e.g. `TextClip(txt=...)`, `CompositeAudioClip`), but the actual library has never run in this environment. In particular:
  - **MoviePy's `TextClip` typically depends on ImageMagick being installed system-wide** (the `convert` binary). On macOS, ImageMagick's default security policy sometimes blocks text rendering (`PolicyError: not authorized`). If captions fail on your first run, this is the first thing to check — you may need `brew install imagemagick` and/or edit its `policy.xml` to allow text operations.
  - moviepy needs `ffmpeg` on `PATH` — `brew install ffmpeg` if not already present.
- **Real Kokoro TTS behavior and timing.** `pip install kokoro-tts` has never actually been run against this code in this session.
- **Real Reddit/YouTube API responses.** The fetchers in `trend_intelligence.py`/`competitor_monitor.py` are wired correctly now, but have never received a real API response — only mocked ones matching the documented response shape.
- **Actual pipeline timing on Intel i3.** Target is 40-50 minutes total, 20-25 of which is video export. Completely unverified on real hardware.
- **Memory footprint.** Should stay under 12GB per the original design assumptions, but untested.

---

## FIRST TEST RUN — WHAT TO DO RIGHT NOW ON YOUR MAC MINI

### 1. Pull the latest code
```bash
cd ~/chaos-merchant   # or wherever you cloned it
git checkout main
git pull origin main
git log --oneline -3   # should show "Fix all 17 bugs from Sonnet code quality audit" near the top
```
(If you haven't cloned it yet: `git clone <repo-url> chaos-merchant && cd chaos-merchant`)

### 2. Install system dependencies (Homebrew)
```bash
brew install ffmpeg
brew install imagemagick   # needed for MoviePy TextClip (captions) — likely gotcha, see above
```

### 3. Set up Python environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install kokoro-tts   # not in requirements.txt, install separately per script_voiceover.py
```

### 4. Configure `.env`
```bash
cp .env.example .env
```
Edit `.env` and fill in:
- `ANTHROPIC_API_KEY` — **required**, pipeline won't start without it
- `YOUTUBE_API_KEY` — **required** by `main.py`'s environment check, also needed for real Competitor Monitor data
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` — optional; without these, Trend Intelligence falls back to a small hardcoded trend list instead of real Reddit data
- `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` — optional, only needed if Kokoro fails and you want the premium fallback

### 5. Check ImageMagick policy (macOS-specific gotcha)
If you hit a `PolicyError` related to text/label operations when captions try to render, find ImageMagick's `policy.xml` (commonly `/opt/homebrew/etc/ImageMagick-7/policy.xml` on Apple Silicon or `/usr/local/etc/ImageMagick-7/policy.xml` on Intel) and make sure there's no `<policy domain="path" rights="none" pattern="@*"/>` or similar rule blocking text rendering. This is a very common MoviePy-on-Mac issue unrelated to anything in this codebase.

### 6. Put a test video in place
```bash
mkdir -p input
# copy a real gaming video (10ish minutes, .mp4/.mov/.mkv etc.) into input/
```

### 7. Run it
```bash
python main.py
```
Watch the terminal output. It should progress through Steps 1-7 (Clip Intelligence → Script/Voiceover → SEO → Video Production → Thumbnail → Quality Control → Output Packaging). Video Production (Step 4) is the longest step — expect it to dominate the runtime.

### 8. If something breaks
- Note the exact step number and error message.
- Check `output/*_qc_manifest.json` if QC is involved.
- If it's a MoviePy/ImageMagick error specifically around `TextClip`, that's the ImageMagick policy issue from step 5 above — not a bug in this session's fixes (which were verified against mocked MoviePy internals that can't catch real ImageMagick/system config issues).
- If it's a Kokoro-related error, check that `pip install kokoro-tts` actually succeeded — `import kokoro` needs to work.

### 9. What success looks like
```bash
ls -la output/batch_*/shorts/           # should have 7 .mp4 files
ls -la output/batch_*/upload_metadata/  # should have 7 .json files with REAL titles (not "Gaming Moment N")
cat output/batch_*/README.md            # Quality Report table should show real PASS/FAIL, not all-hardcoded-PASS
```
Check that at least one video visually has burned-in captions and that the QC manifest doesn't show `routing: manual_review`.

---

## HOW TO RESUME THIS PROJECT

1. Read this HANDOFF.md.
2. `git log --oneline -10` and `git status` to see where things stand.
3. If the first hardware test (above) hasn't been run yet, that's the next action — nothing else should happen before it, since it's the first real signal on whether the 17 fixes actually hold up outside mocked conditions.
4. If the test has been run: update this document with what broke (if anything), and whether it was a real bug vs. an environment/setup issue (ImageMagick, ffmpeg, Kokoro install, etc.).
5. Only after a clean test run should Steps 10, 11, 14, 17, 18, 19 (not-started items) or the per-clip SEO architectural gap be considered.

### Useful commands
```bash
# Check databases
sqlite3 data/chaos_merchant.db "SELECT * FROM hooks;"
sqlite3 data/chaos_merchant.db "SELECT * FROM channel_shorts;"

# Check quota / job state
cat data/quota_tracker.json
cat data/job_tracker.json

# Check latest trend/competitor briefs
cat data/trend_intelligence_latest.json
cat data/competitor_alerts_latest.json

# Force a fresh pipeline run (clears checkpoint)
rm -f data/checkpoints/*_checkpoint.json
```

---

## KNOWN LIMITATIONS (still accurate)

1. **Caption frame-detection false positives.** QC's caption check scans the bottom 15% of frames for bright text on dark background; bright source-video UI elements (game menus, HUD) can trigger false positives. Unchanged from before, not addressed this session.
2. **Content similarity check is genuinely inactive for the first video processed**, and now correctly self-excludes so a video is never compared against its own SEO file (fix #12) — but real dedup value only kicks in once 2+ videos exist in `./output/` within a 14-day window.
3. **One script/SEO pass per video, not per clip** — see "Known architectural gap" at the top. This is the most significant remaining limitation.
4. **Steps 10, 11, 14, 17, 18, 19 are not started.**

---

## DOCUMENT META

**Document created:** 2026-07-02
**Last updated:** 2026-07-03 (after Sonnet 17-bug fix session, branch consolidation to `main`)
**Status:** Pipeline complete and bug-fixed; first real-hardware test is the next concrete action
**Branch:** `main` only — feature branches are deleted after merge going forward
