# Chaos Merchant - Python 3.11, ffmpeg, ImageMagick (policy pre-patched for
# captions), all pip deps, and Kokoro's TTS model files baked in at build
# time - `docker-compose up` should require nothing beyond a filled-in .env.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# System dependencies:
#   ffmpeg             - video export (moviepy/ffmpeg-python/ffmpeg-normalize)
#   imagemagick         - moviepy's TextClip (burned-in captions) shells out to `convert`
#   libgl1/libglib2.0-0  - required by opencv-python at import time (not headless)
#   libsndfile1           - required by soundfile/librosa
#   curl                   - Kokoro model file download below
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        imagemagick \
        libgl1 \
        libglib2.0-0 \
        libsndfile1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ImageMagick's default policy.xml on Debian denies the text/label/caption
# coders and @-file reads that moviepy's TextClip(method='caption') needs -
# without this, captions fail with a silent no-op or PolicyError regardless
# of how correct the application code is. Same fix setup.sh applies
# interactively via sudo+sed on a host machine; here it's done at build
# time since the container runs as root already.
RUN for policy in /etc/ImageMagick-6/policy.xml /etc/ImageMagick-7/policy.xml /etc/ImageMagick/policy.xml; do \
        if [ -f "$policy" ]; then \
            sed -i -E 's/rights="none"([^>]*pattern="(@\*?|TEXT|LABEL|CAPTION)")/rights="read|write"\1/gI' "$policy"; \
            echo "Patched ImageMagick policy: $policy"; \
        fi; \
    done

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Kokoro TTS model files - not pip-installable, downloaded from the same
# release tag setup.sh uses on a host machine. Baked into the image so a
# container start never depends on this succeeding at runtime.
ARG KOKORO_MODEL_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
ARG KOKORO_VOICES_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
RUN curl -fL -o kokoro-v1.0.onnx "$KOKORO_MODEL_URL" \
    && curl -fL -o voices-v1.0.bin "$KOKORO_VOICES_URL" \
    && test "$(wc -c < kokoro-v1.0.onnx)" -gt 1000000 \
    && test "$(wc -c < voices-v1.0.bin)" -gt 1000000

COPY . .

RUN mkdir -p input output data data/checkpoints data/backups logs analytics config prompts

# Initialize the SQLite schema at build time so a fresh container has a
# valid (if empty) database from the first start, same as setup.sh does on
# a host machine.
RUN python3 -c "from core.memory import HookLibrary, ChannelMemory; HookLibrary('./data/chaos_merchant.db'); ChannelMemory('./data/chaos_merchant.db')"

EXPOSE 5050

# Default command runs the pipeline (watcher + scheduler); docker-compose.yml
# overrides this for the dashboard service.
CMD ["python3", "main.py"]
