#!/bin/bash

set -e

echo "🚀 Chaos Merchant Setup"
echo "======================="
echo ""

# Check Python version
python3 --version

# Create virtual environment
echo ""
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo "📦 Installing dependencies from requirements.txt..."
pip install -r requirements.txt --quiet

# Check for ffmpeg
FFMPEG_OK=1
if ! command -v ffmpeg &> /dev/null; then
    FFMPEG_OK=0
    echo "⚠️  ffmpeg not found"
else
    echo "✓ ffmpeg found"
fi

# Check for ImageMagick (moviepy's TextClip / caption rendering depends on it)
IMAGEMAGICK_OK=1
if ! command -v convert &> /dev/null && ! command -v magick &> /dev/null; then
    IMAGEMAGICK_OK=0
    echo "⚠️  ImageMagick not found (needed for burned-in captions)"
else
    echo "✓ ImageMagick found"
fi

# Check for Kokoro TTS (not in requirements.txt, installed separately)
KOKORO_OK=1
if ! python3 -c "import kokoro" &> /dev/null; then
    KOKORO_OK=0
    echo "⚠️  kokoro-tts not installed (primary voice engine)"
else
    echo "✓ kokoro-tts found"
fi

# Create .env from example FIRST, so we have one source of truth for paths
ENV_CREATED=0
if [ ! -f .env ]; then
    echo ""
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
    ENV_CREATED=1
else
    echo ""
    echo "✓ .env already exists (not overwritten)"
fi

# Read the configured paths out of .env so setup.sh and .env can never drift apart
INPUT_DIR=$(grep -E "^INPUT_DIR=" .env | cut -d '=' -f2-)
OUTPUT_DIR=$(grep -E "^OUTPUT_DIR=" .env | cut -d '=' -f2-)
DATA_DIR=$(grep -E "^DATA_DIR=" .env | cut -d '=' -f2-)

if [ -z "$INPUT_DIR" ] || [ -z "$OUTPUT_DIR" ] || [ -z "$DATA_DIR" ]; then
    echo "❌ Could not read INPUT_DIR / OUTPUT_DIR / DATA_DIR from .env - check the file"
    exit 1
fi

echo ""
echo "📁 Creating configured directories..."
mkdir -p "$INPUT_DIR"
mkdir -p "$OUTPUT_DIR"
mkdir -p "$DATA_DIR"
mkdir -p "$DATA_DIR/checkpoints"
mkdir -p "$DATA_DIR/backups"
echo "  ✓ $INPUT_DIR"
echo "  ✓ $OUTPUT_DIR"
echo "  ✓ $DATA_DIR"
echo "  ✓ $DATA_DIR/checkpoints"
echo "  ✓ $DATA_DIR/backups"

# Initialize SQLite database WITH the real schema (hooks, hook_usage_log,
# channel_shorts, performance_history) - not just an empty file
echo ""
echo "📦 Initializing databases with full schema..."
python3 -c "
import sys
sys.path.insert(0, '.')
from core.memory import HookLibrary, ChannelMemory
db_path = '$DATA_DIR/chaos_merchant.db'
HookLibrary(db_path)
ChannelMemory(db_path)
print(f'✓ Database initialized with full schema: {db_path}')
"

echo ""
echo "✅ Setup complete!"
echo ""
echo "========================================================"
echo "  MANUAL STEPS STILL REQUIRED — do these before running"
echo "========================================================"
echo ""

STEP=1

echo "$STEP. Edit .env and fill in your API keys:"
echo "     ANTHROPIC_API_KEY   (REQUIRED - pipeline won't start without it)"
echo "     YOUTUBE_API_KEY     (REQUIRED - pipeline won't start without it)"
echo "     REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET   (optional - without these,"
echo "                          Trend Intelligence falls back to a small mock"
echo "                          trend list instead of real Reddit data)"
echo "     ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID  (optional - only needed if"
echo "                          you want a premium voice fallback for Kokoro)"
STEP=$((STEP+1))
echo ""

if [ "$FFMPEG_OK" -eq 0 ]; then
    echo "$STEP. Install ffmpeg (REQUIRED, not found):"
    echo "     brew install ffmpeg"
    STEP=$((STEP+1))
    echo ""
fi

if [ "$IMAGEMAGICK_OK" -eq 0 ]; then
    echo "$STEP. Install ImageMagick (REQUIRED for burned-in captions, not found):"
    echo "     brew install imagemagick"
    echo "     If captions still fail with a PolicyError after installing, check"
    echo "     ImageMagick's policy.xml (commonly /opt/homebrew/etc/ImageMagick-7/"
    echo "     policy.xml) for a rule blocking text/label operations."
    STEP=$((STEP+1))
    echo ""
fi

if [ "$KOKORO_OK" -eq 0 ]; then
    echo "$STEP. Install Kokoro TTS (REQUIRED unless you're using ElevenLabs only):"
    echo "     pip install kokoro-tts"
    STEP=$((STEP+1))
    echo ""
fi

echo "$STEP. Put a real gaming video (~10 min, .mp4/.mov/.mkv) into:"
echo "     $INPUT_DIR"
STEP=$((STEP+1))
echo ""

echo "$STEP. Run it:"
echo "     source venv/bin/activate"
echo "     python main.py"
echo ""
echo "========================================================"
if [ "$ENV_CREATED" -eq 1 ]; then
    echo "Directories configured (from .env.example defaults):"
else
    echo "Directories configured (from your existing .env):"
fi
echo "  INPUT_DIR:  $INPUT_DIR"
echo "  OUTPUT_DIR: $OUTPUT_DIR"
echo "  DATA_DIR:   $DATA_DIR"
echo "========================================================"
