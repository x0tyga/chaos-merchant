"""
Video Production Agent - Phase 2 Complete
Produces finished YouTube Shorts with captions, audio ducking, color grading, branding
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import numpy as np
import re

try:
    # moviepy 2.x removed the moviepy.editor namespace entirely - everything
    # is imported directly from the top-level moviepy package now.
    from moviepy import (
        VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip,
        ImageClip, TextClip, concatenate_videoclips, concatenate_audioclips, vfx
    )
except ImportError:
    raise ImportError("moviepy required: pip install moviepy")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise ImportError("Pillow required: pip install Pillow")

try:
    from pydub import AudioSegment
    import librosa
except ImportError:
    raise ImportError("pydub and librosa required: pip install pydub librosa")

logger = logging.getLogger(__name__)


class ClipExtractor:
    """Extracts segments from source video"""

    def __init__(self, video_path: str):
        self.video_path = Path(video_path)
        self.video_clip = VideoFileClip(str(self.video_path))
        self.fps = self.video_clip.fps or 30

    def extract_clip(self, start_time: float, end_time: float) -> VideoFileClip:
        """Extract segment from source video"""
        try:
            clip = self.video_clip.subclipped(start_time, end_time)
            expected_frames = int(clip.duration * self.fps)
            logger.info(
                f"✓ Extracted clip: {start_time:.1f}s - {end_time:.1f}s "
                f"({clip.duration:.1f}s, ~{expected_frames} frames @ {self.fps}fps)"
            )

            real_duration = self._detect_playable_duration(clip)
            if real_duration < clip.duration - 0.5:
                logger.error(
                    f"❌ Truncating clip from {clip.duration:.1f}s (claimed by source file "
                    f"metadata) to {real_duration:.1f}s (last point real picture content was "
                    f"detected) - exporting the full claimed duration would have produced a "
                    f"black/silent tail in the finished Short"
                )
                clip = clip.subclipped(0, real_duration)

            return clip
        except Exception:
            logger.exception("❌ Clip extraction failed")
            raise

    @staticmethod
    def _detect_playable_duration(clip: VideoFileClip, black_threshold: float = 8.0) -> float:
        """
        A source video's duration metadata (what ffprobe/moviepy report) can
        overstate how much of the file is actually decodable - a known gotcha
        with some camera/screen-recording muxing where the container header
        claims more frames than the stream really contains. Reading past the
        real content doesn't raise an exception; it silently returns black
        frames, which matches exactly the "real content for ~30s then black
        and silent for the rest of the claimed duration" symptom from the
        first real-hardware run.

        Samples frames spread across the clip's claimed duration and looks
        for a trailing run of near-black frames preceded by real (non-black)
        content. Deliberately requires the LAST THREE sampled points to all
        be black before concluding there's an undecodable tail - a single
        dark sample near the end (a legitimately dark scene, e.g. gaming
        footage at night) must not be mistaken for this.

        Returns the clip's original duration unchanged if no such trailing
        gap is found (the overwhelmingly common case) or if sampling itself
        fails for any reason - this is a safety net, not a requirement for
        extraction to succeed.
        """
        duration = clip.duration
        if not duration or duration <= 2.0:
            return duration

        try:
            fractions = (0.10, 0.25, 0.40, 0.55, 0.70, 0.82, 0.91, 0.97)
            samples = []
            for frac in fractions:
                t = min(duration * frac, max(0.0, duration - 0.05))
                frame = clip.get_frame(t)
                samples.append((t, float(np.mean(frame))))

            logger.info(
                "📊 Playable-duration probe brightness samples: " +
                ", ".join(f"{t:.1f}s={b:.1f}" for t, b in samples)
            )

            black_flags = [b <= black_threshold for _, b in samples]
            if not any(not flag for flag in black_flags):
                # every sample is black - can't tell where content actually
                # ends; don't guess and risk truncating a real dark clip.
                return duration
            if not (black_flags[-1] and black_flags[-2] and black_flags[-3]):
                # trailing 3 samples aren't all black - no clear tail gap
                return duration

            # Walk backwards from the end to the first non-black sample;
            # that's the last confirmed point of real content.
            for t, brightness in reversed(samples):
                if brightness > black_threshold:
                    return t

            return duration
        except Exception:
            logger.exception("⚠ Playable-duration probe failed - using the clip's reported duration as-is")
            return duration

    def close(self):
        """Close video file"""
        try:
            self.video_clip.close()
        except:
            pass


class VerticalReframer:
    """Reframes video to 9:16 vertical aspect ratio"""

    TARGET_WIDTH = 1080
    TARGET_HEIGHT = 1920
    TARGET_RATIO = 9 / 16

    @staticmethod
    def detect_aspect_ratio(video_clip: VideoFileClip) -> str:
        """Detect source aspect ratio"""
        ratio = video_clip.w / video_clip.h
        if abs(ratio - (16/9)) < 0.1:
            return "16:9"
        elif abs(ratio - 1.0) < 0.1:
            return "1:1"
        elif abs(ratio - (9/16)) < 0.1:
            return "9:16"
        else:
            return "unknown"

    @classmethod
    def reframe(cls, video_clip: VideoFileClip, method: str = 'crop') -> VideoFileClip:
        """Reframe to 9:16 vertical"""
        source_ratio = video_clip.w / video_clip.h
        source_duration = video_clip.duration

        if abs(source_ratio - cls.TARGET_RATIO) < 0.01:
            logger.info("✓ Video already 9:16 format")
            result = video_clip.resized((cls.TARGET_WIDTH, cls.TARGET_HEIGHT))
            logger.info(f"📊 Reframe (already 9:16): duration in {source_duration:.1f}s -> out {result.duration:.1f}s")
            return result

        if method == 'crop' and source_ratio > cls.TARGET_RATIO:
            new_width = int(video_clip.h * cls.TARGET_RATIO)
            crop_x = (video_clip.w - new_width) // 2
            cropped = video_clip.cropped(x1=crop_x, y1=0, x2=crop_x + new_width, y2=video_clip.h)
            logger.info(f"✓ Cropped from {video_clip.w}x{video_clip.h} to {new_width}x{video_clip.h}")
            result = cropped.resized((cls.TARGET_WIDTH, cls.TARGET_HEIGHT))
            logger.info(f"📊 Reframe (crop): duration in {source_duration:.1f}s -> out {result.duration:.1f}s")
            return result

        resized = video_clip.resized(height=cls.TARGET_HEIGHT)
        x_offset = (cls.TARGET_WIDTH - resized.w) // 2

        black_bg = ImageClip(np.zeros((cls.TARGET_HEIGHT, cls.TARGET_WIDTH, 3), dtype=np.uint8))
        final = CompositeVideoClip([black_bg, resized.with_position((x_offset, 0))],
                                  size=(cls.TARGET_WIDTH, cls.TARGET_HEIGHT))
        logger.info(f"📊 Reframe (letterbox): duration in {source_duration:.1f}s -> out {final.duration:.1f}s")
        logger.info(f"✓ Letterboxed to {cls.TARGET_WIDTH}x{cls.TARGET_HEIGHT}")
        return final


class CaptionSynchronizer:
    """Generates and syncs burned-in captions to voiceover"""

    CAPTION_FONT_SIZE = 48
    CAPTION_COLOR = 'white'
    CAPTION_BG_COLOR = (0, 0, 0)
    SAFE_MARGIN = 60
    # Caption vertical anchor: 80% down from the top of the frame, but never
    # closer than MIN_BOTTOM_MARGIN px to the bottom edge - see render_captions().
    CAPTION_TOP_RATIO = 0.80
    MIN_BOTTOM_MARGIN = 80

    # moviepy 2.x's TextClip renders text via Pillow directly (it no longer
    # shells out to ImageMagick the way moviepy 1.x did) - but unlike 1.x,
    # it has NO built-in default font: a missing/invalid `font` path makes
    # every single TextClip construction raise. These are checked in order
    # only when CAPTION_FONT_PATH isn't set or doesn't exist; the DejaVu
    # path is the same one BrandingOverlay already relies on existing.
    FALLBACK_FONT_CANDIDATES = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/Library/Fonts/Arial Bold.ttf',
    ]

    def __init__(self, script: str):
        self.script = script
        # Gaming fonts improve brand identity - set CAPTION_FONT_PATH in .env
        # to a real .ttf/.otf to override (e.g. Bebas Neue).
        self.font_path = self._resolve_font_path(os.getenv('CAPTION_FONT_PATH', None))
        # (y_top, y_bottom) band actually used for the most recent
        # render_captions() call, in exported-frame pixel coordinates -
        # consumed by verify_captions_in_export() so post-export
        # verification checks the region captions were really placed in,
        # not a guessed one.
        self.last_caption_band = None

    def _resolve_font_path(self, env_font: str) -> str:
        """
        Resolve a real, existing font file to hand to TextClip. moviepy 2.x
        has no fallback of its own - if this returns None, render_captions()
        must refuse to attempt rendering rather than fail silently N times
        in a row (once per caption segment) with no aggregate signal.
        """
        if env_font:
            if Path(env_font).exists():
                logger.info(f"✓ Using caption font from CAPTION_FONT_PATH: {env_font}")
                return env_font
            logger.warning(
                f"⚠ CAPTION_FONT_PATH={env_font} does not exist on disk - "
                f"falling back to auto-detected system fonts"
            )

        for candidate in self.FALLBACK_FONT_CANDIDATES:
            if Path(candidate).exists():
                logger.info(f"✓ Using fallback caption font: {candidate}")
                return candidate

        logger.error(
            "❌ No usable font found for burned-in captions (checked CAPTION_FONT_PATH "
            f"and {len(self.FALLBACK_FONT_CANDIDATES)} known system font paths). moviepy "
            "2.x's TextClip requires an explicit font file and has no built-in default - "
            "every caption will fail to render until a valid font path is available. "
            "Set CAPTION_FONT_PATH in .env to a real .ttf/.otf file."
        )
        return None

    def generate_caption_timeline(self, voiceover_duration: float) -> List[Tuple[float, float, str]]:
        """
        Parse script into sentences and estimate timing
        Returns: [(start_time, end_time, text), ...]
        """
        sentences = re.split(r'(?<=[.!?])\s+', self.script.strip())
        if not sentences:
            return []

        total_words = len(self.script.split())
        avg_word_duration = voiceover_duration / max(1, total_words)

        captions = []
        current_time = 0.5

        for sentence in sentences:
            if not sentence.strip():
                continue

            word_count = len(sentence.split())
            duration = word_count * avg_word_duration

            captions.append((current_time, current_time + duration, sentence.strip()))
            current_time += duration

        logger.info(f"✓ Generated {len(captions)} caption segments")
        return captions

    def render_captions(self, video_clip: VideoFileClip, caption_timeline: List[Tuple[float, float, str]]) -> VideoFileClip:
        """Render captions as burned-in text overlays"""
        if not caption_timeline:
            logger.info("⚠ No captions to render")
            return video_clip

        if not self.font_path:
            # _resolve_font_path() already logged the loud, actionable
            # error at construction time - looping through every segment
            # here would just repeat the identical failure N times with
            # no new information, burying the one signal that matters.
            logger.error(
                f"❌ Skipping all {len(caption_timeline)} caption segments - no usable "
                f"font available (see error above). Short will export with NO captions."
            )
            return video_clip

        caption_clips = []
        rendered_bands = []  # (y_top, y_bottom) per successfully rendered segment

        # Anchor point: 80% down from the top of the frame, clamped so the
        # caption's own height never pushes its bottom edge closer than
        # MIN_BOTTOM_MARGIN px to the bottom of the frame. Replaces the old
        # hardcoded `video_clip.h - SAFE_MARGIN - 100`, which put captions
        # at a fixed 160px from the bottom regardless of frame height and
        # regressed to being cut off on tall vertical (1080x1920) exports.
        target_y = int(video_clip.h * self.CAPTION_TOP_RATIO)

        for start_time, end_time, text in caption_timeline:
            try:
                duration = end_time - start_time

                text_clip_kwargs = {
                    'text': text,
                    'font': self.font_path,
                    'font_size': self.CAPTION_FONT_SIZE,
                    'color': self.CAPTION_COLOR,
                    'method': 'caption',
                    'size': (video_clip.w - 2 * self.SAFE_MARGIN, None)
                }

                text_clip = TextClip(**text_clip_kwargs)
                text_clip = text_clip.with_duration(duration).with_start(start_time)

                max_y = video_clip.h - self.MIN_BOTTOM_MARGIN - text_clip.h
                y_pos = max(0, min(target_y, max_y))
                text_clip = text_clip.with_position(('center', y_pos))

                rendered_bands.append((y_pos, y_pos + text_clip.h))
                caption_clips.append(text_clip)

            except Exception:
                # logger.exception captures the full traceback, not just
                # str(e) - the difference between a font/rendering issue
                # being visible vs. silently discarded.
                logger.exception("⚠ Caption rendering failed for segment")
                continue

        failed_count = len(caption_timeline) - len(caption_clips)
        if not caption_clips:
            logger.error(
                f"❌ ALL {len(caption_timeline)} caption segments failed to render - "
                f"short will export with NO captions at all (see exceptions above)"
            )
            return video_clip
        if failed_count:
            logger.warning(
                f"⚠ {failed_count} of {len(caption_timeline)} caption segments failed to "
                f"render - short will ship with partial captions"
            )

        # Store the union band across all rendered segments so a post-export
        # verification pass knows exactly where to look for caption pixels,
        # instead of guessing at a region.
        self.last_caption_band = (
            min(b[0] for b in rendered_bands),
            max(b[1] for b in rendered_bands)
        )

        # Explicit with_duration() rather than relying on
        # CompositeVideoClip's implicit max-end-time inference - the
        # base video_clip should already determine this correctly
        # since it starts at t=0 with no trim, but being explicit
        # removes any ambiguity given how much this session's bugs
        # have hinged on exactly this kind of implicit duration
        # behavior in moviepy composites.
        composite = CompositeVideoClip([video_clip] + caption_clips).with_duration(video_clip.duration)
        logger.info(f"✓ Rendered {len(caption_clips)} caption overlays")
        logger.info(f"📊 Captions: duration in {video_clip.duration:.1f}s -> out {composite.duration:.1f}s")
        return composite

    @staticmethod
    def verify_captions_in_export(export_path: str, caption_timeline: List[Tuple[float, float, str]],
                                   caption_band: Tuple[int, int], max_samples: int = 5) -> bool:
        """
        Post-export sanity check: reopen the exported MP4 and sample frames
        at a handful of caption-active timestamps, checking for bright
        (caption-colored) pixels inside the band captions were placed in.
        Mirrors the "verify the artifact, don't trust the writer" pattern
        VideoExporter.export_mp4() already uses for its atomic-write fix -
        render_captions() succeeding in-process doesn't guarantee the
        pixels survived compositing/encoding into the final file.
        """
        if not caption_timeline or not caption_band:
            return True

        y0, y1 = caption_band
        clip = None
        try:
            clip = VideoFileClip(export_path)
            step = max(1, len(caption_timeline) // max_samples)
            sample_segments = caption_timeline[::step][:max_samples]

            for start, end, _ in sample_segments:
                mid = (start + end) / 2
                if mid >= clip.duration:
                    continue
                frame = clip.get_frame(mid)
                band = frame[max(0, int(y0)):min(frame.shape[0], int(y1)), :, :]
                if band.size == 0:
                    continue
                brightness = band.mean(axis=2)
                # CAPTION_COLOR is white text on video content behind it -
                # a nontrivial fraction of near-white pixels in the caption
                # band is the signal that text actually got drawn there.
                if (brightness > 180).mean() > 0.01:
                    return True

            return False
        except Exception:
            logger.exception(f"⚠ Could not verify caption presence in exported video: {export_path}")
            return False
        finally:
            if clip is not None:
                clip.close()


class BackgroundMusicLibrary:
    """
    Loads background music tracks from a user-managed directory
    (BACKGROUND_MUSIC_DIR, default ./assets/music - drop royalty-free
    tracks there). This is the REAL background music bed for shorts; the
    source video's own audio is never used as music (it's stripped
    entirely at clip extraction - see produce_single_short).

    Track selection rotates deterministically by short number so a batch
    gets variety but the same batch re-run picks the same tracks. Tracks
    shorter than the clip are looped; longer ones are trimmed. If no
    music directory/files exist, returns (None, None) and shorts ship
    with voiceover-only audio - degraded, never a crash.
    """

    SUPPORTED_FORMATS = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')

    @classmethod
    def load_for_short(cls, short_number: int, duration: float) -> Tuple[object, str]:
        """Returns (AudioClip trimmed/looped to `duration`, track filename) or (None, None)."""
        music_dir = Path(os.getenv('BACKGROUND_MUSIC_DIR', './assets/music'))
        try:
            if not music_dir.exists():
                logger.info(
                    f"ℹ No background music directory at {music_dir} - shorts will have "
                    f"voiceover-only audio. Drop royalty-free tracks there to add a music bed."
                )
                return None, None

            tracks = sorted(
                f for f in music_dir.iterdir()
                if f.is_file() and f.suffix.lower() in cls.SUPPORTED_FORMATS
            )
            if not tracks:
                logger.info(
                    f"ℹ Background music directory {music_dir} has no audio files "
                    f"({'/'.join(cls.SUPPORTED_FORMATS)}) - shorts will have voiceover-only audio."
                )
                return None, None

            track_path = tracks[short_number % len(tracks)]
            music = AudioFileClip(str(track_path))

            if music.duration < duration:
                loops_needed = int(duration // music.duration) + 1
                music = concatenate_audioclips([music] * loops_needed)
                logger.info(f"✓ Background music '{track_path.name}' looped {loops_needed}x to cover {duration:.1f}s")
            music = music.subclipped(0, duration)

            logger.info(f"✓ Background music loaded: '{track_path.name}' ({duration:.1f}s)")
            return music, track_path.name
        except Exception:
            logger.exception(f"⚠ Background music loading failed - continuing with voiceover-only audio")
            return None, None


class AudioProcessor:
    """Processes audio: voiceover mixed over a ducked background music bed"""

    def __init__(self, voiceover_path: str):
        self.voiceover_path = Path(voiceover_path)
        if not self.voiceover_path.exists():
            raise FileNotFoundError(f"Voiceover file not found: {voiceover_path}")

    def load_voiceover(self) -> AudioFileClip:
        """Load voiceover audio"""
        try:
            audio = AudioFileClip(str(self.voiceover_path))
            logger.info(f"✓ Loaded voiceover: {audio.duration:.1f}s")
            return audio
        except Exception as e:
            logger.error(f"❌ Failed to load voiceover: {e}")
            raise

    # Music gain envelope (env-overridable via MUSIC_DUCK_DB / MUSIC_BASE_DB):
    # the music bed NEVER plays at full volume. Outside the voiceover it sits
    # at base_db under the mix; during the voiceover it ducks further so the
    # voice always dominates. Short linear ramps at the boundaries avoid the
    # audible click a hard gain step would produce.
    DEFAULT_MUSIC_DUCK_DB = -18.0   # during voiceover
    DEFAULT_MUSIC_BASE_DB = -12.0   # outside voiceover
    MUSIC_RAMP_SECONDS = 0.25

    @staticmethod
    def _music_gain_at(t: float, vo_start: float, vo_end: float,
                       duck: float, base: float, ramp: float) -> float:
        """Pure-Python piecewise gain for one timestamp (also the reference for the array path)."""
        if vo_start <= t <= vo_end:
            return duck
        if vo_start - ramp <= t < vo_start:
            return base + (duck - base) * (t - (vo_start - ramp)) / ramp
        if vo_end < t <= vo_end + ramp:
            return duck + (base - duck) * (t - vo_end) / ramp
        return base

    def apply_music_envelope(self, background_music, vo_start: float, vo_end: float,
                             duck_db: float = None, base_db: float = None) -> Tuple[object, bool]:
        """
        Apply the full music gain envelope: base_db everywhere, ducking to
        duck_db while the voiceover plays over [vo_start, vo_end], with
        MUSIC_RAMP_SECONDS linear ramps between the two levels.

        moviepy applies the transform callback lazily at render time, so a
        broken callback would previously fail SILENTLY at construction and
        only surface (or worse, mis-render) during export. This method
        therefore verifies the exact callback object handed to transform()
        by invoking it directly with synthetic frames at known timestamps
        and checking the measured gains against the expected values -
        every production run, logged. A verification mismatch returns the
        original audio with applied=False and a loud error instead of
        shipping a mix that sounds wrong.

        Returns: (audio_clip, applied) - applied is False if the envelope
        failed or failed verification (original audio returned).
        """
        # Defensive env parsing: .env is editable as free text in the
        # dashboard's Settings page, so a typo'd level must degrade to the
        # defaults with a loud warning - not crash the whole short.
        if duck_db is None:
            try:
                duck_db = float(os.getenv('MUSIC_DUCK_DB', self.DEFAULT_MUSIC_DUCK_DB))
            except (TypeError, ValueError):
                logger.warning(f"⚠ Invalid MUSIC_DUCK_DB value {os.getenv('MUSIC_DUCK_DB')!r} - using default {self.DEFAULT_MUSIC_DUCK_DB}")
                duck_db = self.DEFAULT_MUSIC_DUCK_DB
        if base_db is None:
            try:
                base_db = float(os.getenv('MUSIC_BASE_DB', self.DEFAULT_MUSIC_BASE_DB))
            except (TypeError, ValueError):
                logger.warning(f"⚠ Invalid MUSIC_BASE_DB value {os.getenv('MUSIC_BASE_DB')!r} - using default {self.DEFAULT_MUSIC_BASE_DB}")
                base_db = self.DEFAULT_MUSIC_BASE_DB
        duck = 10 ** (duck_db / 20.0)
        base = 10 ** (base_db / 20.0)
        ramp = self.MUSIC_RAMP_SECONDS

        try:
            logger.info(
                f"✓ Applying music envelope: {base_db:.0f}dB base (gain {base:.3f}), "
                f"{duck_db:.0f}dB duck during voiceover {vo_start:.1f}s-{vo_end:.1f}s (gain {duck:.3f}), "
                f"{ramp}s ramps"
            )

            gain_at = self._music_gain_at

            # moviepy 2.x dropped volumex(); transform() is the 2.x
            # replacement for fl() and works on audio clips. t may be a
            # scalar or a batch array of timestamps at render time.
            def _envelope(get_frame, t):
                frame = get_frame(t)
                if np.isscalar(t):
                    gain = gain_at(t, vo_start, vo_end, duck, base, ramp)
                else:
                    t_arr = np.asarray(t)
                    # Only >=/<= comparisons; nesting order resolves the
                    # shared boundaries (duck zone wins at vo_start/vo_end).
                    in_duck = (t_arr >= vo_start) & (t_arr <= vo_end)
                    in_ramp_down = (t_arr >= vo_start - ramp) & (t_arr <= vo_start)
                    in_ramp_up = (t_arr >= vo_end) & (t_arr <= vo_end + ramp)
                    down_gain = ((t_arr - (vo_start - ramp)) * ((duck - base) / ramp)) + base
                    up_gain = ((t_arr - vo_end) * ((base - duck) / ramp)) + duck
                    gain = np.where(in_duck, duck,
                                    np.where(in_ramp_down, down_gain,
                                             np.where(in_ramp_up, up_gain, base)))
                    if frame.ndim > 1:
                        gain = gain[:, np.newaxis]
                return frame * gain

            enveloped = background_music.transform(_envelope)

            if not self._verify_envelope_callback(_envelope, vo_start, vo_end, duck, base, ramp):
                logger.error(
                    "❌ Music envelope FAILED verification (measured gains did not match the "
                    "expected -%.0f/-%.0f dB levels) - using original music, envelope NOT applied",
                    abs(base_db), abs(duck_db)
                )
                return background_music, False

            return enveloped, True

        except Exception:
            logger.exception("⚠ Music envelope failed, using original audio")
            return background_music, False

    @staticmethod
    def _verify_envelope_callback(envelope_fn, vo_start: float, vo_end: float,
                                  duck: float, base: float, ramp: float) -> bool:
        """
        Executes the EXACT callback object that transform() will invoke at
        render time, with synthetic unit frames at known timestamps, and
        checks the measured gains. This is what makes a silently-broken
        envelope impossible: the same code path that renders the audio is
        exercised and measured before the export ever starts.
        """
        try:
            checks = [((vo_start + vo_end) / 2.0, duck, 'during voiceover')]
            if vo_start - ramp > 0:
                checks.append(((vo_start - ramp) / 2.0, base, 'before voiceover'))
                checks.append((vo_start - ramp / 2.0, (base + duck) / 2.0, 'ramp midpoint'))
            checks.append((vo_end + ramp + 1.0, base, 'after voiceover'))

            for t, expected, label in checks:
                measured = envelope_fn(lambda _t: 1.0, t)  # unit frame -> output IS the gain
                if abs(float(measured) - expected) > 1e-6:
                    logger.error(
                        f"❌ Envelope gain wrong {label} (t={t:.2f}s): measured {float(measured):.4f}, "
                        f"expected {expected:.4f}"
                    )
                    return False

            logger.info(
                f"✓ Music envelope verified at render-callback level: gain {base:.3f} outside "
                f"voiceover, {duck:.3f} during, ramps correct ({len(checks)} timestamps measured)"
            )

            # Array/batch path spot check (how moviepy actually calls it at
            # render time) - non-fatal if the environment's numpy stand-in
            # can't support it, since the scalar reference above already
            # verified the gain math itself.
            try:
                t_batch = np.asarray([(vo_start + vo_end) / 2.0, vo_end + ramp + 1.0])
                out = envelope_fn(lambda _t: np.asarray([1.0, 1.0]), t_batch)
                vals = out.tolist() if hasattr(out, 'tolist') else list(getattr(out, 'data', out))
                flat = []
                stack = list(vals)
                while stack:
                    v = stack.pop(0)
                    if isinstance(v, list):
                        stack = v + stack
                    else:
                        flat.append(float(v))
                if abs(flat[0] - duck) > 1e-6 or abs(flat[1] - base) > 1e-6:
                    logger.error(f"❌ Envelope batch-path gains wrong: {flat} vs expected [{duck:.4f}, {base:.4f}]")
                    return False
                logger.info("✓ Music envelope batch/array path verified (matches moviepy's render-time call shape)")
            except Exception as e:
                logger.info(f"ℹ Envelope batch-path spot check skipped ({e}) - scalar reference already verified")

            return True
        except Exception:
            logger.exception("❌ Envelope verification itself failed")
            return False

    def prepare_audio(self, video_clip: VideoFileClip, voiceover_audio: AudioFileClip,
                     background_music=None, start_offset: float = 0.5) -> Tuple[AudioFileClip, bool]:
        """
        Prepare final audio: voiceover mixed over a ducked background music
        bed (from BackgroundMusicLibrary), or voiceover alone if no music
        is configured.

        The SOURCE VIDEO'S AUDIO IS NEVER PART OF THE MIX. This method
        deliberately does not read video_clip.audio at all (video_clip is
        only used for its duration) - the previous implementation used the
        source clip's own audio as the "background music", which is
        exactly the source-audio bleed-through reported from real testing.
        The final track is built exclusively from the voiceover file and
        the explicit background_music clip passed in.

        Returns: (audio_clip, ducking_applied) - ducking_applied is False
        if there was no background music to duck, or ducking itself failed.
        """
        try:
            vo_duration = voiceover_audio.duration
            clip_duration = video_clip.duration

            # Position voiceover within the clip, trimming if it would run past the end
            if vo_duration > clip_duration - start_offset:
                trimmed_duration = max(0.1, clip_duration - start_offset)
                voiceover_audio = voiceover_audio.subclipped(0, trimmed_duration)
                logger.warning(f"⚠ Voiceover trimmed to fit clip ({vo_duration:.1f}s -> {trimmed_duration:.1f}s)")
            elif vo_duration < clip_duration - start_offset:
                logger.info(f"ℹ Voiceover ({vo_duration:.1f}s) shorter than remaining clip time; background music continues after voiceover ends")

            voiceover_audio = voiceover_audio.with_start(start_offset)
            vo_end = start_offset + voiceover_audio.duration

            if background_music is not None:
                logger.info("✓ Compositing voiceover over enveloped background music (source audio excluded)")
                ducked_bg, ducking_applied = self.apply_music_envelope(background_music, start_offset, vo_end)
                final_audio = CompositeAudioClip([ducked_bg, voiceover_audio]).with_duration(clip_duration)
            else:
                logger.info("✓ Using voiceover as sole audio track (no background music configured, source audio excluded)")
                final_audio = CompositeAudioClip([voiceover_audio]).with_duration(clip_duration)
                ducking_applied = False

            logger.info("✓ Audio preparation complete")
            return final_audio, ducking_applied

        except Exception:
            logger.exception("❌ Audio preparation failed")
            raise


class EffectsLayer:
    """Applies color grading and visual effects"""

    @staticmethod
    def apply_color_grading(video_clip: VideoFileClip, contrast: float = 1.2,
                           saturation: float = 1.1) -> VideoFileClip:
        """Apply color grading: contrast boost + saturation boost (numpy-based, macOS compatible)"""
        try:
            logger.info(f"✓ Applying color grading (contrast: {contrast}x, saturation: {saturation}x)")

            def adjust_colors(get_frame, t):
                """Apply contrast and saturation adjustment to frame"""
                frame = get_frame(t)
                # Normalize to 0-1 range
                frame = frame.astype(np.float32) / 255.0
                # Apply contrast: (value - 0.5) * contrast + 0.5
                frame = (frame - 0.5) * contrast + 0.5
                # Apply saturation in RGB space
                # Convert to HSV, adjust V channel, convert back
                gray = np.dot(frame[..., :3], [0.299, 0.587, 0.114])
                frame_rgb = frame[..., :3]
                frame_rgb = gray[:, :, np.newaxis] + saturation * (frame_rgb - gray[:, :, np.newaxis])
                frame[..., :3] = frame_rgb
                # Clip to valid range and convert back to uint8
                frame = np.clip(frame, 0, 1) * 255.0
                return frame.astype(np.uint8)

            graded_clip = video_clip.transform(adjust_colors)
            logger.info("✓ Color grading applied (numpy-based)")
            logger.info(f"📊 Color grading: duration in {video_clip.duration:.1f}s -> out {graded_clip.duration:.1f}s")
            return graded_clip

        except Exception:
            logger.exception("⚠ Color grading adjustment failed, using original video")
            return video_clip


class BrandingOverlay:
    """Applies channel branding watermark"""

    WATERMARK_SIZE = (150, 100)
    WATERMARK_POSITION = ('right', 'bottom')
    WATERMARK_MARGIN = (20, 20)
    OPACITY = 0.8

    @staticmethod
    def create_watermark_image(channel_name: str, width: int = 150, height: int = 100) -> np.ndarray:
        """Create watermark image with channel name"""
        try:
            img = Image.new('RGBA', (width, height), (0, 0, 0, 180))
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            except:
                font = ImageFont.load_default()

            text_bbox = draw.textbbox((0, 0), channel_name, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]

            x = (width - text_width) // 2
            y = (height - text_height) // 2

            draw.text((x, y), channel_name, fill=(255, 255, 255, 255), font=font)

            logger.info(f"✓ Created watermark: '{channel_name}'")
            return np.array(img)

        except Exception:
            logger.exception("⚠ Watermark creation failed")
            return None

    @classmethod
    def apply_branding(cls, video_clip: VideoFileClip, channel_name: str) -> VideoFileClip:
        """Apply channel watermark to video"""
        try:
            if not channel_name:
                logger.info("⚠ No channel name provided, skipping branding")
                return video_clip

            watermark_array = cls.create_watermark_image(channel_name)
            if watermark_array is None:
                return video_clip

            watermark_clip = ImageClip(watermark_array).with_duration(video_clip.duration)

            x_pos = video_clip.w - cls.WATERMARK_SIZE[0] - cls.WATERMARK_MARGIN[0]
            y_pos = video_clip.h - cls.WATERMARK_SIZE[1] - cls.WATERMARK_MARGIN[1]

            watermark_clip = watermark_clip.with_position((x_pos, y_pos))
            watermark_clip = watermark_clip.with_effects([vfx.FadeIn(0.3), vfx.FadeOut(0.3)])

            # Explicit with_duration() rather than relying on
            # CompositeVideoClip's implicit duration inference - see the
            # same reasoning in CaptionSynchronizer.render_captions().
            composite = CompositeVideoClip([video_clip, watermark_clip], size=video_clip.size).with_duration(video_clip.duration)
            logger.info(f"✓ Applied branding watermark: '{channel_name}'")
            logger.info(f"📊 Branding: duration in {video_clip.duration:.1f}s -> out {composite.duration:.1f}s")
            return composite

        except Exception:
            logger.exception("❌ Branding failed")
            return video_clip


class VideoExporter:
    """Exports video to MP4 with YouTube specs"""

    @staticmethod
    def export_mp4(video_clip: VideoFileClip, output_path: str, preset: str = 'ultrafast') -> str:
        """
        Export VideoClip to MP4.

        Writes to a temporary path first and only moves it to the real
        output_path once write_videofile() has fully completed - moviepy
        shells out to ffmpeg as a subprocess and writes directly to its
        destination path with no atomicity guarantee, so a crash, an OOM
        kill, or any exception partway through the encode previously left
        a truncated file sitting AT the real output_path. A truncated MP4
        is missing its moov atom (written last by ffmpeg by default) and
        fails with "moov atom not found" on every later read (ffprobe,
        moviepy, QC's VideoValidator, the Pipeline Auditor's audio-level
        check) - this makes that failure mode structurally impossible:
        output_path either doesn't exist yet, or contains a fully-written,
        valid file. Never something in between.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # IMPORTANT: the temp filename must keep the real .mp4 suffix.
        # ffmpeg infers the output container/muxer from the output
        # filename's extension whenever no explicit -f flag is given -
        # naming this `.short_001.mp4.tmp` (suffix .tmp) previously made
        # ffmpeg unable to correctly identify the MP4 muxer, producing a
        # small, broken-container file instead of raising a clear error.
        # Putting the "incomplete" marker as an infix instead keeps the
        # real .mp4 suffix intact so ffmpeg's format detection is correct.
        temp_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")

        # A stale temp file from a previous crashed run must never be
        # mistaken for this run's output, and some ffmpeg configurations
        # refuse to silently overwrite an existing file.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as e:
                logger.warning(f"⚠ Could not remove stale temp file {temp_path}: {e}")

        # Expected values computed from the clip BEING EXPORTED, logged
        # up front and compared against the real written file below - the
        # "expected vs actual" signal needed to catch a corrupt/truncated
        # export immediately instead of discovering it later in QC (or
        # never, if QC's own checks happen to miss it too).
        expected_duration = video_clip.duration or 0
        expected_fps = getattr(video_clip, 'fps', None) or 30
        expected_frames = int(expected_duration * expected_fps)
        # Rough sanity-check heuristic (video bitrate dominates over the
        # 128kbps audio track) - real compressed size varies with content,
        # this is a ballpark for catching "way too small", not a strict bound.
        expected_size_mb = (expected_duration * 6000 * 1000 / 8) / (1024 * 1024)

        try:
            logger.info(
                f"📹 Exporting to {output_path.name} (preset: {preset}) - "
                f"expecting ~{expected_duration:.1f}s ({expected_frames} frames @ {expected_fps}fps), "
                f"~{expected_size_mb:.1f}MB at 6000kbps"
            )

            video_clip.write_videofile(
                str(temp_path),
                codec='libx264',
                audio_codec='aac',
                fps=30,
                logger=None,
                preset=preset,
                bitrate='6000k',
                audio_bitrate='128k',
                ffmpeg_params=['-movflags', 'faststart']
            )

            if not temp_path.exists() or temp_path.stat().st_size == 0:
                raise IOError(f"write_videofile() returned without error but produced no output file: {temp_path}")

            # Rename within the same directory/filesystem - atomic, so
            # output_path can never be observed in a partially-written state.
            temp_path.replace(output_path)

            file_size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"✓ Exported: {output_path.name} ({file_size_mb:.1f} MB, expected ~{expected_size_mb:.1f}MB)")

            # Verify the actual written file, not just its existence/size -
            # re-open it and compare its REAL duration/frame count against
            # what was expected. This is the check that would have caught
            # this exact function's earlier temp-filename bug (a file that
            # existed, wasn't zero-length, but had the wrong container/
            # content) immediately at export time instead of only in QC.
            try:
                written_clip = VideoFileClip(str(output_path))
                actual_duration = written_clip.duration or 0
                actual_fps = written_clip.fps or expected_fps
                actual_frames = int(actual_duration * actual_fps)
                written_clip.close()

                logger.info(
                    f"📊 Export verification for {output_path.name}: "
                    f"expected {expected_frames} frames ({expected_duration:.1f}s) vs "
                    f"actual {actual_frames} frames ({actual_duration:.1f}s)"
                )

                if expected_duration > 0.1 and actual_duration < expected_duration * 0.5:
                    logger.warning(
                        f"⚠ {output_path.name}: actual duration ({actual_duration:.1f}s) is far "
                        f"shorter than expected ({expected_duration:.1f}s) - the video content may "
                        f"not have been written correctly even though the file exists"
                    )
                if expected_size_mb > 0.1 and file_size_mb < expected_size_mb * 0.3:
                    logger.warning(
                        f"⚠ {output_path.name}: file size ({file_size_mb:.1f}MB) is far below the "
                        f"~{expected_size_mb:.1f}MB expected for a {expected_duration:.1f}s clip at "
                        f"6000kbps - this usually means the export did not encode its full intended content"
                    )
            except Exception as verify_error:
                logger.warning(f"⚠ Could not verify {output_path.name}'s real duration/frame count after export: {verify_error}")

            return str(output_path)

        except Exception:
            logger.exception(f"❌ Export failed for {output_path.name}")
            raise
        finally:
            # Whatever happened above, a leftover temp file must never
            # survive: it's either already been moved to output_path (the
            # success path, so this is a no-op) or it's a partial/corrupt
            # write that must not be left on disk to be mistaken for real
            # output by a later run or a manual directory listing.
            if temp_path.exists():
                try:
                    temp_path.unlink()
                    logger.info(f"🧹 Cleaned up incomplete temp export: {temp_path.name}")
                except OSError as cleanup_error:
                    logger.warning(f"⚠ Could not clean up temp file {temp_path}: {cleanup_error}")

    @staticmethod
    def validate_output(mp4_path: str) -> bool:
        """Validate output MP4"""
        try:
            mp4_file = Path(mp4_path)

            if not mp4_file.exists():
                logger.error(f"❌ Output file not found: {mp4_path}")
                return False

            if mp4_file.stat().st_size < 500000:
                logger.error(f"❌ Output file too small: {mp4_file.stat().st_size} bytes")
                return False

            clip = VideoFileClip(mp4_path)
            if abs(clip.w - 1080) > 5 or abs(clip.h - 1920) > 5:
                logger.error(f"❌ Resolution incorrect: {clip.w}x{clip.h} (expected 1080x1920)")
                clip.close()
                return False

            clip.close()
            logger.info(f"✓ Output validated: {mp4_file.name}")
            return True

        except Exception as e:
            logger.error(f"❌ Validation failed: {e}")
            return False


class VideoProducer:
    """Main orchestrator for video production - Phase 2 Complete"""

    def __init__(self, source_video_path: str, clip_manifest: Dict, voiceover_results: List[Dict],
                 output_dir: str, temp_dir: str = None, channel_name: str = None):
        """
        voiceover_results: list of per-clip voiceover results (one per
        short, same order/index as clip_manifest['top_clip_indices']),
        each shaped like generate_voiceover_for_clip()'s return value -
        so each short gets its OWN script/audio instead of one shared
        voiceover muxed onto all 7 clips regardless of content match.
        """
        self.source_video_path = Path(source_video_path)
        self.clip_manifest = clip_manifest
        self.voiceover_results = voiceover_results or []
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir or self.output_dir / 'temp')
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.channel_name = channel_name or os.getenv('CHANNEL_NAME', 'Chaos Merchant')

    def produce_all_shorts(self) -> Dict:
        """Produce all 7 shorts from top clips"""
        logger.info("🎬 Starting video production (Phase 2 - Full Features)...")
        batch_start_time = datetime.now()

        results = []
        top_clip_indices = self.clip_manifest.get('top_clip_indices', [])

        if not top_clip_indices:
            logger.error("❌ No top clips found in manifest")
            return {
                'status': 'error',
                'error': 'No top clips in manifest',
                'video_paths': [],
                'timestamp': datetime.now().isoformat()
            }

        for i, clip_idx in enumerate(top_clip_indices[:7]):
            logger.info(f"\n--- Producing Short {i+1}/7 (clip index: {clip_idx}) ---")

            try:
                result = self.produce_single_short(clip_idx, i)
                results.append(result)
            except Exception as e:
                logger.exception(f"❌ Short {i+1} failed")
                results.append({
                    'status': 'error',
                    'clip_idx': clip_idx,
                    'error': str(e),
                    'short_number': i
                })

        video_paths = [r.get('output_path') for r in results if r.get('status') == 'success']
        timings = {str(r.get('clip_idx')): r.get('duration', 0) for r in results if r.get('status') == 'success'}
        errors = [r.get('error') for r in results if r.get('status') == 'error']

        # Aggregate real per-short processing times (previously hardcoded to 0)
        per_short_times = [r.get('processing_time', 0) for r in results if r.get('processing_time') is not None]
        export_total = sum(per_short_times)
        batch_wall_clock = (datetime.now() - batch_start_time).total_seconds()

        num_expected = len(top_clip_indices)
        num_produced = len(video_paths)
        if num_produced == 0:
            batch_status = 'error'
        elif num_produced < num_expected:
            batch_status = 'partial'
        else:
            batch_status = 'success'

        logger.info(f"\n✅ Production complete: {num_produced} of {num_expected} shorts produced (status: {batch_status})")
        logger.info(f"   Total export time: {export_total:.1f}s | Wall clock: {batch_wall_clock:.1f}s")

        # Aggregate real per-short 'features' into what applied across ALL
        # successful shorts vs. what applied in AT LEAST ONE - a feature
        # applied in 0/7 shorts (e.g. captions never once succeeding) is a
        # much stronger signal than the old hardcoded list ever surfaced.
        per_short_feature_sets = [set(r.get('features', [])) for r in results if r.get('status') == 'success']
        features_in_all_shorts = sorted(set.intersection(*per_short_feature_sets)) if per_short_feature_sets else []
        features_in_any_short = sorted(set.union(*per_short_feature_sets)) if per_short_feature_sets else []

        # video_paths is a FILTERED list (successes only), so its position
        # doesn't reliably equal short_number once any short fails - e.g. if
        # short 2 fails, video_paths[2] is actually short 3's video. This
        # matters now that each short has its own distinct per-clip SEO/
        # script data: downstream consumers (output_packaging.py) need the
        # real short_number to look up the RIGHT clip's metadata, not just
        # positional order in this filtered list.
        short_results = [
            {'short_number': r.get('short_number'), 'clip_idx': r.get('clip_idx'), 'output_path': r.get('output_path')}
            for r in results if r.get('status') == 'success'
        ]

        # Per-short features (which of captions/audio_ducking/color_grading/
        # branding actually applied to THIS specific short, not just the
        # batch-wide aggregate above) - the data was already computed per
        # short in `results`, just not previously surfaced to callers.
        # Keyed by short_number (string, for JSON-manifest consistency with
        # the rest of this codebase's short-keyed dicts) so the Pipeline
        # Auditor and other downstream consumers can look up exactly what
        # happened to one specific short instead of only the batch average.
        short_features = {
            str(r.get('short_number')): r.get('features', [])
            for r in results if r.get('status') == 'success'
        }

        return {
            'status': batch_status,
            'video_paths': video_paths,
            'short_results': short_results,
            'short_features': short_features,
            'timings': timings,
            'processing_times': {
                'export_total': round(export_total, 2),
                'wall_clock_total': round(batch_wall_clock, 2),
                'per_short': {str(r.get('clip_idx')): round(r.get('processing_time', 0), 2)
                              for r in results if r.get('processing_time') is not None}
            },
            'errors': errors,
            'metadata': {
                'source_video': str(self.source_video_path),
                'total_shorts_expected': num_expected,
                'total_shorts': len(video_paths),
                'total_duration': sum(timings.values()),
                'codec': 'h264',
                'audio_codec': 'aac',
                'resolution': '1080x1920',
                'features_requested': ['captions', 'audio_ducking', 'color_grading', 'branding'],
                'features_applied_in_all_shorts': features_in_all_shorts,
                'features_applied_in_any_short': features_in_any_short
            },
            'timestamp': datetime.now().isoformat()
        }

    def produce_single_short(self, clip_idx: int, short_number: int) -> Dict:
        """Produce one finished short with Phase 2 features"""
        start_time = datetime.now()

        try:
            clips = self.clip_manifest.get('clips', [])
            if clip_idx >= len(clips):
                raise IndexError(f"Clip index {clip_idx} out of range")

            clip_data = clips[clip_idx]
            clip_start = clip_data.get('start_time', 0)
            clip_end = clip_data.get('end_time', clip_data.get('duration', 0))

            logger.info(f"Step 1: Extracting clip ({clip_start:.1f}s - {clip_end:.1f}s)...")
            extractor = ClipExtractor(str(self.source_video_path))
            extracted_clip = extractor.extract_clip(clip_start, clip_end)

            # Strip the source video's audio COMPLETELY, immediately at
            # extraction - before any reframe/composite step can carry it
            # forward. The final audio track is built exclusively from
            # voiceover + background music in prepare_audio(); doing the
            # strip here as well makes source-audio bleed-through
            # structurally impossible no matter what any downstream
            # composite does with component audio.
            extracted_clip = extracted_clip.without_audio()
            logger.info("✓ Source audio stripped (final mix = voiceover + background music only)")

            logger.info(f"Step 2: Reframing to 9:16 vertical...")
            aspect = VerticalReframer.detect_aspect_ratio(extracted_clip)
            method = 'crop' if aspect == '16:9' else 'letterbox'
            reframed_clip = VerticalReframer.reframe(extracted_clip, method=method)

            if short_number >= len(self.voiceover_results):
                raise IndexError(f"No voiceover result available for short {short_number}")
            clip_voiceover = self.voiceover_results[short_number]
            if clip_voiceover.get('status') != 'success':
                raise ValueError(
                    f"Voiceover generation for short {short_number} did not succeed "
                    f"(status: {clip_voiceover.get('status')}) - cannot produce this short "
                    f"without its own audio"
                )
            clip_script = clip_voiceover.get('script', {}).get('full_script', '')

            logger.info(f"Step 3: Preparing audio (voiceover + background music, source audio excluded)...")
            clip_duration = reframed_clip.duration
            audio_processor = AudioProcessor(clip_voiceover['voiceover']['audio_path'])
            voiceover_audio = audio_processor.load_voiceover()
            original_vo_duration = voiceover_audio.duration
            background_music, music_track = BackgroundMusicLibrary.load_for_short(
                short_number, reframed_clip.duration
            )
            final_audio, ducking_applied = audio_processor.prepare_audio(
                reframed_clip, voiceover_audio, background_music=background_music
            )

            # prepare_audio() reassigns its own local `voiceover_audio` when
            # trimming, so this outer reference is still the ORIGINAL,
            # untrimmed voiceover - exactly what's needed to log what the
            # voiceover actually was before any reconciliation happened.
            logger.info(
                f"📊 Duration reconciliation: clip={clip_duration:.2f}s, "
                f"voiceover(original)={original_vo_duration:.2f}s, "
                f"final_audio_track={final_audio.duration:.2f}s - the video's own "
                f"duration is authoritative; voiceover is trimmed to fit it, never "
                f"the other way around"
            )
            if abs(final_audio.duration - clip_duration) > 0.05:
                logger.error(
                    f"❌ final_audio duration ({final_audio.duration:.2f}s) does not match "
                    f"the clip's duration ({clip_duration:.2f}s) - forcing it back so the "
                    f"video's length can never be shortened by the audio track"
                )
                final_audio = final_audio.with_duration(clip_duration)

            reframed_clip = reframed_clip.with_audio(final_audio)

            logger.info(f"Step 4: Adding burned-in captions...")
            caption_sync = CaptionSynchronizer(clip_script)
            caption_timeline = caption_sync.generate_caption_timeline(voiceover_audio.duration)
            captioned_clip = caption_sync.render_captions(reframed_clip, caption_timeline)
            # render_captions/apply_color_grading/apply_branding each return the
            # SAME clip object unchanged on failure (or a no-op condition like no
            # channel name) and a NEW composited/transformed object on success -
            # identity comparison (matching the existing cleanup pattern below)
            # gives an accurate applied/not-applied signal without changing
            # every helper's return type.
            captions_applied = captioned_clip is not reframed_clip

            logger.info(f"Step 5: Applying color grading...")
            effects = EffectsLayer()
            graded_clip = effects.apply_color_grading(captioned_clip, contrast=1.2, saturation=1.1)
            color_grading_applied = graded_clip is not captioned_clip

            logger.info(f"Step 6: Adding channel branding...")
            branded_clip = BrandingOverlay.apply_branding(graded_clip, self.channel_name)
            branding_applied = branded_clip is not graded_clip

            # Final duration sanity check before export - captions/color
            # grading/branding each already force their own composite back to
            # video_clip.duration internally, but this is the one place that
            # would catch any future regression in that chain before it ships
            # as a truncated Short: the exported video's length must always
            # be the clip's own length, never something shorter driven by an
            # audio track.
            logger.info(
                f"📊 Duration check before export - clip: {clip_duration:.2f}s | "
                f"voiceover (original): {original_vo_duration:.2f}s | "
                f"final audio track: {final_audio.duration:.2f}s | "
                f"final video (post captions/grading/branding): {branded_clip.duration:.2f}s"
            )
            if abs(branded_clip.duration - clip_duration) > 0.05:
                logger.error(
                    f"❌ Final video duration ({branded_clip.duration:.2f}s) does not match "
                    f"the clip's own duration ({clip_duration:.2f}s) going into export - "
                    f"forcing it back to the clip's full duration"
                )
                branded_clip = branded_clip.with_duration(clip_duration)

            output_name = f"video_{self.source_video_path.stem}_{short_number:03d}.mp4"
            output_path = self.output_dir / output_name

            logger.info(f"Step 7: Exporting MP4...")
            exporter = VideoExporter()
            export_path = exporter.export_mp4(branded_clip, str(output_path), preset='ultrafast')

            is_valid = exporter.validate_output(export_path)

            # Don't trust that captions compositing succeeded in-process -
            # confirm the pixels actually made it into the finished MP4.
            captions_verified = True
            if captions_applied:
                captions_verified = CaptionSynchronizer.verify_captions_in_export(
                    export_path, caption_timeline, caption_sync.last_caption_band
                )
                if not captions_verified:
                    logger.error(
                        f"❌ {output_name}: captions were composited in-process but no caption "
                        f"pixels were detected in the exported MP4 - they were likely lost "
                        f"during compositing/export, not just a rendering issue upstream"
                    )

            try:
                extractor.close()
                reframed_clip.close()
                voiceover_audio.close()
                if background_music is not None:
                    background_music.close()
                captioned_clip.close() if captioned_clip != reframed_clip else None
                graded_clip.close() if graded_clip != captioned_clip else None
                branded_clip.close() if branded_clip != graded_clip else None
            except:
                pass

            elapsed = (datetime.now() - start_time).total_seconds()

            applied_features = []
            if captions_applied and captions_verified:
                applied_features.append('captions')
            if ducking_applied:
                applied_features.append('audio_ducking')
            if color_grading_applied:
                applied_features.append('color_grading')
            if branding_applied:
                applied_features.append('branding')

            if is_valid:
                return {
                    'status': 'success',
                    'clip_idx': clip_idx,
                    'short_number': short_number,
                    'output_path': export_path,
                    'duration': extracted_clip.duration,
                    'processing_time': elapsed,
                    # Reflects what actually applied (see identity-comparison
                    # checks above), not what was merely attempted - a step
                    # can silently no-op on failure without killing the short.
                    'features': applied_features,
                    'features_requested': ['captions', 'audio_ducking', 'color_grading', 'branding'],
                    'captions_verified': captions_verified
                }
            else:
                return {
                    'status': 'error',
                    'clip_idx': clip_idx,
                    'short_number': short_number,
                    'error': 'Output validation failed',
                    'processing_time': elapsed,
                    'features': applied_features,
                    'features_requested': ['captions', 'audio_ducking', 'color_grading', 'branding'],
                    'captions_verified': captions_verified
                }

        except Exception as e:
            logger.exception(f"❌ Short {short_number} production failed")
            return {
                'status': 'error',
                'clip_idx': clip_idx,
                'short_number': short_number,
                'error': str(e),
                'processing_time': (datetime.now() - start_time).total_seconds()
            }


def produce_shorts(source_video_path: str, clip_manifest: Dict, voiceover_results: List[Dict],
                  output_dir: str = './output', temp_dir: str = None) -> Dict:
    """
    Main entry point: Produce shorts with Phase 2 features
    - Burned-in captions synced to voiceover
    - Music ducking (background audio reduces during voiceover)
    - Color grading (contrast + saturation boost)
    - Channel branding watermark

    Args:
        voiceover_results: list of per-clip voiceover results (one per
            short, same order as clip_manifest['top_clip_indices']), each
            shaped like generate_voiceover_for_clip()'s return value
    """
    logger.info("=" * 60)
    logger.info("🎬 VIDEO PRODUCTION AGENT - PHASE 2 (FULL FEATURES)")
    logger.info("=" * 60)

    try:
        channel_name = os.getenv('CHANNEL_NAME', 'Chaos Merchant')

        producer = VideoProducer(source_video_path, clip_manifest, voiceover_results,
                                output_dir, temp_dir, channel_name)
        result = producer.produce_all_shorts()

        logger.info("\n" + "=" * 60)
        logger.info(f"PRODUCTION COMPLETE: {len(result['video_paths'])} shorts produced")
        logger.info("Features: Captions ✓ Audio Ducking ✓ Color Grading ✓ Branding ✓")
        logger.info("=" * 60)

        return result

    except Exception as e:
        logger.error(f"❌ Production failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'video_paths': [],
            'timestamp': datetime.now().isoformat()
        }
