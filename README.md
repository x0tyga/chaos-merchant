# Chaos Merchant - Autonomous YouTube Shorts Production

**Status:** Full pipeline + intelligence layer + dashboard + publisher built and unit-verified. First real-hardware run happened and surfaced real bugs (see [KNOWN_ISSUES.md](KNOWN_ISSUES.md)); those are fixed, but **a clean end-to-end hardware run since the fixes has not yet happened.** Don't take "it should work now" as "it's been proven to work."

**Cost:** ~$2-5/month (Claude Haiku for nearly everything, Kokoro TTS free/local, Google Trends free)

**Processing:** ~40-50 min per source video (7 Shorts from one ~10-minute input video) - a target, not yet measured on real hardware

Chaos Merchant takes a raw gaming video and produces up to 7 finished YouTube Shorts - each with its own script, voiceover, captions, SEO metadata, and thumbnail - with zero manual intervention beyond dropping the video in a folder. A Flask dashboard lets you monitor runs and tune prompts without touching a terminal; an optional Publisher module can auto-upload to YouTube/TikTok/Instagram once you're ready to trust it.

## ⚡ Quick Start

```bash
git clone https://github.com/x0tyga/chaos-merchant.git && cd chaos-merchant
bash setup.sh          # installs deps, downloads Kokoro model files, patches ImageMagick policy
cp .env.example .env   # then edit .env: at minimum set ANTHROPIC_API_KEY and YOUTUBE_API_KEY
source venv/bin/activate

cp ~/your_gaming_video.mp4 ./input/
python main.py

# ~40-50 minutes later, open:
open output/batch_YYYYMMDD_HHMMSS/README.md
```

`setup.sh` checks for `ffmpeg`/ImageMagick, downloads Kokoro's model files via `curl`, and attempts to auto-patch ImageMagick's `policy.xml` if it would block caption rendering. It prints exactly what (if anything) still needs manual attention at the end. See [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for gotchas found so far.

## 🏗️ Architecture

```
VIDEO INPUT (watcher.py monitors INPUT_DIR)
    ↓
[1. Clip Intelligence] → scene detection (OpenCV) + engagement scoring (librosa), selects up to 7 clips
    ↓
[2. Script + Voiceover] → PER CLIP: Claude Haiku script gen + Kokoro TTS (ElevenLabs fallback)
    ↓
[3. SEO Optimizer] → PER CLIP: titles, description, hashtags, keywords, tags
    ↓
[4. Video Production] → reframe to 9:16, burned-in captions, music ducking, color grade, watermark, export
    ↓
[5. Thumbnail Generation] → PER CLIP: Canva MCP (active Claude Code session) or brief-only (autonomous run)
    ↓
[6. Quality Control] → codec/resolution/duration/audio-sync checks, caption detection, content similarity
    ↓
[7. Output Packaging] → batch_<id>/ folder: shorts/, thumbnails/, upload_metadata/, manifests/, README.md
    ↓
READY TO UPLOAD - manually, or via the Publisher module (off by default)

Scheduled in parallel (main.py + core/scheduler.py):
  Trend Intelligence (daily 7am) · Competitor Monitor (every 3h)
  Analytics & Feedback (daily 9am) · Comment Mining (weekly Sun 10am)
  Thumbnail Research (weekly Sun 10am)
```

Each of the up to 7 shorts gets its **own** script, voiceover, SEO metadata, and thumbnail brief - this was not always true (see [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for when/why it changed).

## 🚀 Features

**Production Pipeline (Steps 1-7):**
- Scene detection with engagement scoring; genuinely fewer than 7 clips is possible and expected for short/atypical source footage, not a bug
- Per-clip AI script generation (Claude Haiku) + Kokoro TTS voiceover (free, local; ElevenLabs fallback if configured)
- Reframing to 9:16, burned-in captions, music ducking, color grading, channel watermark - each tracked as actually-applied-or-not per short, not assumed
- Per-clip SEO metadata and thumbnail briefs - real Canva MCP images in an active Claude Code session, detailed manual-creation briefs otherwise
- Three-tier quality control (video file validation, metadata completeness, PASS/WARNING/manual_review routing)
- Upload-ready batch folder: 30-second README, upload checklist, per-short metadata JSON

**Intelligence Layer (scheduled agents):**
- **Hook Library** - tracks every hook used, prevents 7-day repetition, status progression new → testing → proven_winner/declining
- **Channel Memory** - tracks every produced short, detects series opportunities, prevents 14-day topic repeat, powers the content gap report
- **Trend Intelligence** - daily brief from Reddit (PRAW), RSS feeds, and Google Trends (via `pytrends-modern`, unofficial/best-effort), with a hardcoded-fallback safety net if all real sources are unavailable
- **Competitor Monitor** - every 3h, real YouTube Data API channel/video lookups, alerts on view spikes; starts with an empty competitor list, add channels via the dashboard or `python -m agents.competitor_monitor add @Channel`
- **Analytics & Feedback** - real YouTube performance pulls at 48h/7d marks, updates Hook Library with real CTR/retention, spike detection with desktop notifications, confidence-gated prompt auto-tuning
- **Comment Mining** - weekly sentiment/pattern analysis on your own + competitor comments, feeds an ideas backlog and vocabulary reference
- **Thumbnail Research** - weekly trending-Shorts-thumbnail scrape (yt-dlp) + color/composition analysis, cross-referenced against your own CTR once you have enough data

All intelligence agents are designed to degrade cleanly to "no data yet" on a fresh channel rather than crash - see each agent's own docstring for exactly how.

**Dashboard** (`dashboard/`, Flask): pipeline status/queue, output batches with real viral scores, analytics charts, trends/competitor/ideas feed, research findings, and a Settings page to edit `.env` and any prompt file **directly in the browser** - no terminal required for day-to-day tuning. See "Dashboard" below.

**Publisher** (`core/publisher.py`): optional auto-upload to YouTube, TikTok, and Instagram, each independently gated by an env flag that **defaults to off**. See "Publisher" below.

## 📊 Performance (targets, not yet measured on real hardware)

| Component | Target Time | Hardware |
|-----------|-------------|----------|
| Clip Intelligence | 4-5 min | CPU (OpenCV, librosa) |
| Script + Voiceover (Kokoro, x7) | 2-3 min | CPU (local TTS) |
| SEO Optimizer (x7) | ~1 min | Claude API |
| Video Production (x7) | 20-25 min | CPU (ffmpeg) |
| Thumbnails (x7) | 2-3 min | Canva MCP or brief |
| Quality Control | 1-2 min | Validation |
| Output Packaging | ~1 min | File organization |
| **TOTAL** | **40-50 min** | **Intel i3 CPU, target only** |

## 💰 Cost Breakdown

The dashboard's Analytics page shows real, measured spend (`core/cost_tracker.py` logs every Claude API call's actual token usage). Rough monthly estimate before you have real data:

- Kokoro TTS: $0 (free, local)
- Google Trends / Reddit / RSS: $0 (free tier)
- YouTube Data API: $0 (free tier, 10k quota/day)
- Claude API (mostly Haiku, 7x per-clip calls across script/SEO/thumbnail per video): ~$2-5/month at moderate volume
- Canva MCP: $0 (included with an active Claude Code session; brief-only otherwise)

## 🔧 Configuration

Copy `.env.example` to `.env` and fill in what you need - the example file documents every variable inline, including which are required vs. optional. Key ones:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
YOUTUBE_API_KEY=...

# Video
MIN_CLIP_DURATION=15
MAX_CLIP_DURATION=45
VIRAL_SCORE_THRESHOLD=3.0

# Optional voice fallback
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...

# Dashboard (127.0.0.1 by default - no built-in auth, don't expose this)
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=5050

# Publisher (all off by default)
AUTO_POST_YOUTUBE=false
AUTO_POST_TIKTOK=false
AUTO_POST_INSTAGRAM=false
```

## 🖥️ Dashboard

```bash
python dashboard/app.py
# open http://127.0.0.1:5050
```

Pages: **Home** (queue, checkpoints, scheduled job status, quota, cost, publisher state), **Output** (every batch with QC status and real logged viral scores), **Analytics** (Chart.js views/CTR/retention, top hooks, API cost by agent), **Trends** (today's brief, competitor alerts, ideas backlog, add-competitor-by-URL), **Research** (thumbnail research, comment insights, content gap report), **Settings** (edit `.env` and any `prompts/*.txt` file in the browser - saving `.env` backs up the previous version first), **Logs** (tails `logs/chaos_merchant.log`, auto-refreshing).

This is a single-user local tool with **no authentication**. Don't bind `DASHBOARD_HOST` to `0.0.0.0` on a shared network without putting your own auth in front of it - Settings can read and write `.env`, which holds your API keys.

## 📤 Publisher

`core/publisher.py` can auto-upload finished shorts to YouTube, TikTok, and Instagram. **All three are off by default** (`AUTO_POST_YOUTUBE`/`AUTO_POST_TIKTOK`/`AUTO_POST_INSTAGRAM=false`) - nothing is ever posted anywhere until you deliberately flip a flag.

- **YouTube**: resumable upload + thumbnail via the Data API v3. Needs a one-time OAuth authorization: `python -m core.publisher setup-youtube`.
- **TikTok**: Content Posting API direct-post. Needs an approved TikTok developer app (unaudited apps can only post privately) and a token obtained via TikTok's own web OAuth flow (not something this tool can do for you - see the module docstring).
- **Instagram**: Graph API two-step Reels publish. Needs a Meta Business app, an Instagram Professional account, and a **publicly reachable URL** for your finished videos (`PUBLIC_VIDEO_BASE_URL`) - the Graph API fetches from a URL, it doesn't accept a direct file upload.

YouTube's upload path uses a stable, long-unchanged API and this codebase's existing OAuth pattern. TikTok's and Instagram's request shapes are built to each platform's documented API but have not been exercised against live endpoints in this project yet - review current docs before enabling either for the first time.

## 🎯 Deployment Modes (thumbnails only)

**Active Claude Code session** (cloud/interactive): Canva MCP available, thumbnails generated as real images automatically.

**Autonomous run, no session** (e.g. `python main.py` on a home machine via cron): Canva MCP unavailable, falls back to a detailed brief + Canva prompt per short for manual creation. Everything else in the pipeline is identical either way.

## 📚 Documentation

- **README.md** (this file) - overview and quick reference
- **[CLAUDE.md](CLAUDE.md)** - codebase map: what every file does, key data structures, modification guide
- **[HANDOFF.md](HANDOFF.md)** - current project state, what changed recently, what to do next
- **[KNOWN_ISSUES.md](KNOWN_ISSUES.md)** - every issue found so far, with status
- **[TESTING_GUIDE.md](TESTING_GUIDE.md)** - pre-flight checklist and diagnostics

## 🧪 Testing

```bash
# Run the pipeline on a video
python main.py

# Run a single agent directly
python -m agents.trend_intelligence
python -m agents.comment_mining
python -m agents.thumbnail_research
python -m agents.analytics_feedback

# Inspect the database
sqlite3 data/chaos_merchant.db "SELECT * FROM hooks LIMIT 5;"
sqlite3 data/chaos_merchant.db "SELECT * FROM channel_shorts ORDER BY publish_date DESC LIMIT 5;"

# Check latest scheduled-agent output
cat data/trend_intelligence_latest.json
cat data/competitor_alerts_latest.json
```

See [TESTING_GUIDE.md](TESTING_GUIDE.md) for the full pre-flight checklist and failure diagnostics.

## 📁 Project Structure

```
chaos-merchant/
├── main.py                     # Entry point: pre-flight checks, watcher, scheduler
├── setup.sh                    # One-command setup (deps, Kokoro download, ImageMagick fix)
├── requirements.txt
├── .env.example                 # Every config variable, documented inline
├── Dockerfile / docker-compose.yml
│
├── core/
│   ├── pipeline.py              # Steps 1-7 orchestrator, checkpoint/recovery
│   ├── memory.py                 # Hook Library + Channel Memory (SQLite)
│   ├── scheduler.py              # Agent scheduling, quota management
│   ├── recovery.py               # Checkpoint listing/cleanup
│   ├── publisher.py              # YouTube/TikTok/Instagram auto-upload (off by default)
│   ├── cost_tracker.py           # Real Claude API spend tracking
│   ├── notifications.py          # Desktop notifications (spike alerts)
│   └── quality_test.py           # Kokoro vs ElevenLabs comparison
│
├── agents/
│   ├── watcher.py                     # File system monitoring
│   ├── clip_intelligence.py           # Scene detection + scoring (Step 1)
│   ├── script_voiceover.py            # Per-clip script + Kokoro/ElevenLabs TTS (Step 2)
│   ├── seo_optimizer.py               # Per-clip SEO metadata (Step 3)
│   ├── video_production.py            # ffmpeg/moviepy assembly (Step 4)
│   ├── thumbnail.py                   # Canva MCP / brief-only (Step 5)
│   ├── quality_control.py             # Validation + routing (Step 6)
│   ├── output_packaging.py            # Batch folder assembly (Step 7)
│   ├── trend_intelligence.py          # Daily trend brief
│   ├── competitor_monitor.py          # Viral-spike alerts
│   ├── analytics_feedback.py          # Real performance tracking + hook scoring
│   ├── comment_mining.py              # Weekly comment sentiment/patterns
│   └── thumbnail_research.py          # Weekly trending-thumbnail research
│
├── dashboard/
│   ├── app.py                    # Flask routes
│   ├── data.py                   # Read-only data access layer
│   ├── templates/                # Home, Output, Analytics, Trends, Research, Settings, Logs
│   └── static/style.css
│
├── config/                       # competitors.json, gaming_calendar.json (auto-created)
├── prompts/                      # Human-editable Claude prompt templates
├── data/                         # SQLite DB, trackers, checkpoints, agent output (git-ignored)
├── analytics/                    # performance_log.csv (git-ignored)
├── logs/                         # chaos_merchant.log, rotated (git-ignored)
├── input/                        # Drop source videos here
└── output/                       # batch_<id>/ folders land here
```

## 🔄 Workflow

1. Drop a video in `input/` (or let `main.py`'s startup scan pick up anything already there).
2. `python main.py` - runs Steps 1-7 automatically once the watcher sees the file.
3. Open `output/batch_<id>/README.md` for the 30-second summary and upload checklist, or check the dashboard's Output page.
4. Upload manually, or enable the relevant `AUTO_POST_*` flag once you trust the Publisher module.
5. Scheduled intelligence agents run in the background per the schedule above - check the dashboard's Trends/Research pages, or `data/*_latest.json`.

## 🤔 FAQ

**Do I need a GPU?** No - CPU is fine, ffmpeg/Kokoro are CPU-oriented. Never measured on real hardware yet, so "acceptable" timing is a target.

**How much does it cost to run?** Check the dashboard's Analytics page for real measured spend. Rough estimate: $2-5/month in Claude API calls.

**What if a step fails?** The pipeline checkpoints after each step; rerun `python main.py` and it resumes from the last successful step for that video.

**Can I customize the output?** Yes - edit files under `prompts/` (directly in the dashboard's Settings page, or by hand) and `.env`. See [CLAUDE.md](CLAUDE.md) for the modification guide.

**How do I debug a failure?** Check `output/*_qc_manifest.json` for QC-specific failures, the dashboard's Logs page or `logs/chaos_merchant.log` for everything else, and [KNOWN_ISSUES.md](KNOWN_ISSUES.md) for issues already diagnosed.

## Technology Stack

| Component | Technology |
|-----------|-----------|
| LLM | Claude API (Haiku for per-clip generation) |
| Voiceover | Kokoro TTS (local, free), ElevenLabs (optional fallback) |
| Thumbnails | Canva MCP connector, or brief-only fallback |
| Video | ffmpeg + moviepy 2.x |
| Captions | Burned in from the generated script's own timing - no speech-to-text transcription involved |
| Scene Detection | OpenCV |
| Audio Analysis | librosa |
| Trends | Reddit (PRAW) + RSS + Google Trends (`pytrends-modern`, unofficial) |
| Database | SQLite (WAL mode) |
| Dashboard | Flask |
| Scheduling | `schedule` (Python library) |

---

**Maintainer:** Actively maintained. See [HANDOFF.md](HANDOFF.md) for current state and next steps.
