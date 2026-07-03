"""
Script + Voiceover Agent - Script generation and voice synthesis
Generates gaming-focused scripts and produces voiceover audio
Primary: Kokoro TTS (free, local CPU)
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from datetime import datetime
import tempfile

from anthropic import Anthropic

logger = logging.getLogger(__name__)


class ScriptGenerator:
    """Generates YouTube Shorts scripts using Claude API"""

    def __init__(self):
        self.client = Anthropic()

    def generate_script(self, clip_data, trending_topics=None, channel_history=None):
        """
        Generate voiceover script from clip data
        
        Args:
            clip_data: Clip intelligence manifest
            trending_topics: List of trending topics
            channel_history: Previous video summaries
        
        Returns:
            dict: Generated script with metadata
        """
        logger.info("📝 Generating script...")
        
        # Build context
        top_clips = clip_data.get('top_clips', [])[:3]  # Use top 3 for context
        
        prompt = f"""Generate a YouTube Shorts voiceover script.

Video data:
- Duration: {clip_data.get('duration', 0):.1f} seconds
- Number of clips: {len(clip_data.get('clips', []))}
- Top engagement scores: {[round(c.get('engagement_score', 0), 2) for c in top_clips]}

Trending topics: {json.dumps(trending_topics or [], indent=2)}
Channel history: {json.dumps(channel_history or [], indent=2)}

Generate a JSON object with: hook, main_content, cta, full_script, reading_time_seconds"""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Parse response
            response_text = response.content[0].text
            
            # Try to extract JSON
            try:
                # Find JSON in response
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    script_data = json.loads(json_str)
                else:
                    raise ValueError("No JSON found")
            except (json.JSONDecodeError, ValueError):
                # Fallback: create structured script from response
                script_data = {
                    'hook': 'Check out this crazy moment!',
                    'main_content': response_text[:200],
                    'cta': 'Drop a like and subscribe for more!',
                    'full_script': response_text,
                    'reading_time_seconds': 40
                }
            
            logger.info(f"✓ Script generated ({script_data.get('reading_time_seconds', 0)}s)")
            return {
                'status': 'success',
                'script': script_data,
                'model': 'claude-haiku-4-5-20251001'
            }
            
        except Exception as e:
            logger.error(f"❌ Script generation failed: {e}")
            raise


class KokoroTTS:
    """Kokoro TTS voice synthesis (free, local, primary engine).

    Uses the kokoro-onnx package (module name: kokoro_onnx), which requires
    two matching-version model files downloaded separately (not installed
    via pip), from the SAME release tag:
    - ONNX model: KOKORO_MODEL_PATH (default: kokoro-v1.0.onnx)
    - Voices file: KOKORO_VOICES_PATH (default: voices-v1.0.bin)

        wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
        wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

    Mixing files from different release tags (e.g. a v1.0 voices file with
    a v1.1 onnx model) is a known source of load failures - always pull
    both files from the same release tag.
    """

    def __init__(self):
        self.model_path = os.getenv('KOKORO_MODEL_PATH', 'kokoro-v1.0.onnx')
        self.voices_path = os.getenv('KOKORO_VOICES_PATH', 'voices-v1.0.bin')
        self.available = self._check_availability()

    def _check_availability(self):
        """Check if kokoro-onnx is installed and model files exist"""
        try:
            import kokoro_onnx  # noqa: F401
        except ImportError:
            logger.warning("⚠️  kokoro-onnx not installed. Install with: pip install kokoro-onnx")
            return False

        if not os.path.exists(self.model_path) or not os.path.exists(self.voices_path):
            logger.warning(
                f"⚠️  Kokoro model files not found (KOKORO_MODEL_PATH={self.model_path}, "
                f"KOKORO_VOICES_PATH={self.voices_path}). Download both files from the SAME "
                f"release tag: https://github.com/thewh1teagle/kokoro-onnx/releases"
            )
            return False

        # Sanity-check the ONNX model isn't a truncated download, an HTML
        # error page, or a git-lfs pointer file saved in place of the real
        # binary. All of those produce a file that *exists* but fails at
        # load time with onnxruntime's opaque "INVALID_PROTOBUF: ...
        # Protobuf parsing failed" instead of a clear "file missing" error.
        # A real kokoro onnx model is tens to hundreds of MB.
        model_size = os.path.getsize(self.model_path)
        if model_size < 1_000_000:
            logger.warning(
                f"⚠️  KOKORO_MODEL_PATH ({self.model_path}) is only {model_size} bytes - "
                f"too small to be a real ONNX model, so it will fail to load with a "
                f"Protobuf parsing error. This usually means the download was "
                f"interrupted, or an HTML error page / git-lfs pointer got saved instead "
                f"of the actual binary. Re-download with: wget "
                f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
            )
            return False

        if os.path.basename(self.model_path) not in ('kokoro-v1.0.onnx', 'kokoro-v1.0.fp16.onnx', 'kokoro-v1.0.int8.onnx'):
            logger.warning(
                f"⚠️  KOKORO_MODEL_PATH points at '{os.path.basename(self.model_path)}', not a "
                f"recognized kokoro-v1.0.* filename. If this is the legacy kokoro-v0_19.onnx "
                f"model, it predates the current voices-v1.0.bin format and the two are not "
                f"guaranteed compatible - update KOKORO_MODEL_PATH to a v1.0 model from: "
                f"https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0"
            )

        return True

    @staticmethod
    def _construct_kokoro(model_path, voices_path):
        """
        kokoro-onnx's Kokoro() constructor loads the voices file via
        np.load(voices_path) without passing allow_pickle=True. The
        official voices-*.bin release files are npz archives containing
        pickled style-vector objects, so under NumPy's allow_pickle=False
        default this raises: "This file contains pickled (object) data.
        ... load it unsafely using the allow_pickle= keyword argument".
        This is a known upstream limitation (thewh1teagle/kokoro-onnx#161),
        not a corrupt/wrong download - kokoro-onnx just never sets the flag.

        We don't control that internal np.load() call, so allow_pickle is
        patched into numpy's default only for the duration of this
        constructor call. This is safe specifically because voices_path is
        the official release file the operator downloaded themselves, not
        arbitrary/untrusted input - pickle loading is only ever a security
        risk for files from an untrusted source.
        """
        import numpy as np
        from kokoro_onnx import Kokoro

        original_load = np.load

        def _load_allow_pickle(*args, **kwargs):
            kwargs.setdefault('allow_pickle', True)
            return original_load(*args, **kwargs)

        np.load = _load_allow_pickle
        try:
            return Kokoro(model_path, voices_path)
        except Exception as e:
            if 'protobuf' in str(e).lower():
                raise RuntimeError(
                    f"Kokoro ONNX model at {model_path} is not a valid ONNX model "
                    f"(protobuf parsing failed): {e}\n"
                    f"The file is corrupted, truncated, or the wrong file was saved at "
                    f"this path (e.g. an HTML error page or git-lfs pointer instead of "
                    f"the real binary). Delete it and re-download: wget "
                    f"https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
                ) from e
            raise
        finally:
            np.load = original_load

    def generate(self, text, voice='bella', output_path=None):
        """
        Generate voiceover using Kokoro TTS

        Args:
            text: Text to synthesize
            voice: Voice name (bella, heart, nova, etc)
            output_path: Output WAV file path

        Returns:
            dict: Audio file path and metadata
        """
        if not self.available:
            raise RuntimeError("Kokoro TTS not available")

        logger.info(f"🎙️  Generating voiceover with Kokoro ({voice})...")

        try:
            import soundfile as sf

            if output_path is None:
                output_path = f"/tmp/voiceover_kokoro_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"

            # Generate audio
            tts = self._construct_kokoro(self.model_path, self.voices_path)
            samples, sample_rate = tts.create(text, voice=voice)

            # Save to file
            sf.write(output_path, samples, sample_rate)

            logger.info(f"✓ Kokoro voiceover saved: {output_path}")

            return {
                'status': 'success',
                'engine': 'kokoro',
                'voice': voice,
                'audio_path': output_path,
                'text_length': len(text),
                'estimated_duration': len(text) / 150 * 60  # ~150 words per minute
            }

        except Exception as e:
            logger.error(f"❌ Kokoro TTS failed: {e}")
            raise


class ElevenLabsTTS:
    """ElevenLabs voice synthesis (premium, cloud-based, optional fallback)"""

    def __init__(self):
        self.api_key = os.getenv('ELEVENLABS_API_KEY')
        self.voice_id = os.getenv('ELEVENLABS_VOICE_ID')
        self.available = bool(self.api_key and self.voice_id)

    def generate(self, text, output_path=None):
        """Generate voiceover using ElevenLabs API"""
        if not self.available:
            raise RuntimeError("ElevenLabs not configured (set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID)")

        logger.info("🎙️  Generating voiceover with ElevenLabs...")

        try:
            import requests

            if output_path is None:
                output_path = f"/tmp/voiceover_elevenlabs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json"
            }
            data = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }

            response = requests.post(url, json=data, headers=headers, timeout=60)

            if response.status_code != 200:
                raise RuntimeError(f"ElevenLabs API error: {response.status_code} {response.text[:200]}")

            with open(output_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"✓ ElevenLabs voiceover saved: {output_path}")

            return {
                'status': 'success',
                'engine': 'elevenlabs',
                'voice_id': self.voice_id,
                'audio_path': output_path,
                'text_length': len(text),
                'estimated_duration': len(text) / 150 * 60
            }

        except Exception as e:
            logger.error(f"❌ ElevenLabs TTS failed: {e}")
            raise


class VoiceoverComparison:
    """
    Generates the same text with both Kokoro and ElevenLabs (whichever are
    available/configured) for side-by-side quality comparison.
    Used by core/quality_test.py and test_voice_comparison.py.
    """

    @staticmethod
    def compare(text: str, sample_name: str = 'test') -> dict:
        """
        Args:
            text: Text to synthesize with both engines
            sample_name: Identifier used to name output audio files

        Returns:
            dict: {'kokoro': {...}, 'elevenlabs': {...}} each with a 'status' key
                  of 'success', 'error', or 'unavailable'
        """
        results = {}

        kokoro = KokoroTTS()
        if kokoro.available:
            try:
                output_path = f"/tmp/voiceover_compare_{sample_name}_kokoro.wav"
                results['kokoro'] = kokoro.generate(text, output_path=output_path)
            except Exception as e:
                logger.warning(f"⚠️  Kokoro comparison sample failed: {e}")
                results['kokoro'] = {'status': 'error', 'engine': 'kokoro', 'error': str(e)}
        else:
            results['kokoro'] = {'status': 'unavailable', 'engine': 'kokoro', 'error': 'Kokoro not installed'}

        elevenlabs = ElevenLabsTTS()
        if elevenlabs.available:
            try:
                output_path = f"/tmp/voiceover_compare_{sample_name}_elevenlabs.mp3"
                results['elevenlabs'] = elevenlabs.generate(text, output_path=output_path)
            except Exception as e:
                logger.warning(f"⚠️  ElevenLabs comparison sample failed: {e}")
                results['elevenlabs'] = {'status': 'error', 'engine': 'elevenlabs', 'error': str(e)}
        else:
            results['elevenlabs'] = {'status': 'unavailable', 'engine': 'elevenlabs', 'error': 'ElevenLabs not configured'}

        return results


def generate_voiceover(clip_data, trending_topics=None, channel_history=None):
    """
    Main function to generate script and voiceover.
    Primary: Kokoro TTS (free, local). Fallback: ElevenLabs (if configured).

    Args:
        clip_data: Clip intelligence manifest
        trending_topics: Trending topics for context
        channel_history: Previous video data

    Returns:
        dict: Script + voiceover results
    """
    logger.info("🎬 Starting script + voiceover generation...")

    # Generate script
    generator = ScriptGenerator()
    script_result = generator.generate_script(clip_data, trending_topics, channel_history)

    if script_result['status'] != 'success':
        raise RuntimeError("Script generation failed")

    script = script_result['script']
    full_text = script.get('full_script', '')

    # Primary: Kokoro TTS (free, local)
    voiceover_result = None
    kokoro = KokoroTTS()

    if kokoro.available:
        try:
            logger.info("Using Kokoro TTS (free, local voice synthesis)...")
            voiceover_result = kokoro.generate(full_text)
        except Exception as e:
            logger.warning(f"⚠️  Kokoro failed: {e}")
    else:
        logger.warning("⚠️  Kokoro TTS not available")

    # Fallback: ElevenLabs (only if Kokoro unavailable/failed and ElevenLabs configured)
    if voiceover_result is None:
        elevenlabs = ElevenLabsTTS()
        if elevenlabs.available:
            logger.info("Falling back to ElevenLabs premium voice synthesis...")
            voiceover_result = elevenlabs.generate(full_text)
        else:
            raise RuntimeError(
                "❌ No voiceover engine available\n"
                "Install Kokoro with: pip install kokoro-onnx (and download the model files, see KokoroTTS docstring)\n"
                "Or configure ElevenLabs: set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env"
            )

    return {
        'status': 'success',
        'script': script,
        'voiceover': voiceover_result,
        'timestamp': datetime.now().isoformat()
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    # Test Kokoro availability
    print("Testing Kokoro TTS...")
    kokoro = KokoroTTS()
    print(f"Kokoro available: {kokoro.available}")
