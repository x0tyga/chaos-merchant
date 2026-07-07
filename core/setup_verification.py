"""
Setup Verification - checks every required dependency/configuration
WITHOUT starting the pipeline, scheduler, or watcher, so a broken setup
(a missing font, an unauthorized API key, ImageMagick's policy blocking
text, a truncated Kokoro model download) is obvious up front instead of
discovered 40 minutes into a real pipeline run.

Invoked via `python main.py --verify` - main.py checks for that flag and
imports run_verification() BEFORE importing the full agent stack, so a
genuinely broken/missing dependency in one of those modules can't crash
the verification command itself, which is exactly the failure mode this
exists to diagnose.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> Tuple[bool, str]:
    path = shutil.which('ffmpeg')
    if path:
        return True, path
    return False, "not found in PATH - install it (e.g. brew install ffmpeg on macOS, apt-get install ffmpeg on Linux)"


def _check_imagemagick() -> Tuple[bool, str]:
    """
    Checks both that ImageMagick is installed AND that its policy actually
    allows text/label rendering - the real-world way this gotcha bites is
    ImageMagick being present but its policy.xml silently blocking the
    exact operation being used, which "is it installed" alone can't catch.
    Renders a real tiny label image rather than parsing policy.xml, since
    that's the one test that reflects what will actually happen at render
    time regardless of ImageMagick version or policy file location.

    NOTE: as of this session's Bug 3 fix, moviepy 2.x's TextClip no longer
    uses ImageMagick at all for captions (it renders via Pillow directly,
    with its own font-fallback chain - see CAPTION_FONT_PATH below), so
    this check is no longer load-bearing for captions specifically. Still
    checked because some setup docs/other moviepy effects may still
    reference it, and it's cheap to verify either way.
    """
    binary = shutil.which('convert') or shutil.which('magick')
    if not binary:
        return False, (
            "not installed - not load-bearing for captions (moviepy 2.x renders those via "
            "Pillow directly), but install it if any other tooling in your setup expects it"
        )

    test_path = Path(tempfile.gettempdir()) / '_chaos_merchant_im_verify.png'
    try:
        result = subprocess.run(
            [binary, '-size', '100x30', 'label:test', str(test_path)],
            capture_output=True, timeout=10, text=True
        )
        if result.returncode != 0:
            return False, f"installed at {binary} but policy likely blocks text/label operations: {result.stderr.strip()[:200]}"
        return True, f"found at {binary}, text/label rendering verified working"
    except Exception as e:
        return False, f"found at {binary} but a test render failed: {e}"
    finally:
        try:
            test_path.unlink(missing_ok=True)
        except Exception:
            pass


def _check_kokoro_files() -> Tuple[bool, str]:
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False, "kokoro-onnx package not installed (pip install kokoro-onnx) - ElevenLabs fallback still works if configured"

    model_path = os.getenv('KOKORO_MODEL_PATH', 'kokoro-v1.0.onnx')
    voices_path = os.getenv('KOKORO_VOICES_PATH', 'voices-v1.0.bin')

    if not os.path.exists(model_path):
        return False, f"KOKORO_MODEL_PATH not found: {model_path} (see agents/script_voiceover.py's KokoroTTS docstring for the download command)"
    if not os.path.exists(voices_path):
        return False, f"KOKORO_VOICES_PATH not found: {voices_path}"

    model_size = os.path.getsize(model_path)
    if model_size < 1_000_000:
        return False, f"{model_path} is only {model_size} bytes - too small to be a real model (corrupted/truncated download, or an HTML error page saved in its place)"

    return True, f"{model_path} ({model_size / 1_000_000:.0f}MB), {voices_path} present"


def _check_anthropic_key() -> Tuple[bool, str]:
    key = os.getenv('ANTHROPIC_API_KEY', '')
    if not key or key.strip() in ('', 'sk-ant-...'):
        return False, "ANTHROPIC_API_KEY not set (or still the placeholder value from .env.example)"

    try:
        from anthropic import Anthropic
        client = Anthropic()
        # A real, minimal (1 output token) live call - the only way to
        # actually confirm the key authenticates, not just that it's a
        # non-empty string. Costs a negligible amount of real API spend,
        # acceptable for a command the user runs deliberately, not part
        # of any automated/scheduled run.
        client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1, messages=[{"role": "user", "content": "hi"}])
        return True, "key present and authenticated successfully (verified with a live 1-token API call)"
    except ImportError:
        return False, "ANTHROPIC_API_KEY is set but the anthropic package isn't installed (pip install anthropic) to verify it"
    except Exception as e:
        return False, f"key present but the live API call failed - likely invalid/revoked: {e}"


def _check_reddit_credentials() -> Tuple[bool, str]:
    client_id = os.getenv('REDDIT_CLIENT_ID', '')
    client_secret = os.getenv('REDDIT_CLIENT_SECRET', '')
    if not client_id or not client_secret or 'your-reddit' in client_id:
        return False, (
            "REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not set (or still placeholder values) - "
            "Reddit sourcing and trend intelligence will both be skipped"
        )

    try:
        import praw
        reddit = praw.Reddit(
            client_id=client_id, client_secret=client_secret,
            user_agent=os.getenv('REDDIT_USER_AGENT', 'chaos-merchant/1.0')
        )
        _ = reddit.subreddit('announcements').display_name  # lightweight real call to confirm auth actually works
        return True, "credentials present and authenticated successfully (verified with a live call)"
    except ImportError:
        return True, "credentials present (praw not installed to verify live - pip install praw)"
    except Exception as e:
        return False, f"credentials present but authentication failed: {e}"


def _check_youtube_api_key() -> Tuple[bool, str]:
    key = os.getenv('YOUTUBE_API_KEY', '')
    if not key or 'your-youtube-api-key' in key:
        return False, "YOUTUBE_API_KEY not set (or still the placeholder value from .env.example)"
    return True, f"set ({key[:6]}...)"


def _check_music_folder() -> Tuple[bool, str]:
    music_dir = Path(os.getenv('BACKGROUND_MUSIC_DIR', './assets/music'))
    supported_formats = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')
    if not music_dir.exists():
        return False, f"{music_dir} does not exist"
    tracks = [f for f in music_dir.iterdir() if f.is_file() and f.suffix.lower() in supported_formats]
    if not tracks:
        return False, f"{music_dir} exists but has no audio files ({'/'.join(supported_formats)}) - shorts will ship voiceover-only"
    names = ', '.join(t.name for t in tracks[:3]) + ('...' if len(tracks) > 3 else '')
    return True, f"{len(tracks)} track(s) found: {names}"


def _check_caption_font() -> Tuple[bool, str]:
    font_path = os.getenv('CAPTION_FONT_PATH', '')
    if not font_path:
        return False, (
            "not set - captions will use the automatic fallback chain (DejaVu/Liberation/macOS "
            "system fonts), which is functional but not guaranteed to be a real gaming-style font"
        )
    if not Path(font_path).exists():
        return False, f"set to {font_path} but that file does not exist"
    return True, f"{font_path} exists"


def run_verification() -> bool:
    """
    Runs every check and prints a clear PASS/FAIL line for each, followed
    by an overall summary. Returns True only if every check passed.
    """
    print("=" * 70)
    print("CHAOS MERCHANT - SETUP VERIFICATION")
    print("=" * 70)

    checks = [
        ('ffmpeg in PATH', _check_ffmpeg),
        ('ImageMagick installed, policy allows text/label', _check_imagemagick),
        ('Kokoro model files present and valid size', _check_kokoro_files),
        ('ANTHROPIC_API_KEY set and valid', _check_anthropic_key),
        ('Reddit credentials set', _check_reddit_credentials),
        ('YOUTUBE_API_KEY set', _check_youtube_api_key),
        ('assets/music/ has at least one track', _check_music_folder),
        ('CAPTION_FONT_PATH set and file exists', _check_caption_font),
    ]

    all_passed = True
    for name, check_fn in checks:
        try:
            passed, detail = check_fn()
        except Exception as e:
            passed, detail = False, f"check itself raised an unexpected error: {e}"
        icon = "✓ PASS" if passed else "❌ FAIL"
        print(f"{icon}  {name}")
        print(f"       {detail}")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("✓ ALL CHECKS PASSED")
    else:
        print("❌ SOME CHECKS FAILED - fix the above before running the full pipeline")
    print("=" * 70)

    return all_passed


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.WARNING)  # keep output to the check results, not INFO chatter
    sys.exit(0 if run_verification() else 1)
