# Chaos Merchant - Developer Guide

## Codebase Overview

This document describes the architecture, key components, and modification guide for Chaos Merchant.

## Architecture Layers

### 1. **Core Pipeline** (`core/pipeline.py`)
Main orchestration engine that:
- Monitors input folder for new videos
- Sequences agents 1-9 in order
- Implements checkpoint/recovery system
- Handles error routing and notifications

### 2. **Agents** (`agents/`)
12 autonomous agents, each handling a specific task:

**Production Pipeline:**
- `watcher.py` - File system monitoring
- `clip_intelligence.py` - Scene detection & scoring
- `script_voiceover.py` - Claude script gen + Kokoro TTS
- `seo_optimizer.py` - Metadata generation
- `video_production.py` - ffmpeg assembly
- `thumbnail.py` - Canva MCP brief + generation
- `quality_control.py` - Validation
- `output_packaging.py` - Asset assembly

**Intelligence Agents:**
- `analytics_feedback.py` - YouTube performance tracking
- `trend_intelligence.py` - Google Trends + PRAW + RSS
- `competitor_monitor.py` - Competitive tracking
- `comment_mining.py` - Sentiment analysis

### 3. **Core Utilities** (`core/`)
- `scheduler.py` - Task scheduling
- `publisher.py` - YouTube upload
- `memory.py` - SQLite databases (hooks, channel memory)
- `recovery.py` - Crash recovery & checkpoints

### 4. **Configuration** (`config/`)
- `settings.py` - Global settings
- `competitors.json` - Competitor tracking
- `.env` - API keys (git-ignored)

### 5. **Prompts** (`prompts/`)
Human-editable text files for:
- Script generation templates
- Hook library prompts
- Trend analysis prompts
- Metadata generation

## Key Data Structures

### Hook Library (SQLite)
Tracks every hook used in shorts:
```python
{
  'id': int,
  'text': str,           # e.g., "OMG THIS GLITCH..."
  'style': str,          # opening, transition, ending
  'usage_count': int,
  'ctr': float,          # Click-through rate
  'retention': float,    # Average retention
  'status': str,         # new, testing, proven_winner, declining
  'first_used': date,
  'last_used': date,
  'created_at': date
}
```

### Channel Memory (SQLite)
Tracks every short produced:
```python
{
  'id': int,
  'title': str,
  'topic': str,
  'summary': str,
  'youtube_url': str,
  'views': int,
  'ctr': float,
  'retention': float,
  'publish_date': date,
  'last_updated': date
}
```

### Clip Intelligence Output (JSON)
Per 10-minute source video:
```python
{
  'video_path': str,
  'duration': float,     # seconds
  'clips': [
    {
      'start': float,
      'end': float,
      'duration': float,
      'scene_change_confidence': float,
      'engagement_score': float,  # 0-1
      'audio_features': {
        'energy': float,
        'loudness': float,
        'speech_presence': float
      }
    }
  ],
  'top_7_clip_indices': [int],
  'generated_at': timestamp
}
```

## Critical Functions to Know

### `core/pipeline.py:run_pipeline(video_path)`
Entry point for processing a single video through all 9 agents.

### `agents/clip_intelligence.py:analyze_video(video_path)`
Returns JSON manifest with scene detection and scoring.

### `agents/script_voiceover.py:generate_voiceover(clips, script_brief)`
Generates voiceover using Kokoro TTS (primary) or ElevenLabs (fallback).
**NOTE:** Kokoro runs locally; ElevenLabs requires API key.

### `agents/thumbnail.py:generate_thumbnail_brief(clip_data)`
Generates detailed Canva prompt and brief. Returns:
```python
{
  'brief': str,          # Human-readable description
  'canva_prompt': str,   # Structured prompt for Canva MCP
  'fallback': str        # Brief-only mode if Canva unavailable
}
```

### `agents/thumbnail.py:create_with_canva_mcp(brief, prompt)`
Calls Canva MCP connector. Fails gracefully to brief-only mode.

### `core/memory.py:HookLibrary`
SQLite interface for hook tracking. Methods:
- `add_hook(text, style)` - New hook
- `record_usage(hook_id)` - Increment counter
- `get_top_performers()` - Proven winners
- `prevent_repetition(days=7)` - 7-day dedup
- `auto_retire(retention_threshold)` - Remove underperformers

### `core/memory.py:ChannelMemory`
SQLite interface for channel tracking. Methods:
- `add_short(title, topic, summary)` - New short
- `update_performance(youtube_id, views, ctr)` - YouTube stats
- `get_gap_report()` - Content gaps vs trends
- `prevent_topic_repeat(days=14)` - 14-day dedup

## Modification Guide

### Adding a New Trend Source (e.g., TikTok API in future)

1. **Create agent** `agents/trend_source_tiktok.py`:
```python
def fetch_tiktok_trends():
    # Fetch from TikTok API
    trends = [...]
    return {
        'source': 'tiktok',
        'trends': trends,
        'timestamp': now(),
        'confidence': 0.95
    }
```

2. **Integrate into Trend Intelligence** `agents/trend_intelligence.py`:
```python
# Add to daily 7am job
tiktok_trends = fetch_tiktok_trends()
all_trends.extend(tiktok_trends['trends'])
```

### Modifying Script Generation Prompt

1. Edit `prompts/script_generation.txt`
2. Variables available: `{clip_topic}`, `{trending_hooks}`, `{channel_memory}`
3. Test with small video in `tests/sample_video.mp4`
4. The agent automatically validates length and timing

### Adding a New LLM Model (e.g., Sonnet for specific task)

1. **Modify call in agent**:
```python
from anthropic import Anthropic

client = Anthropic()

# For cost-sensitive: Haiku
response = client.messages.create(
    model="claude-3-5-haiku-20241022",
    messages=[...],
    max_tokens=500
)

# For creative tasks: Sonnet
response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    messages=[...],
    max_tokens=2000
)
```

### Handling Kokoro TTS Failure Gracefully

The `script_voiceover.py` agent has built-in fallback:
```python
try:
    # Primary: Kokoro (free)
    audio = kokoro_tts(script)
except Exception as e:
    logger.warning(f"Kokoro failed: {e}")
    # Fallback: ElevenLabs
    if os.getenv('ELEVENLABS_API_KEY'):
        audio = elevenlabs_tts(script)
    else:
        raise  # Re-raise if no fallback available
```

### Canva MCP Thumbnail Generation Fallback

The `thumbnail.py` agent has two-tier fallback:

```python
# Tier 1: Try Canva MCP
try:
    thumbnail = canva_mcp.create_thumbnail(prompt)
    return {'image': thumbnail, 'source': 'canva_mcp'}
except Exception as e:
    logger.warning(f"Canva MCP failed: {e}")
    # Tier 2: Brief-only mode
    return {'brief': brief, 'canva_prompt': prompt, 'source': 'brief_only'}
```

## Testing

### Run Main Script
```bash
python main.py
```

### Run Specific Agent
```bash
from agents.clip_intelligence import analyze_video
result = analyze_video('tests/sample_video.mp4')
print(result)
```

### Check Database
```bash
sqlite3 data/chaos_merchant.db
> SELECT * FROM hooks LIMIT 5;
> SELECT * FROM channel_memory ORDER BY publish_date DESC;
```

## Environment Variables

**Required:**
- `ANTHROPIC_API_KEY` - Claude API key
- `YOUTUBE_API_KEY` - YouTube Data API key

**Optional (for Reddit trends):**
- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT`

**Optional (for ElevenLabs fallback):**
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`

## Common Issues

### ffmpeg not found
Install: `brew install ffmpeg` (macOS) or `apt-get install ffmpeg` (Linux)

### Kokoro TTS too slow
- Kokoro runs on CPU only (no GPU needed)
- 8.5 minutes for full audiobook is normal
- For 7 shorts (~5-10 min total audio): expect 2-3 minutes

### Canva MCP Thumbnail Generation - Session Dependency

**CRITICAL SETUP NOTE:** Canva MCP thumbnails ONLY work when Claude Code is actively running in a session.

**Two Operating Modes:**

**Mode 1: Claude Code Active Session (Cloud/Interactive)**
- ✅ Canva MCP available: thumbnail images generated directly
- Pipeline can create thumbnails end-to-end
- Output: `thumbnails[].image_url` (ready for upload)
- Setup: Run via Claude Code web/desktop app

**Mode 2: Autonomous Home Machine (No Session)**
- ❌ Canva MCP NOT available: falls back to `brief_only` mode
- Pipeline generates detailed visual briefs instead of images
- Output: `thumbnails[].brief` + `thumbnails[].canva_prompt` + `instructions`
- Workflow: User manually creates thumbnails on Canva.com after pipeline completes
- Setup: Run `python main.py` directly on home machine (no Claude Code session)

**Automatic Fallback Logic:**
```python
# agents/thumbnail.py
if canva_mcp_available:
    thumbnail_url = canva_mcp.generate(prompt)  # Return image URL
else:
    # Home machine mode: return brief for manual creation
    return {
        'status': 'brief_only',
        'brief': 'Detailed visual description...',
        'canva_prompt': 'Canva-optimized prompt...',
        'instructions': 'Create on Canva.com using this prompt'
    }
```

**At Setup Time:**
- Cloud/automated deployment (AWS, GitHub Actions, etc.): Uses Canva MCP (thumbnails auto-generated)
- Home machine local runs: Uses brief-only mode (manual thumbnail creation)
- No configuration needed: Detects automatically and adapts

**For Home Machine Users:**
1. Run pipeline: `python main.py`
2. Video production completes (7 MP4s with all features)
3. Thumbnail generation creates briefs
4. Check `output/[video]_thumbnail_manifest.json` for briefs
5. Log into Canva.com and use briefs/prompts to create thumbnails
6. Download thumbnails and place in output folder
7. Proceed to Step 9: Output Packaging

**Expected Manifest Format (Brief-Only Mode):**
```json
{
  "status": "partial",
  "generated_count": 0,
  "brief_only_count": 7,
  "thumbnails": [
    {
      "status": "brief_only",
      "brief": "Gaming glitch moment - pixelated broken screen...",
      "canva_prompt": "YouTube thumbnail: gaming glitch, high contrast...",
      "instructions": "Create on Canva.com using this prompt"
    },
    ...
  ]
}
```

### Quality Control Validation - Step 6

Quality Control validates all pipeline outputs before proceeding to packaging. It performs three-tier validation:

**Tier 1: Video File Validation**
- Codec: h264 required (YouTube Shorts standard)
- Resolution: Exactly 1080x1920 pixels (9:16 vertical format)
- Aspect Ratio: 9:16 (verified from resolution)
- Duration: 10-120 seconds (YouTube Shorts limits)
- File Size: 500KB-100MB (sanity check)
- Audio Presence: Video must have audio track
- Audio Sync: Voiceover duration must match video duration (±1 second)

**Tier 2: Metadata Validation**
- Clip Manifest: Must have 7 top_clip_indices, all clips present with scores
- SEO Manifest: Must have best_title, hashtags (10-15), keywords (10+ phrases), tags (5-8)
- Video Manifest: Must have video_paths (7 videos), codec info, processing_times
- Thumbnail Manifest: Must have status ('generated' or 'brief_only'), generated_count + brief_only_count = 7

**Tier 3: Routing Decision**
- **PASS**: All videos valid, all metadata complete → Proceed to Step 7 (Output Packaging)
- **WARNING**: Videos valid, minor metadata gaps detected → Log warnings, continue with best-effort
- **ERROR**: Any video validation fails OR critical metadata missing → Route to manual_review queue

**Manual Review Workflow:**
When QC fails with errors:
1. Check `output/[video]_qc_manifest.json` for specific validation errors
2. Fix issues: regenerate videos, verify metadata completeness
3. Re-run quality control: `python core/quality_control.py --video [path] --manifest [path]`
4. Proceed to Step 7 once QC passes

**QC Manifest Output:**
```json
{
  "status": "pass|warning|error",
  "routing": "pass|manual_review",
  "timestamp": "2026-07-02T12:00:00+00:00",
  "video_validation": {
    "total_checked": 7,
    "passed": 7,
    "failed": 0,
    "errors": []
  },
  "metadata_validation": {
    "clip_manifest": {"status": "valid"},
    "seo_manifest": {"status": "valid", "warnings": ["hashtags_less_than_15"]},
    "video_manifest": {"status": "valid"},
    "thumbnail_manifest": {"status": "valid"}
  },
  "warnings": ["Minor metadata gaps detected"],
  "qc_notes": "All video files passed codec/resolution/duration checks"
}
```

### Quality Control - Known Limitations

**Caption Detection False Positives**
- **Issue:** Frame detection analyzes bottom 15% of video for bright text on dark background
- **Risk:** Source video UI elements (game menus, HUD text, bright screen regions) in lower portion can trigger false positives
- **Mitigation:** Monitor during real footage testing; adjust frame detection thresholds if needed
- **Expected:** Minor false positives on first 1-2 batches of real gaming footage; refine detection after
- **Impact:** Low - worst case, falsely flags a video with bright UI as having captions; manual review catches it
- **Acceptable:** Yes, for launch. Will improve with channel-specific tuning

**Content Similarity - Initial Population Phase**
- **Issue:** Content similarity check requires 14-day channel history to work
- **First 14 Days:** Check runs but finds no prior shorts; effectively inactive until history builds
- **Expected Behavior:** All new content shows "similarity check skipped" for first 2 weeks
- **After 14 Days:** Full deduplication active; scans all recent shorts
- **Impact:** First batch has no protection against accidental topic repeats (single-batch risk)
- **Acceptable:** Yes, for launch. Real protection kicks in after first 2 weeks of daily uploads
- **Setup:** Channel memory auto-populates as shorts are published via YouTube API

### YouTube API quota exceeded
- Build tracks quota in `data/quota_tracker.json`
- Graceful degradation: analytics throttles first
- Check quota: `curl https://www.googleapis.com/youtube/v3/videos?quotaUser=...`

## Performance Targets

| Step | Component | Target Time | Hardware |
|------|-----------|-------------|----------|
| 2-3 | Clip Analysis | 4-5 min | CPU (OpenCV, librosa) |
| 4 | Voiceover (Kokoro) | 2-3 min | CPU (Kokoro TTS) |
| 5 | SEO Metadata | 1 min | CPU (Claude API) |
| 6 | Video Production | 20-25 min | CPU (ffmpeg) |
| 7 | Thumbnails | 2-3 min | Network (Canva MCP) |
| 8 | QC | 1-2 min | CPU (validation) |
| **TOTAL** | **Full Pipeline** | **40-50 min** | **Intel i3 acceptable** |

## Next Steps

Current phase: **Step 1 (Repo Scaffold) ✅ Complete**

Next to implement:
1. **Step 2:** Watcher Agent (file system monitoring)
2. **Step 3:** Clip Intelligence (scene detection + scoring)
3. **Step 4:** Script + Voiceover (Kokoro TTS primary + ElevenLabs testing)

---

**Last Updated:** Build Session 1
**Maintainer:** Claude Code
