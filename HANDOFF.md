# CHAOS MERCHANT - PROJECT HANDOFF DOCUMENT

**Current Date:** 2026-07-03
**Branch:** `claude/github-abundant-aho-c2btu7` (this session's designated branch - see git log for the full commit sequence)
**Status:** Full pipeline + intelligence layer + dashboard + publisher + Docker built. Every fix this session verified against mocked dependencies (no network access to real `moviepy`/`ffmpeg`/`anthropic`/etc. in this dev sandbox). **No clean end-to-end hardware run has happened since these fixes landed.**
**Next Action:** Run the pipeline end-to-end on real hardware and observe what actually happens - see "NEXT STEPS" below.

---

## EXECUTIVE SUMMARY

### What happened this session (post-first-run hardening)

The pipeline's **first real-hardware run** happened today and produced broken output: 1 MP4 instead of 7, a ~7-second unformatted video, no captions/effects/branding, and a loose file instead of an organized batch folder. No logs were available from that run (different machine), so root causes were diagnosed via code trace, not log inspection. Everything found was fixed and verified against hand-built fakes matching each library's documented API shape - **not** against the real libraries, which still can't be installed in this dev sandbox (no network access to pip).

Work proceeded in six categories, each committed and pushed separately, each with its own debrief:

1. **Critical bugs** - the actual root causes of last night's broken output, plus a `quality_control.py` moviepy 1.x import that broke QC entirely on `main` before this session started.
2. **Setup/requirements automation** - `setup.sh` now auto-downloads Kokoro's model files (with corruption detection), attempts to auto-patch ImageMagick's caption-blocking policy, and `main.py` pre-flight-checks all of this before starting.
3. **Incomplete implementations** - wired real `pytrends-modern` into Trend Intelligence, removed all placeholder/mock seed data from Competitor Monitor, and - the deepest change - made script/voiceover/SEO generation genuinely **per-clip** instead of one shared pass reused across all 7 shorts. Wired the previously-dead Hook Library logging into the pipeline.
4. **Three new intelligence agents** - Analytics & Feedback, Comment Mining, Thumbnail Research - all built to degrade cleanly to "no data yet" on a fresh channel (explicit requirement, since this channel has zero posted videos).
5. **Dashboard + Publisher** - a complete Flask dashboard (7 pages, in-browser `.env`/prompt-file editing) and a Publisher module for YouTube/TikTok/Instagram auto-upload, all three platforms off by default. Found and fixed two prerequisites along the way: `ChannelMemory.add_short()` was never actually called anywhere, and there was no Claude API cost tracking at all.
6. **Documentation + Docker** (this category) - rewrote README/HANDOFF, created KNOWN_ISSUES.md, built Dockerfile + docker-compose.yml.

**Full bug-by-bug detail is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md) - this document is current state and next steps, not a changelog.**

### The one thing to internalize before touching this project again

Every single fix and every new feature this session was verified by exercising the affected code against realistic hand-built fakes (fake moviepy clips, fake Anthropic/YouTube/TikTok/Instagram API responses, a minimal fake `PIL.Image`, etc.) - because this dev sandbox has no network access to install `moviepy`, `ffmpeg`, `anthropic`, `kokoro-onnx`, `googleapiclient`, `yt-dlp`, `Pillow`, or `Flask`/`Werkzeug` for real. That verification method is real and was applied rigorously (see each category's commit message for exactly what was tested), but it is **not the same as a real hardware run.** Nothing in this document should be read as "confirmed working" beyond "confirmed logically correct against a faithful mock of the real API."

---

## CURRENT ARCHITECTURE

```
core/
  pipeline.py       Steps 1-7 orchestrator, checkpoint/recovery, batch_id generation
  memory.py         Hook Library + Channel Memory (SQLite, WAL mode)
  scheduler.py       QuotaTracker / JobTracker / ChaosScheduler
  recovery.py        Checkpoint listing/cleanup
  publisher.py        YouTube/TikTok/Instagram auto-upload (all off by default)
  cost_tracker.py      Real Claude API spend tracking (data/cost_log.json)
  notifications.py      Desktop notifications (macOS/Linux, used by spike detection)
  quality_test.py        Kokoro vs ElevenLabs comparison utility

agents/  (Steps 1-7 = production pipeline, called by pipeline.py)
  watcher.py                 file system monitoring
  clip_intelligence.py       Step 1: scene detection + engagement scoring
  script_voiceover.py        Step 2: PER-CLIP script gen (Claude) + voiceover (Kokoro/ElevenLabs)
  seo_optimizer.py           Step 3: PER-CLIP SEO metadata
  video_production.py        Step 4: ffmpeg/moviepy assembly, captions/ducking/grading/branding
  thumbnail.py                Step 5: PER-CLIP Canva MCP or brief-only
  quality_control.py           Step 6: validation + pass/warning/manual_review routing
  output_packaging.py           Step 7: batch folder assembly

agents/  (scheduled intelligence agents, registered in main.py)
  trend_intelligence.py       daily 7am
  competitor_monitor.py       every 3h
  analytics_feedback.py       daily 9am
  comment_mining.py           weekly Sunday 10am
  thumbnail_research.py       weekly Sunday 10am

dashboard/    Flask app (dashboard/app.py) - run separately: python dashboard/app.py
config/       competitors.json, gaming_calendar.json (both auto-created empty, user-maintained)
prompts/      script_generation.txt, seo_optimization.txt, thumbnail_prompt.txt (auto-updated),
              vocabulary_reference.txt (auto-updated)
```

### Data flow (per source video)

```
INPUT: source_video.mp4
  ↓
[Clip Intelligence] → clip_manifest.json: top_clip_indices (up to 7), per-clip engagement/audio scores
  ↓
[Script + Voiceover] → ONE call per clip index: script_voiceover_results[i] = {script, voiceover audio path}
  ↓
[SEO Optimizer] → ONE call per clip index, using that clip's own script: seo_results[i]
  ↓
[Video Production] → produces up to 7 MP4s, each using ITS OWN clip's script_voiceover_results[i] for
                      captions/audio. short_results[] maps short_number -> clip_idx -> output_path
                      (NOT positionally reliable once any short fails - use short_results, not index)
  ↓
[Thumbnail] → ONE call per clip index, using that clip's own SEO + script: thumbnails[i]
  ↓
[Quality Control] → validates all produced videos + metadata completeness, routes pass/warning/manual_review
  ↓
[Output Packaging] → output/batch_<id>/{shorts,thumbnails,upload_metadata,manifests}/, README.md

Also, right after Video Production and Thumbnail complete:
  Pipeline._log_hook_usage()     → logs each produced short's hook to Hook Library (placeholder, pre-performance)
  Pipeline._log_channel_memory() → adds a channel_shorts row per produced short (title/topic/hook/thumbnail/caption style)
```

---

## WHAT'S REAL VS. WHAT'S SCAFFOLDING

| Area | State |
|---|---|
| Steps 1-7 (production pipeline) | Real, per-clip, fail-loud on genuine failures. **Never run against real moviepy/ffmpeg/Kokoro in this session's sandbox** |
| Trend Intelligence | Real Reddit (PRAW) + RSS + Google Trends (`pytrends-modern`, unofficial); hardcoded fallback list only if all real sources fail |
| Competitor Monitor | Real YouTube Data API; starts with an empty competitor list, no mock seed data |
| Hook Library / Channel Memory | Real SQLite, both tables now actually get written to during normal pipeline operation |
| Analytics & Feedback | Real YouTube Data API (public stats) + optional real YouTube Analytics API (OAuth, private metrics). Degrades cleanly with zero published shorts - **genuinely untested against a real published video**, since none exist yet |
| Comment Mining | Real YouTube comment pulls (own + competitor), real Claude sentiment analysis. Same "no data yet" caveat |
| Thumbnail Research | Real yt-dlp trending scrape + Pillow analysis. Same caveat |
| Dashboard | Real Flask app reading real files/SQLite. **Flask itself was never actually run** in this dev sandbox (not installable) - verified via raw Jinja2 template rendering + static route cross-checks instead |
| Publisher - YouTube | Real resumable upload code, built on a stable/unchanged API and this project's existing OAuth pattern. Never actually authorized or uploaded a real video |
| Publisher - TikTok/Instagram | Real request-shape code per each platform's documented API. **Never exercised against a live endpoint** - no approved TikTok app, no live Instagram token available |
| Docker | Dockerfile + docker-compose.yml built this session, **never actually built/run** (no Docker daemon in this sandbox) |

---

## NEXT STEPS

In order:

1. **Run the pipeline end-to-end on real hardware.** This is the single highest-value next action - nothing else in this list matters until this happens once, cleanly, with logs captured. Follow the Quick Start in README.md. Capture `logs/chaos_merchant.log` and every `output/*_manifest.json` regardless of outcome.
2. **If it fails:** check [KNOWN_ISSUES.md](KNOWN_ISSUES.md) first - many likely failure modes (ImageMagick policy, Kokoro model files, moviepy API drift) are already documented with fixes. If it's a genuinely new failure, add it to KNOWN_ISSUES.md with the same format (root cause, fix, status) rather than just patching silently.
3. **If it succeeds:** verify the batch folder actually has 7 shorts, each with real burned-in captions and distinct titles/scripts (not the same content 7 times - this was the deepest bug fixed this session, worth specifically checking it stuck).
4. **Try the dashboard**: `python dashboard/app.py`, confirm all 7 pages load against real (not fake) data, confirm the Settings page's `.env`/prompt-file editing round-trips correctly.
5. **Only after a clean hardware run:** consider enabling `AUTO_POST_YOUTUBE` for a real test upload (small/private video first), or building out Docker verification (`docker-compose up` should require zero manual setup - confirm that's actually true).

### Useful commands

```bash
# Check databases
sqlite3 data/chaos_merchant.db "SELECT * FROM hooks;"
sqlite3 data/chaos_merchant.db "SELECT * FROM channel_shorts;"
sqlite3 data/chaos_merchant.db "SELECT * FROM hook_usage_log ORDER BY used_at DESC LIMIT 10;"

# Check quota / job / cost state
cat data/quota_tracker.json
cat data/job_tracker.json
cat data/cost_log.json

# Check latest scheduled-agent output
cat data/trend_intelligence_latest.json
cat data/competitor_alerts_latest.json
cat data/ideas_backlog.json

# Force a fresh pipeline run for one video (clears its checkpoint)
rm -f data/checkpoints/*_checkpoint.json

# One-time OAuth setup
python -m agents.analytics_feedback setup   # YouTube Analytics (impressions/AVD/retention)
python -m core.publisher setup-youtube       # YouTube upload

# Manually trigger a scheduled agent
python -m agents.trend_intelligence
python -m agents.comment_mining
python -m agents.thumbnail_research

# Dashboard
python dashboard/app.py   # http://127.0.0.1:5050

# Docker (never actually run this session - verify it works)
docker-compose up
```

---

## HOW TO RESUME THIS PROJECT

1. Read this HANDOFF.md, then [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for full bug/limitation detail.
2. `git log --oneline -15` and `git status` to see exactly where things stand.
3. If a clean hardware run hasn't happened yet, that's the next action - see "NEXT STEPS" above.
4. If it has: update this document with what actually happened (success or new failures), and move KNOWN_ISSUES.md's "still unverified" items into either "fixed" or a newly-documented issue as appropriate.

---

## DOCUMENT META

**Document created:** 2026-07-02
**Last updated:** 2026-07-03, end of the post-first-run hardening session (Categories 1-6: critical bugs, setup automation, incomplete implementations, three new intelligence agents, dashboard + publisher, documentation + Docker)
**Status:** Feature-complete for the originally-scoped build; first clean end-to-end hardware run since this session's fixes is the next concrete action
