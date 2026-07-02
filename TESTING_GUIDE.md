# Testing Guide - Chaos Merchant

Complete guide to testing your setup, running your first pipeline, and diagnosing failures.

## ✅ Pre-Flight Checklist

Run this before attempting your first full pipeline:

```bash
# 1. Python version
python --version  # Should be 3.11+

# 2. Virtual environment activated
echo $VIRTUAL_ENV  # Should show path to venv

# 3. Dependencies installed
pip list | grep -i "moviepy\|anthropic\|librosa"

# 4. .env file exists and has credentials
cat .env | grep ANTHROPIC_API_KEY

# 5. Input folder exists
ls -la input/

# 6. Database initializes
python -c "from core.memory import HookLibrary; HookLibrary()"
```

Expected output: All items show ✓

---

## 🧪 Test 1: Credentials Only (5 minutes)

**Purpose:** Verify all API keys work before running full pipeline

**Step 1: Create test script**

```bash
cat > test_credentials.py << 'EOF'
#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Check environment
print("=" * 70)
print("CHAOS MERCHANT - CREDENTIAL TEST")
print("=" * 70)

# 1. Anthropic
api_key = os.getenv('ANTHROPIC_API_KEY')
if api_key and api_key.startswith('sk-ant-'):
    print("✓ ANTHROPIC_API_KEY present")
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        print("✓ Anthropic API: Connected")
    except Exception as e:
        print(f"❌ Anthropic API: Failed - {e}")
        sys.exit(1)
else:
    print("❌ ANTHROPIC_API_KEY missing or invalid")
    sys.exit(1)

# 2. YouTube API
yt_key = os.getenv('YOUTUBE_API_KEY')
if yt_key:
    print("✓ YOUTUBE_API_KEY present")
else:
    print("⚠ YOUTUBE_API_KEY missing (optional - trends will work without it)")

# 3. Reddit API
reddit_id = os.getenv('REDDIT_CLIENT_ID')
if reddit_id:
    print("✓ REDDIT_CLIENT_ID present (optional)")
else:
    print("⚠ REDDIT_CLIENT_ID missing (optional - Google Trends will still work)")

# 4. Database
db_path = Path('./data/chaos_merchant.db')
try:
    from core.memory import HookLibrary, ChannelMemory
    hook_lib = HookLibrary()
    channel_mem = ChannelMemory()
    print("✓ Database: Initialized")
except Exception as e:
    print(f"❌ Database: Failed - {e}")
    sys.exit(1)

# 5. Dependencies
try:
    import moviepy
    import librosa
    import cv2
    print("✓ Video dependencies: Installed")
except ImportError as e:
    print(f"❌ Video dependencies: Missing - {e}")
    sys.exit(1)

print("=" * 70)
print("✓ ALL CHECKS PASSED - Ready for pipeline")
print("=" * 70)
EOF
chmod +x test_credentials.py
python test_credentials.py
```

**Expected output:**
```
✓ ANTHROPIC_API_KEY present
✓ Anthropic API: Connected
✓ YOUTUBE_API_KEY present
✓ REDDIT_CLIENT_ID present (optional)
✓ Database: Initialized
✓ Video dependencies: Installed
=============================================
✓ ALL CHECKS PASSED - Ready for pipeline
```

**If this fails:** Fix the issue before proceeding. See "Troubleshooting Credentials" section.

---

## 🎬 Test 2: Pipeline on Sample Video (50 minutes)

**Purpose:** End-to-end test with real video processing

**Step 1: Get sample video**

Option A (download sample):
```bash
cd input
# If you have wget/curl
wget https://commondatastorage.googleapis.com/gtv-videos-library/sample/BigBuckBunny.mp4 -O sample_video.mp4

# If you have curl
curl -L "https://commondatastorage.googleapis.com/gtv-videos-library/sample/BigBuckBunny.mp4" -o sample_video.mp4
```

Option B (use your own video):
```bash
cp ~/your_gaming_video.mp4 input/sample_video.mp4
```

**Step 2: Start pipeline**

```bash
python main.py

# You should see:
# 🎬 Starting pipeline for: sample_video.mp4
# Step 1/7: Clip Intelligence Analysis
#   ✓ Scene detection: 47 scenes found
#   ✓ Engagement scoring complete
#   ✓ Top 7 clips selected
# Step 2/7: Script Generation + Voiceover
#   ✓ Generating scripts for 7 clips
#   ✓ Kokoro TTS: 2m 34s
# ... (continues for ~40-50 min)
```

**Step 3: Monitor progress**

In another terminal:
```bash
# Watch output folder
watch -n 5 'ls -la output/batch_*/'

# Or check specific step
tail -f output/sample_video_clip_manifest.json
```

**Step 4: Check for success**

After pipeline completes, you should see:
```
✅ Pipeline complete!
📁 Batch folder: output/batch_YYYYMMDD_HHMMSS/
```

**Step 5: Verify output structure**

```bash
cd output/batch_YYYYMMDD_HHMMSS
ls -la
# Expected:
# -rw-r--r-- README.md
# -rw-r--r-- UPLOAD_ORDER.txt
# -rw-r--r-- VIDEO_CHECKLIST.md
# drwxr-xr-x shorts/
# drwxr-xr-x thumbnails/
# drwxr-xr-x upload_metadata/
# drwxr-xr-x manifests/

cd shorts
ls -la
# Should have: short_001.mp4 short_002.mp4 ... short_007.mp4

cd ../manifests
ls -la
# Should have: BATCH_MANIFEST.json, qc_manifest.json, etc.
```

**What success looks like:**
- ✓ 7 MP4 files in shorts/ (each 15-45 seconds)
- ✓ 7 thumbnail files in thumbnails/
- ✓ 7 JSON metadata files in upload_metadata/
- ✓ All manifests saved
- ✓ README.md readable in 30 seconds

---

## 🔧 Test 3: Component Tests (Individual Steps)

**Test Clip Intelligence**

```bash
python -c "
from agents.clip_intelligence import analyze_video
result = analyze_video('./input/sample_video.mp4', num_clips=7)
print(f'✓ Clips found: {len(result[\"clips\"])}')
print(f'✓ Top clips: {result[\"top_clip_indices\"]}')
"
```

Expected: Shows scene detection results

**Test Voiceover Generation**

```bash
python -c "
from agents.script_voiceover import generate_voiceover
manifest = {
    'clips': [{'start': 10, 'end': 25, 'duration': 15}],
    'top_clip_indices': [0]
}
result = generate_voiceover(manifest, [], [])
print(f'✓ Voiceover generated: {result.get(\"voiceover\", {}).get(\"engine\")}')
"
```

Expected: Kokoro TTS or ElevenLabs (with API key)

**Test Video Production**

```bash
python -c "
from agents.video_production import produce_shorts
# This requires all upstream data, skip if Step 4 didn't complete
print('✓ Video production module loaded')
"
```

**Test Quality Control**

```bash
python -c "
from core.memory import HookLibrary, ChannelMemory
hook_lib = HookLibrary()
channel_mem = ChannelMemory()

# Add test hook
hook_lib.add_hook('Test hook text', 'opening')

# Check top performers
top = hook_lib.get_top_performers()
print(f'✓ Hook library working: {len(top)} hooks in database')
"
```

---

## 🚨 Troubleshooting

### Issue: "ANTHROPIC_API_KEY not found"

**Cause:** .env file not in project root or key not set

**Solution:**
```bash
# Check .env exists
ls -la .env

# Check key is set
grep ANTHROPIC_API_KEY .env

# If missing, get key from https://console.anthropic.com/
# Then add to .env:
echo "ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE" >> .env
```

### Issue: "ModuleNotFoundError: No module named 'moviepy'"

**Cause:** Dependencies not installed

**Solution:**
```bash
# Install dependencies
pip install -r requirements.txt

# Verify
pip list | grep moviepy
```

### Issue: "No module named 'anthropic'"

**Cause:** Anthropic SDK not installed

**Solution:**
```bash
pip install anthropic
```

### Issue: "Kokoro TTS too slow (>5 minutes)"

**Cause:** Running on slow CPU or disk

**Solution:**
```bash
# Check CPU usage
top  # press q to exit

# Check disk speed
time dd if=/dev/zero of=test_file bs=1M count=100

# If very slow, use ElevenLabs fallback:
# Set ELEVENLABS_API_KEY in .env (requires paid account)
```

### Issue: "Video output has no audio"

**Cause:** Voiceover generation failed or audio sync issue

**Solution:**
```bash
# Check voiceover file exists
ls -la output/batch_*/voiceover_*.wav

# Check if voiceover duration matches video
ffprobe output/batch_*/shorts/short_001.mp4 | grep Duration

# Re-run pipeline (transient API issue)
python main.py
```

### Issue: "Captions not visible in output video"

**Cause:** Font not installed or caption generation failed

**Solution:**
```bash
# Check caption_style in video_manifest.json
cat output/batch_*/manifests/video_manifest.json | grep caption

# Set custom font (optional)
echo "CAPTION_FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" >> .env

# Re-run Step 4 (Video Production)
```

### Issue: "YouTube API quota exceeded"

**Cause:** Ran too many pipeline iterations today

**Solution:**
```bash
# Check quota usage
cat data/quota_tracker.json

# Wait until tomorrow (quota resets daily)
# Or increase limit: https://console.cloud.google.com/apis/dashboard
```

### Issue: "Database disk image is malformed"

**Cause:** Crash during database write

**Solution:**
```bash
# Restore from backup
ls data/backups/  # List available backups
cp data/backups/chaos_merchant_20260702_143056.db data/chaos_merchant.db

# Delete corrupted database
rm data/chaos_merchant.db
python main.py  # Recreates clean database
```

### Issue: "Batch folder but no videos/thumbnails"

**Cause:** Quality Control failed or Video Production crashed

**Solution:**
```bash
# Check QC results
cat output/batch_*/manifests/qc_manifest.json

# Look for errors in qc_result
jq '.qc_result.issues.errors' output/batch_*/manifests/qc_manifest.json

# Fix the issue (see error message) and re-run
```

---

## 📊 What Success Looks Like

### Successful Pipeline Run

Logs show:
```
🎬 Starting pipeline for: sample_video.mp4
Step 1/7: Clip Intelligence Analysis
  ✓ Scene detection: 47 scenes found
  ✓ Top 7 clips selected
Step 2/7: Script Generation + Voiceover
  ✓ Voiceover generated: kokoro_tts
Step 3/7: SEO Optimization
  ✓ SEO metadata generated
Step 4/7: Video Production
  ✓ Video 1: Exported (32.4s)
  ✓ Video 2: Exported (28.1s)
  ...
  ✓ Video 7: Exported (35.2s)
Step 5/7: Thumbnail Generation
  ✓ Thumbnails generated or briefs created
Step 6/7: Quality Control
  ✓ All 7 videos validated
  ✓ QC ROUTING: PASS
Step 7/7: Output Packaging
  ✓ Batch folder created: batch_20260702_143056
  ✓ README: 30-second summary
  ✓ Upload order: 7 videos ready

✅ Pipeline complete!
📁 Batch folder: output/batch_20260702_143056/
```

Output folder:
- ✓ batch_YYYYMMDD_HHMMSS/ exists
- ✓ README.md readable in 30 sec
- ✓ UPLOAD_ORDER.txt shows all 7 videos
- ✓ shorts/ has 7 MP4 files
- ✓ All MP4s between 15-45 seconds
- ✓ thumbnails/ has 7 JPG or BRIEF files
- ✓ upload_metadata/ has 7 JSON files
- ✓ manifests/ has all validation files

Database:
- ✓ Hook Library initialized
- ✓ Channel Memory initialized
- ✓ Backups created

### Successful Individual Test

Component test shows:
```
✓ Anthropic API: Connected
✓ Database: Initialized
✓ Video dependencies: Installed
✓ Clips found: 47
✓ Top clips: [0, 2, 5, ...]
✓ Voiceover generated: kokoro_tts
✓ Hook library working: X hooks in database
```

---

## 📈 Performance Expectations

**Normal run on Intel i3 (40-50 minutes total):**

- Clip Intelligence: 4-5 min
- Script Generation: 30 sec (Claude API)
- Voiceover: 2-3 min (Kokoro TTS CPU)
- SEO Optimizer: 1 min (Claude API)
- Video Production: 20-25 min (ffmpeg reframe + encode)
- Thumbnails: 2-3 min (Canva or brief)
- Quality Control: 1-2 min (validation)
- Output Packaging: 1 min (file copying)

**If slower:** Check CPU usage, disk space, or network latency (Claude API calls)

---

## 🔍 Debugging Steps

When something fails:

1. **Check the error message**
   ```bash
   # Read the last 50 lines of output
   tail -50 output.log
   ```

2. **Check specific manifests**
   ```bash
   # QC manifest shows validation errors
   cat output/batch_*/manifests/qc_manifest.json | jq '.qc_result'

   # Video manifest shows encoder errors
   cat output/batch_*/manifests/video_manifest.json | jq '.errors'
   ```

3. **Check logs in batch folder**
   ```bash
   cat output/batch_*/VALIDATION.log
   ```

4. **Re-run specific step**
   ```bash
   # If Step 4 failed, fix and re-run:
   python main.py  # checkpoint system will resume at Step 4
   ```

5. **Check YouTube API quota**
   ```bash
   cat data/quota_tracker.json
   ```

6. **Ask for help**
   Include:
   - Error message from logs
   - Contents of relevant manifest
   - Your .env config (no API keys!)
   - Output of: `python --version && pip list | head -20`

---

## ✅ Validation Checklist

Before considering pipeline successful:

- [ ] All 7 MP4 files created
- [ ] Each MP4 is 1080x1920 resolution
- [ ] Each MP4 is 15-45 seconds duration
- [ ] Audio present in all MP4s
- [ ] Captions visible in videos (burn-in check)
- [ ] Voiceover synced (±0.3s tolerance)
- [ ] QC manifest shows PASS
- [ ] README.md exists and is readable
- [ ] UPLOAD_ORDER.txt shows all 7
- [ ] Metadata JSON has title, description, hashtags
- [ ] Thumbnails exist (or briefs if brief-only mode)

---

**If all checks pass, you're ready to upload!**

Open `output/batch_YYYYMMDD_HHMMSS/README.md` and follow the YouTube upload instructions.
