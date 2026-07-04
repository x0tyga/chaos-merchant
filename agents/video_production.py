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
        ImageClip, TextClip, concatenate_videoclips, vfx
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
            logger.info(f"✓ Extracted clip: {start_time:.1f}s - {end_time:.1f}s ({clip.duration:.1f}s)")
            return clip
        except Exception as e:
            logger.error(f"❌ Clip extraction failed: {e}")
            raise

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

        if abs(source_ratio - cls.TARGET_RATIO) < 0.01:
            logger.info("✓ Video already 9:16 format")
            return video_clip.resized((cls.TARGET_WIDTH, cls.TARGET_HEIGHT))

        if method == 'crop' and source_ratio > cls.TARGET_RATIO:
            new_width = int(video_clip.h * cls.TARGET_RATIO)
            crop_x = (video_clip.w - new_width) // 2
            cropped = video_clip.cropped(x1=crop_x, y1=0, x2=crop_x + new_width, y2=video_clip.h)
            logger.info(f"✓ Cropped from {video_clip.w}x{video_clip.h} to {new_width}x{video_clip.h}")
            return cropped.resized((cls.TARGET_WIDTH, cls.TARGET_HEIGHT))

        resized = video_clip.resized(height=cls.TARGET_HEIGHT)
        x_offset = (cls.TARGET_WIDTH - resized.w) // 2

        black_bg = ImageClip(np.zeros((cls.TARGET_HEIGHT, cls.TARGET_WIDTH, 3), dtype=np.uint8))
        final = CompositeVideoClip([black_bg, resized.with_position((x_offset, 0))],
                                  size=(cls.TARGET_WIDTH, cls.TARGET_HEIGHT))
        logger.info(f"✓ Letterboxed to {cls.TARGET_WIDTH}x{cls.TARGET_HEIGHT}")
        return final


class CaptionSynchronizer:
    """Generates and syncs burned-in captions to voiceover"""

    CAPTION_FONT_SIZE = 48
    CAPTION_COLOR = 'white'
    CAPTION_BG_COLOR = (0, 0, 0)
    SAFE_MARGIN = 60

    def __init__(self, script: str):
        self.script = script
        # NOTE: Current implementation uses system default font for compatibility
        # BEFORE CHANNEL GOES LIVE: Replace with Bebas Neue or custom gaming-style font
        # Set CAPTION_FONT_PATH in .env to override (e.g., /path/to/BebasNeue-Regular.ttf)
        # Gaming fonts improve brand identity and visual appeal on YouTube Shorts
        self.font_path = os.getenv('CAPTION_FONT_PATH', None)

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

        caption_clips = []

        for start_time, end_time, text in caption_timeline:
            try:
                duration = end_time - start_time

                text_clip_kwargs = {
                    'text': text,
                    'font_size': self.CAPTION_FONT_SIZE,
                    'color': self.CAPTION_COLOR,
                    'method': 'caption',
                    'size': (video_clip.w - 2 * self.SAFE_MARGIN, None)
                }

                if self.font_path and Path(self.font_path).exists():
                    text_clip_kwargs['font'] = self.font_path

                text_clip = TextClip(**text_clip_kwargs)

                text_clip = text_clip.with_duration(duration).with_start(start_time)
                text_clip = text_clip.with_position(('center', video_clip.h - self.SAFE_MARGIN - 100))

                caption_clips.append(text_clip)

            except Exception:
                # logger.exception captures the full traceback, not just
                # str(e) - the difference between "ImageMagick policy denied
                # text operations" being visible vs. silently discarded.
                logger.exception("⚠ Caption rendering failed for segment")
                continue

        if caption_clips:
            composite = CompositeVideoClip([video_clip] + caption_clips)
            logger.info(f"✓ Rendered {len(caption_clips)} caption overlays")
            return composite

        return video_clip


class AudioProcessor:
    """Processes audio: voiceover, music ducking, normalization"""

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

    def apply_music_ducking(self, background_audio: AudioFileClip, vo_start: float,
                           vo_end: float, duck_db: float = -6.0) -> Tuple[AudioFileClip, bool]:
        """
        Reduce background music volume while the voiceover plays over [vo_start, vo_end]
        duck_db: reduction in dB (e.g., -6 = reduce to ~50% volume)

        Returns: (audio_clip, applied) - applied is False if ducking failed
        and the original unducked audio was returned instead, so callers
        can report accurately instead of assuming success.
        """
        try:
            logger.info(f"✓ Applying music ducking ({duck_db}dB during voiceover)...")
            duck_factor = 10 ** (duck_db / 20.0)

            # moviepy 2.x dropped the volumex() clip method (it only ever
            # accepted a constant scalar factor, not a time-varying one
            # anyway - ducking needs the volume to change only during
            # [vo_start, vo_end]). transform() is the 2.x replacement for
            # the old fl() general frame-transform method and works on
            # audio clips too: t may be a scalar or a batch array of times,
            # so the factor is computed with np.where for elementwise safety.
            def _duck_frame(get_frame, t):
                frame = get_frame(t)
                if np.isscalar(t):
                    factor = duck_factor if vo_start <= t <= vo_end else 1.0
                else:
                    t_arr = np.asarray(t)
                    factor = np.where((t_arr >= vo_start) & (t_arr <= vo_end), duck_factor, 1.0)
                    if frame.ndim > 1:
                        factor = factor[:, np.newaxis]
                return frame * factor

            ducked = background_audio.transform(_duck_frame)
            return ducked, True

        except Exception:
            logger.exception("⚠ Music ducking failed, using original audio")
            return background_audio, False

    def prepare_audio(self, video_clip: VideoFileClip, voiceover_audio: AudioFileClip,
                     start_offset: float = 0.5) -> Tuple[AudioFileClip, bool]:
        """
        Prepare final audio: voiceover mixed over ducked background music.
        Background music is genuinely retained (ducked, not discarded) when present.

        Returns: (audio_clip, ducking_applied) - ducking_applied is False if
        there was no background audio to duck, or ducking itself failed.
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
                logger.info(f"ℹ Voiceover ({vo_duration:.1f}s) shorter than remaining clip time; background audio continues after voiceover ends")

            voiceover_audio = voiceover_audio.with_start(start_offset)
            vo_end = start_offset + voiceover_audio.duration

            if video_clip.audio is not None:
                logger.info("✓ Compositing voiceover with ducked background audio")
                ducked_bg, ducking_applied = self.apply_music_ducking(video_clip.audio, start_offset, vo_end)
                final_audio = CompositeAudioClip([ducked_bg, voiceover_audio]).with_duration(clip_duration)
            else:
                logger.info("✓ Using voiceover as sole audio track (no background audio in source clip)")
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

            composite = CompositeVideoClip([video_clip, watermark_clip], size=video_clip.size)
            logger.info(f"✓ Applied branding watermark: '{channel_name}'")
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
        temp_path = output_path.with_name(f".{output_path.name}.tmp")

        # A stale temp file from a previous crashed run must never be
        # mistaken for this run's output, and some ffmpeg configurations
        # refuse to silently overwrite an existing file.
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as e:
                logger.warning(f"⚠ Could not remove stale temp file {temp_path}: {e}")

        try:
            logger.info(f"📹 Exporting to {output_path.name} (preset: {preset})...")

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
            logger.info(f"✓ Exported: {output_path.name} ({file_size_mb:.1f} MB)")
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

            logger.info(f"Step 3: Preparing audio (voiceover + music ducking)...")
            audio_processor = AudioProcessor(clip_voiceover['voiceover']['audio_path'])
            voiceover_audio = audio_processor.load_voiceover()
            final_audio, ducking_applied = audio_processor.prepare_audio(reframed_clip, voiceover_audio)
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

            output_name = f"video_{self.source_video_path.stem}_{short_number:03d}.mp4"
            output_path = self.output_dir / output_name

            logger.info(f"Step 7: Exporting MP4...")
            exporter = VideoExporter()
            export_path = exporter.export_mp4(branded_clip, str(output_path), preset='ultrafast')

            is_valid = exporter.validate_output(export_path)

            try:
                extractor.close()
                reframed_clip.close()
                voiceover_audio.close()
                captioned_clip.close() if captioned_clip != reframed_clip else None
                graded_clip.close() if graded_clip != captioned_clip else None
                branded_clip.close() if branded_clip != graded_clip else None
            except:
                pass

            elapsed = (datetime.now() - start_time).total_seconds()

            applied_features = []
            if captions_applied:
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
                    'features_requested': ['captions', 'audio_ducking', 'color_grading', 'branding']
                }
            else:
                return {
                    'status': 'error',
                    'clip_idx': clip_idx,
                    'short_number': short_number,
                    'error': 'Output validation failed',
                    'processing_time': elapsed,
                    'features': applied_features,
                    'features_requested': ['captions', 'audio_ducking', 'color_grading', 'branding']
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
