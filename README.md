# Chaos Merchant 🎮🎬

Autonomous 24/7 YouTube Shorts production system for gaming and internet culture content.

## Overview

Chaos Merchant takes a 10-minute raw video and produces 7 finished, monetization-ready YouTube Shorts in 40-50 minutes with zero manual intervention.

**Features:**
- 📹 Automatic clip intelligence and scene detection
- 🎙️ AI-powered script generation + Kokoro TTS voiceover
- 🎨 Canva MCP-powered thumbnail generation
- 📊 SEO optimization and metadata generation
- 🎬 Professional video production (ffmpeg)
- 📈 Analytics & feedback loop
- 🔍 Trend intelligence (Google Trends + Reddit + RSS)
- 🏆 Hook library for continuous optimization
- 🤖 Fully autonomous with graceful fallbacks

## Architecture

```
INPUT_FOLDER (raw video)
    ↓
WATCHER → CLIP_INTELLIGENCE → SCRIPT_VOICEOVER → SEO_OPTIMIZER 
    → VIDEO_PRODUCTION → THUMBNAIL → QUALITY_CONTROL → OUTPUT_PACKAGING
    ↓
OUTPUT_FOLDER (ready to upload)
```

**Parallel Intelligence Agents:**
- Analytics & Feedback (daily 9am)
- Trend Intelligence (daily 7am)
- Competitor Monitoring (every 3h)
- Comment Mining (weekly)
- Thumbnail Research (weekly)

## Quick Start

```bash
# Setup
./setup.sh

# Activate virtual environment
source venv/bin/activate

# Edit environment
nano .env

# Run
python main.py
```

## Configuration

Copy `.env.example` to `.env` and add your API keys:
- `ANTHROPIC_API_KEY`: Claude API key
- `YOUTUBE_API_KEY`: YouTube Data API key
- `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET`: Reddit API credentials
- `ELEVENLABS_API_KEY`: (Optional) For fallback premium voiceover

## Cost Estimate

**Monthly (MVP):** ~$2-5/month
- Kokoro TTS: Free
- Canva MCP: Free (included)
- Claude API: $2-5/month
- Google Trends API: Free
- YouTube Data API: Free tier

## Processing Time

Target: 40-50 minutes for 7 shorts from 10-minute source video

**Breakdown:**
- Clip analysis: 4-5 min
- Script generation: 2 min
- Voiceover generation (Kokoro): 2-3 min
- Caption alignment (Whisper): 8-10 min
- Video production (ffmpeg): 20-25 min
- Thumbnail generation (Canva): 2-3 min
- QC checks: 2-3 min

## Project Structure

```
chaos-merchant/
├── agents/          # Autonomous agent implementations
├── core/            # Pipeline, scheduler, publisher
├── prompts/         # Human-editable prompt templates
├── config/          # settings.py, API configs
├── tests/           # Test suite
├── data/            # SQLite database, logs
├── input/           # Raw video folder
├── output/          # Finished shorts
├── main.py          # Entry point
├── requirements.txt # Python dependencies
├── setup.sh         # Setup script
├── CLAUDE.md        # Developer guide
└── README.md        # This file
```

## Build Sequence (20 Steps)

**Phase 1: Foundation (Steps 1-5)**
1. ✅ Repo Scaffold
2. Watcher Agent
3. Clip Intelligence
4. Script + Voiceover (Kokoro TTS primary)
5. SEO Optimizer

**Phase 2: Production (Steps 6-9)**
6. Video Production
7. Thumbnail Generation (Canva MCP)
8. Quality Control
9. Output Packaging

**Phase 3: Intelligence (Steps 10-15)**
10. Core Pipeline Integration
11. Analytics & Feedback
12. Trend Intelligence
13. Competitor Monitoring
14. Comment Mining
15. Hook Library + Channel Memory

**Phase 4: Orchestration (Steps 16-18)**
16. Scheduler
17. Dashboard (Flask UI)
18. Publisher Module

**Phase 5: Deployment (Steps 19-20)**
19. Docker
20. Documentation

## Technology Stack

| Component | Technology |
|-----------|-----------|
| **LLM** | Claude API (Haiku + Sonnet) |
| **Voiceover** | Kokoro TTS (primary) |
| **Thumbnails** | Canva MCP connector |
| **Video** | ffmpeg + moviepy |
| **Captions** | Whisper (OpenAI) |
| **Scene Detection** | OpenCV |
| **Audio Analysis** | librosa |
| **Trends** | Google Trends API + PRAW + RSS |
| **Database** | SQLite |
| **UI** | Flask |
| **Scheduling** | Python schedule library |

## Decisions

- ✅ No GPU requirement (Intel i3 compatible)
- ✅ Kokoro TTS primary (free alternative to ElevenLabs)
- ✅ Canva MCP for thumbnails (replaces Ideogram, free)
- ✅ Hybrid testing approach (test both voices in Step 4)
- ✅ Google Trends + PRAW + RSS (no TikTok API cost)
- ✅ 40-50 min processing time target
- ✅ Graceful degradation & fallbacks throughout

## Resources

- [Original Plan](/root/.claude/plans/i-have-a-plan-toasty-bunny.md)
- [Claude API Docs](https://api.anthropic.com/docs)
- [YouTube Data API](https://developers.google.com/youtube/v3)
- [Kokoro TTS](https://github.com/hexgrad/kokoro)

## Status

**Phase 1 Status:** ✅ Step 1 (Repo Scaffold) Complete
**Next:** Step 2 (Watcher Agent)

---

Made with 🤖 by Claude Code
