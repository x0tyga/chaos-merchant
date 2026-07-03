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

# ImageMagick ships with a security policy that, on many distros/Homebrew
# installs, denies the text/label/caption coders and @-file reads that
# moviepy's TextClip(method='caption') needs - without this fix, captions
# fail silently or with a PolicyError no matter how correct the code is.
if [ "$IMAGEMAGICK_OK" -eq 1 ]; then
    echo ""
    echo "🔧 Checking ImageMagick policy.xml for caption-blocking rules..."
    IM_POLICY_PATH=""
    if [[ "$(uname)" == "Darwin" ]]; then
        IM_POLICY_CANDIDATES=(
            /opt/homebrew/etc/ImageMagick-7/policy.xml
            /opt/homebrew/etc/ImageMagick-6/policy.xml
            /usr/local/etc/ImageMagick-7/policy.xml
            /usr/local/etc/ImageMagick-6/policy.xml
        )
    else
        IM_POLICY_CANDIDATES=(
            /etc/ImageMagick-7/policy.xml
            /etc/ImageMagick-6/policy.xml
            /etc/ImageMagick/policy.xml
        )
    fi
    for candidate in "${IM_POLICY_CANDIDATES[@]}"; do
        if [ -f "$candidate" ]; then
            IM_POLICY_PATH="$candidate"
            break
        fi
    done

    if [ -n "$IM_POLICY_PATH" ]; then
        # Match rights="none" rules on the patterns that block caption
        # rendering: @ (reading external files as args), and the TEXT/
        # LABEL/CAPTION coders (case-insensitive pattern names).
        if grep -qEi 'rights="none"[^>]*pattern="(@\*?|text|label|caption)"' "$IM_POLICY_PATH" \
           || grep -qEi 'pattern="(@\*?|text|label|caption)"[^>]*rights="none"' "$IM_POLICY_PATH"; then
            echo "  ⚠ Found policy rule(s) blocking text/label/caption operations in $IM_POLICY_PATH"
            cp "$IM_POLICY_PATH" "$IM_POLICY_PATH.bak.$(date +%s)" 2>/dev/null && \
                echo "  📋 Backed up original policy.xml before editing"
            echo "  🔧 Attempting automatic fix (requires sudo)..."
            if [[ "$(uname)" == "Darwin" ]]; then
                SED_FIX=(sudo sed -i '' -E 's/rights="none"([^>]*pattern="(@\*?|TEXT|LABEL|CAPTION)")/rights="read|write"\1/gI')
            else
                SED_FIX=(sudo sed -i -E 's/rights="none"([^>]*pattern="(@\*?|TEXT|LABEL|CAPTION)")/rights="read|write"\1/gI')
            fi
            if "${SED_FIX[@]}" "$IM_POLICY_PATH" 2>/dev/null; then
                echo "  ✓ ImageMagick policy.xml patched - text/label/caption operations now allowed"
            else
                echo "  ❌ Could not patch automatically (sudo declined or sed failed). Fix manually:"
                if [[ "$(uname)" == "Darwin" ]]; then
                    echo "     sudo sed -i '' 's/rights=\"none\" pattern=\"@/rights=\"read|write\" pattern=\"@/' \"$IM_POLICY_PATH\""
                else
                    echo "     sudo sed -i 's/rights=\"none\" pattern=\"@/rights=\"read|write\" pattern=\"@/' \"$IM_POLICY_PATH\""
                fi
                echo "     (also check for rights=\"none\" pattern=\"TEXT|LABEL|CAPTION\" rules)"
            fi
        else
            echo "  ✓ No caption-blocking policy rule found in $IM_POLICY_PATH"
        fi
    else
        echo "  ℹ Could not locate policy.xml automatically. If captions fail with a"
        echo "     PolicyError later, find it with: find / -name policy.xml 2>/dev/null"
    fi
fi

# Check for Kokoro TTS (package now in requirements.txt; model files are NOT
# pip-installable and must be downloaded separately)
KOKORO_OK=1
if ! python3 -c "import kokoro_onnx" &> /dev/null; then
    KOKORO_OK=0
    echo "⚠️  kokoro-onnx not installed (primary voice engine)"
else
    echo "✓ kokoro-onnx found"
fi

# Download the Kokoro model files automatically if the package is present.
# Both files come from the SAME release tag - mixing versions causes load
# failures. A file under 1MB means a corrupted/interrupted download or a 404
# response saved in place of the real binary (both produce a file that
# *exists* but fails at load time with an opaque error), so re-download it.
KOKORO_MODEL_PATH="${KOKORO_MODEL_PATH:-kokoro-v1.0.onnx}"
KOKORO_VOICES_PATH="${KOKORO_VOICES_PATH:-voices-v1.0.bin}"
KOKORO_MODEL_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
KOKORO_MIN_BYTES=1000000

download_kokoro_file() {
    local url="$1" dest="$2" label="$3" size
    if [ -f "$dest" ]; then
        size=$(wc -c < "$dest" 2>/dev/null | tr -d ' ')
        if [ "${size:-0}" -ge "$KOKORO_MIN_BYTES" ]; then
            echo "  ✓ $label already present ($dest, ${size} bytes)"
            return 0
        fi
        echo "  ⚠ $label exists but is only ${size:-0} bytes (corrupt/incomplete) - re-downloading"
    fi
    echo "  ⬇ Downloading $label..."
    if curl -fL -o "$dest" "$url"; then
        size=$(wc -c < "$dest" 2>/dev/null | tr -d ' ')
        if [ "${size:-0}" -lt "$KOKORO_MIN_BYTES" ]; then
            echo "  ❌ Downloaded $label is only ${size:-0} bytes - likely a 404 or interrupted transfer"
            echo "     Check manually: curl -fL -o \"$dest\" \"$url\""
            return 1
        fi
        echo "  ✓ $label downloaded (${size} bytes)"
        return 0
    else
        echo "  ❌ Failed to download $label from $url"
        return 1
    fi
}

if [ "$KOKORO_OK" -eq 1 ]; then
    echo ""
    echo "📦 Checking Kokoro model files..."
    KOKORO_MODEL_OK=1
    download_kokoro_file "$KOKORO_MODEL_URL" "$KOKORO_MODEL_PATH" "kokoro-v1.0.onnx" || KOKORO_MODEL_OK=0
    download_kokoro_file "$KOKORO_VOICES_URL" "$KOKORO_VOICES_PATH" "voices-v1.0.bin" || KOKORO_MODEL_OK=0
    if [ "$KOKORO_MODEL_OK" -eq 0 ]; then
        KOKORO_OK=0
    fi
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
    echo "$STEP. Kokoro TTS setup is incomplete (REQUIRED unless using ElevenLabs only)."
    echo "     kokoro-onnx is now in requirements.txt (installed above), and this script"
    echo "     already attempted to auto-download the model files via curl - check the"
    echo "     'Checking Kokoro model files' output above for why that failed, then either"
    echo "     re-run this script or download manually:"
    echo "       curl -fL -o kokoro-v1.0.onnx $KOKORO_MODEL_URL"
    echo "       curl -fL -o voices-v1.0.bin $KOKORO_VOICES_URL"
    echo "     Verify neither file is suspiciously small (should be several MB+):"
    echo "       ls -la kokoro-v1.0.onnx voices-v1.0.bin"
    echo "     Then set KOKORO_MODEL_PATH / KOKORO_VOICES_PATH in .env to their paths"
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
