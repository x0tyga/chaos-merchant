"""
Script + Voiceover Agent - Script generation and voice synthesis
Generates scripts for chaotic, high-energy viral moments across any topic
(gaming, golf, sports, internet culture) and produces voiceover audio
Primary: Kokoro TTS (free, local CPU)
"""

import base64
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
import tempfile

from anthropic import Anthropic

from core.cost_tracker import log_anthropic_usage

logger = logging.getLogger(__name__)

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("opencv-python not available - clip content analysis will be skipped (scripts fall back to metadata-only generation)")

SCRIPT_PROMPT_PATH = Path('./prompts/script_generation.txt')

DEFAULT_SCRIPT_INSTRUCTIONS = """You are writing a voiceover script for one specific clip from a longer
video. Your job is to react to what is actually in this clip - not to
generate generic excitement that could sit on top of any video.

Voice: a knowledgeable friend who just watched this exact clip and is
explaining why it is actually worth your attention. Think of a sports
commentator who explains the play - what happened, why it is hard, what
it means - not one who just yells over it. The energy comes from
specificity and pacing, not from hype words or exclamation points.

GTA 6 is the channel's current primary focus. When the clip is GTA 6
content, write for someone who follows the game: name the character, the
location, the mission, the mechanic - whatever the clip actually shows -
and explain why it matters to someone tracking this game.

HARD RULES - never break these:
1. The hook must reference something that literally happens in THIS
   specific clip: a character, a location, a mechanic, a detail. Never a
   generic opener that could introduce any video.
2. Never write a word in all capital letters. The text-to-speech engine
   reads all-caps words letter by letter and ruins the audio. Normal
   acronyms like GTA are fine.
3. Banned words and phrases - never use any of them: "crazy", "insane",
   "unhinged", "mind blowing", "mind-blowing", "you won't believe". If
   you are tempted to reach for one, write the specific detail that made
   you reach for it instead.
4. Short, punchy sentences - but every sentence carries real information.
   Cut any sentence that only adds energy without adding a fact.
5. The reaction must be earned by the content. If the clip shows
   something genuinely unusual, say exactly what is unusual about it and
   why. Do not manufacture excitement the clip does not support.

STRUCTURE:
1. Hook (0-3 seconds): the specific detail, stated plainly, that makes
   someone stop scrolling.
2. Body (3-30 seconds): explain what is happening and why it matters -
   the context a casual viewer would miss.
3. Close (last few seconds): a natural sign-off; a genuine question about
   the clip beats a generic subscribe plea.
4. Total: 120-180 words.

If a clip content description is provided below, treat it as the ground
truth of what is on screen - build the entire script from those
specifics. If no description is available, build from the clip's timing
and audio data and stay concrete; never invent specific events you cannot
know happened."""

# Words/phrases that must never reach the TTS engine or captions - the
# prompt above bans them, and this deterministic post-pass guarantees it
# even if the model slips. Replacements are deliberately neutral; every
# substitution is logged so a prompt that keeps producing banned words is
# visible rather than silently papered over.
BANNED_SCRIPT_PHRASES = [
    ("you won't believe", 'look at'),
    ('mind blowing', 'remarkable'),
    ('mind-blowing', 'remarkable'),
    ('unhinged', 'chaotic'),
    ('insane', 'remarkable'),
    ('crazy', 'wild'),
]

# All-caps words of this length or shorter are assumed to be real acronyms
# (GTA, VI, NPC, AI, TV...) and left alone - TTS spelling those out letter
# by letter is correct pronunciation. Longer all-caps words are shouting,
# which TTS also spells out letter by letter, ruining the audio.
MAX_ACRONYM_LENGTH = 3
ALL_CAPS_WHITELIST = {'LSPD', 'NPCS'}


def _sanitize_script_text(text: str) -> Tuple[str, List[str]]:
    """
    Deterministic enforcement of the two TTS-critical script rules, applied
    after every generation regardless of how well the model followed the
    prompt: (1) no all-caps words (read letter-by-letter by TTS), (2) no
    banned generic-hype words/phrases. Returns (clean_text, changes) where
    changes describes every substitution made, for logging.
    """
    if not text:
        return text, []

    changes = []

    def _fix_caps(match):
        word = match.group(0)
        if len(word) <= MAX_ACRONYM_LENGTH or word in ALL_CAPS_WHITELIST:
            return word
        fixed = word.capitalize()
        changes.append(f'all-caps "{word}" -> "{fixed}"')
        return fixed

    text = re.sub(r'\b[A-Z]{2,}\b', _fix_caps, text)

    for banned, replacement in BANNED_SCRIPT_PHRASES:
        def _replace(match):
            original = match.group(0)
            fixed = replacement.capitalize() if original[0].isupper() else replacement
            changes.append(f'banned "{original}" -> "{fixed}"')
            return fixed
        text = re.sub(re.escape(banned), _replace, text, flags=re.IGNORECASE)

    return text, changes


class ClipContentAnalyzer:
    """
    Extracts keyframes from one specific clip segment of the source video
    (OpenCV, already a core dependency) and asks Claude Haiku vision for a
    factual description of what is literally happening on screen - the
    ground truth the script generator reacts to, instead of generating
    blind from engagement scores alone. One vision call per clip.
    """

    NUM_FRAMES = 3
    MAX_FRAME_WIDTH = 768  # downscale before sending - keeps vision token cost low
    JPEG_QUALITY = 80

    def __init__(self):
        self.client = Anthropic()

    def describe_clip(self, source_video_path: str, start_time: float, end_time: float) -> Optional[str]:
        """Returns a factual description of the clip's content, or None if analysis isn't possible."""
        frames = self._extract_frames(source_video_path, start_time, end_time)
        if not frames:
            return None

        duration = end_time - start_time
        content = []
        for frame_b64 in frames:
            content.append({
                'type': 'image',
                'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': frame_b64}
            })
        content.append({
            'type': 'text',
            'text': (
                f"These are {len(frames)} frames sampled from the start, middle, and end "
                f"of a {duration:.0f}-second video clip. Describe factually what is "
                f"happening: who or what is on screen, the location or setting, any "
                f"visible game UI or mechanics, and what changes across the frames. "
                f"Name specific identifiable things (the game, characters, vehicles, "
                f"locations) when you are confident. 2-4 sentences of plain factual "
                f"observation - no hype, no speculation beyond what is visible."
            )
        })

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": content}]
            )
            log_anthropic_usage('clip_content_analysis', response)
            description = response.content[0].text.strip()
            logger.info(f"✓ Clip content described: {description[:100]}...")
            return description or None
        except Exception as e:
            logger.warning(f"⚠ Clip content analysis failed (script will generate from metadata only): {e}")
            return None

    def _extract_frames(self, source_video_path: str, start_time: float, end_time: float) -> List[str]:
        """Grabs NUM_FRAMES evenly spaced frames from [start_time, end_time] as base64 JPEGs."""
        if not CV2_AVAILABLE:
            logger.info("ℹ opencv-python unavailable, skipping clip content analysis")
            return []
        if not Path(source_video_path).exists():
            logger.warning(f"⚠ Source video not found for content analysis: {source_video_path}")
            return []

        cap = None
        try:
            cap = cv2.VideoCapture(str(source_video_path))
            duration = max(0.1, end_time - start_time)
            # Sample away from the exact edges - the first/last instants of
            # a scene-detected segment are often mid-transition frames.
            timestamps = [start_time + duration * f for f in (0.15, 0.5, 0.85)][:self.NUM_FRAMES]

            frames = []
            for ts in timestamps:
                cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000)
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                h, w = frame.shape[:2]
                if w > self.MAX_FRAME_WIDTH:
                    scale = self.MAX_FRAME_WIDTH / w
                    frame = cv2.resize(frame, (self.MAX_FRAME_WIDTH, int(h * scale)))
                ok, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.JPEG_QUALITY])
                if ok:
                    frames.append(base64.b64encode(buffer.tobytes()).decode('ascii'))

            logger.info(f"✓ Extracted {len(frames)} keyframes from clip ({start_time:.1f}s - {end_time:.1f}s) for content analysis")
            return frames
        except Exception as e:
            logger.warning(f"⚠ Keyframe extraction failed: {e}")
            return []
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass


def _load_script_instructions() -> str:
    """
    Reads tone/style/rules instructions from prompts/script_generation.txt
    if present - this is what the dashboard's Settings page edits to tune
    generated scripts without touching code. Falls back to
    DEFAULT_SCRIPT_INSTRUCTIONS if the file is missing or empty, so a
    fresh install (or an accidentally-emptied file) never breaks script
    generation. Per-clip data and the required JSON output schema are
    always appended in code afterward, never read from this file - an
    edit here can change tone/rules/vocabulary but can never break JSON
    parsing downstream by deleting the wrong line.
    """
    try:
        if SCRIPT_PROMPT_PATH.exists():
            content = SCRIPT_PROMPT_PATH.read_text().strip()
            if content:
                return content
    except Exception as e:
        logger.warning(f"⚠ Could not read script prompt template: {e}")
    return DEFAULT_SCRIPT_INSTRUCTIONS


class ScriptGenerator:
    """Generates YouTube Shorts scripts using Claude API"""

    def __init__(self):
        self.client = Anthropic()

    def _call_and_parse(self, prompt: str) -> dict:
        """
        Shared Claude call + JSON-extraction logic for both generate_script()
        (whole-video, legacy) and generate_script_for_clip() (per-clip).
        """
        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        log_anthropic_usage('script_voiceover', response)

        response_text = response.content[0].text

        try:
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
                'hook': 'Here is the moment worth watching.',
                'main_content': response_text[:200],
                'cta': 'Drop a like and subscribe for more!',
                'full_script': response_text,
                'reading_time_seconds': 40
            }

        # Deterministic enforcement of the TTS-critical rules (no all-caps
        # words, no banned hype words) on every text field that reaches the
        # TTS engine, captions, or hook library - the prompt asks for these
        # rules, this guarantees them even when the model slips.
        all_changes = []
        for field in ('hook', 'main_content', 'cta', 'full_script'):
            if isinstance(script_data.get(field), str):
                script_data[field], changes = _sanitize_script_text(script_data[field])
                all_changes.extend(changes)
        if all_changes:
            logger.warning(
                f"⚠ Script sanitizer corrected {len(all_changes)} rule violation(s) the model "
                f"produced despite the prompt: {'; '.join(all_changes)}"
            )

        return script_data

    def generate_script(self, clip_data, trending_topics=None, channel_history=None):
        """
        Generate ONE voiceover script for the whole video (legacy/whole-video
        mode). For per-clip scripts (each short gets its own unique hook and
        script matching what's actually on screen), use
        generate_script_for_clip() instead - this is what the pipeline uses.

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
            script_data = self._call_and_parse(prompt)
            logger.info(f"✓ Script generated ({script_data.get('reading_time_seconds', 0)}s)")
            return {
                'status': 'success',
                'script': script_data,
                'model': 'claude-haiku-4-5-20251001'
            }

        except Exception as e:
            logger.error(f"❌ Script generation failed: {e}")
            raise

    def generate_script_for_clip(self, clip_data, clip_index, trending_topics=None,
                                 channel_history=None, clip_description=None):
        """
        Generate a voiceover script scoped to ONE specific clip, not the
        whole source video - each of the 7 shorts gets its own hook/script
        matching that clip's actual content instead of one script shared
        (and mismatched) across all of them.

        Args:
            clip_data: A single clip dict from clip_manifest['clips']
                (start_time, end_time, duration, engagement_score, etc.)
            clip_index: This clip's position among the selected shorts (0-based)
            trending_topics: List of trending topics
            channel_history: Previous video summaries
            clip_description: Factual description of what is literally on
                screen in this clip (from ClipContentAnalyzer's keyframe
                vision pass) - the ground truth the script reacts to. When
                None, the prompt says so explicitly so the model stays
                concrete without inventing events it cannot know.

        Returns:
            dict: Generated script with metadata
        """
        logger.info(f"📝 Generating script for clip {clip_index + 1}...")

        if clip_description:
            content_section = f"""What is actually happening in this clip (ground truth from frame analysis):
{clip_description}"""
        else:
            content_section = (
                "No visual content description is available for this clip. Build the "
                "script from the timing and audio data below, stay concrete, and do "
                "not invent specific events you cannot know happened."
            )

        instructions = _load_script_instructions()
        prompt = f"""{instructions}

{content_section}

Clip data:
- Clip #{clip_index + 1}
- Duration: {clip_data.get('duration', 0):.1f} seconds
- Engagement score: {round(clip_data.get('engagement_score', 0), 2)} (0-1 scale)
- Scene change confidence: {round(clip_data.get('scene_change_confidence', 0), 2)}
- Audio energy: {round(clip_data.get('audio_features', {}).get('energy', 0), 2)}

Trending topics: {json.dumps(trending_topics or [], indent=2)}
Channel history: {json.dumps(channel_history or [], indent=2)}

Generate a JSON object with: hook, main_content, cta, full_script, reading_time_seconds"""

        try:
            script_data = self._call_and_parse(prompt)
            logger.info(f"✓ Script generated for clip {clip_index + 1} ({script_data.get('reading_time_seconds', 0)}s)")
            return {
                'status': 'success',
                'clip_index': clip_index,
                'script': script_data,
                'model': 'claude-haiku-4-5-20251001'
            }

        except Exception as e:
            logger.error(f"❌ Script generation failed for clip {clip_index + 1}: {e}")
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
        self.default_voice = os.getenv('KOKORO_VOICE', 'af_bella')
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

    def generate(self, text, voice=None, output_path=None):
        """
        Generate voiceover using Kokoro TTS

        Args:
            text: Text to synthesize
            voice: Voice name. Valid kokoro-onnx v1.0 voices: af_heart,
                af_bella, af_nicole, af_aoede, am_adam, am_michael,
                bf_emma, bm_george. Defaults to KOKORO_VOICE env var
                (default: af_bella) if not specified.
            output_path: Output WAV file path

        Returns:
            dict: Audio file path and metadata
        """
        if not self.available:
            raise RuntimeError("Kokoro TTS not available")

        if voice is None:
            voice = self.default_voice

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


def _synthesize_voiceover(full_text: str, output_path: str = None, label: str = '') -> dict:
    """
    Shared Kokoro-then-ElevenLabs fallback logic used by both
    generate_voiceover() (whole-video) and generate_voiceover_for_clip()
    (per-clip). Raises RuntimeError if neither engine is available -
    mirrors the exact check main.py's pre-flight verify_environment() uses.
    """
    voiceover_result = None
    kokoro = KokoroTTS()

    if kokoro.available:
        try:
            logger.info(f"Using Kokoro TTS (free, local voice synthesis){label}...")
            voiceover_result = kokoro.generate(full_text, output_path=output_path)
        except Exception as e:
            logger.warning(f"⚠️  Kokoro failed{label}: {e}")
    else:
        logger.warning(f"⚠️  Kokoro TTS not available{label}")

    if voiceover_result is None:
        elevenlabs = ElevenLabsTTS()
        if elevenlabs.available:
            logger.info(f"Falling back to ElevenLabs premium voice synthesis{label}...")
            voiceover_result = elevenlabs.generate(full_text, output_path=output_path)
        else:
            raise RuntimeError(
                f"❌ No voiceover engine available{label}\n"
                "Install Kokoro with: pip install kokoro-onnx (and download the model files, see KokoroTTS docstring)\n"
                "Or configure ElevenLabs: set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env"
            )

    return voiceover_result


def generate_voiceover(clip_data, trending_topics=None, channel_history=None):
    """
    Generate ONE script + voiceover for the whole video (legacy/whole-video
    mode). For per-clip voiceovers (each short gets its own script and
    audio matching what's actually on screen), use
    generate_voiceover_for_clip() instead - this is what the pipeline uses.
    Primary: Kokoro TTS (free, local). Fallback: ElevenLabs (if configured).

    Args:
        clip_data: Clip intelligence manifest
        trending_topics: Trending topics for context
        channel_history: Previous video data

    Returns:
        dict: Script + voiceover results
    """
    logger.info("🎬 Starting script + voiceover generation...")

    generator = ScriptGenerator()
    script_result = generator.generate_script(clip_data, trending_topics, channel_history)

    if script_result['status'] != 'success':
        raise RuntimeError("Script generation failed")

    script = script_result['script']
    full_text = script.get('full_script', '')
    voiceover_result = _synthesize_voiceover(full_text)

    return {
        'status': 'success',
        'script': script,
        'voiceover': voiceover_result,
        'timestamp': datetime.now().isoformat()
    }


def generate_voiceover_for_clip(clip_data, clip_index, trending_topics=None,
                                channel_history=None, source_video_path=None):
    """
    Generate a script + voiceover scoped to ONE specific clip. Each of the
    7 shorts calls this independently, producing its own hook/script and
    its own voice recording - matching what's actually on screen for that
    clip, instead of all 7 shorts sharing one script/audio file recorded
    about the source video as a whole.

    Args:
        clip_data: A single clip dict from clip_manifest['clips']
        clip_index: This clip's position among the selected shorts (0-based)
        trending_topics: Trending topics for context
        channel_history: Previous video data
        source_video_path: Path to the source video. When provided, this
            clip's segment gets a keyframe content analysis (one Haiku
            vision call) so the script reacts to what is literally on
            screen instead of generating blind from engagement scores.
            When None (or analysis fails), script generation proceeds
            from metadata only - degraded, not broken.

    Returns:
        dict: Script + voiceover results for this one clip, including the
        clip_description used (or None) so downstream consumers and
        debugging can see exactly what the script was reacting to.
    """
    logger.info(f"🎬 Starting script + voiceover generation for clip {clip_index + 1}...")

    clip_description = None
    if source_video_path:
        start_time = clip_data.get('start_time', 0)
        end_time = clip_data.get('end_time', clip_data.get('duration', 0))
        if end_time > start_time:
            analyzer = ClipContentAnalyzer()
            clip_description = analyzer.describe_clip(source_video_path, start_time, end_time)
        else:
            logger.warning(f"⚠ Clip {clip_index + 1} has invalid timing ({start_time} -> {end_time}), skipping content analysis")
    if clip_description is None:
        logger.info(f"ℹ Clip {clip_index + 1}: no content description available, generating script from metadata only")

    generator = ScriptGenerator()
    script_result = generator.generate_script_for_clip(
        clip_data, clip_index, trending_topics, channel_history,
        clip_description=clip_description
    )

    if script_result['status'] != 'success':
        raise RuntimeError(f"Script generation failed for clip {clip_index + 1}")

    script = script_result['script']
    full_text = script.get('full_script', '')
    output_path = f"/tmp/voiceover_clip{clip_index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
    voiceover_result = _synthesize_voiceover(full_text, output_path=output_path, label=f" (clip {clip_index + 1})")

    return {
        'status': 'success',
        'clip_index': clip_index,
        'script': script,
        'clip_description': clip_description,
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
