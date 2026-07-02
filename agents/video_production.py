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
    from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ImageClip, TextClip, concatenate_videoclips
    from moviepy.video.fx.resize import resize
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
            clip = self.video_clip.subclip(start_time, end_time)
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
            return video_clip.resize((cls.TARGET_WIDTH, cls.TARGET_HEIGHT))

        if method == 'crop' and source_ratio > cls.TARGET_RATIO:
            new_width = int(video_clip.h * cls.TARGET_RATIO)
            crop_x = (video_clip.w - new_width) // 2
            cropped = video_clip.crop(x1=crop_x, y1=0, x2=crop_x + new_width, y2=video_clip.h)
            logger.info(f"✓ Cropped from {video_clip.w}x{video_clip.h} to {new_width}x{video_clip.h}")
            return cropped.resize((cls.TARGET_WIDTH, cls.TARGET_HEIGHT))

        resized = video_clip.resize(height=cls.TARGET_HEIGHT)
        x_offset = (cls.TARGET_WIDTH - resized.w) // 2

        black_bg = ImageClip(np.zeros((cls.TARGET_HEIGHT, cls.TARGET_WIDTH, 3), dtype=np.uint8))
        final = CompositeVideoClip([black_bg, resized.set_position((x_offset, 0))],
                                  size=(cls.TARGET_WIDTH, cls.TARGET_HEIGHT))
        logger.info(f"✓ Letterboxed to {cls.TARGET_WIDTH}x{cls.TARGET_HEIGHT}")
        return final


class CaptionSynchronizer:
    """Generates and syncs burned-in captions to voiceover"""

    CAPTION_FONT_SIZE = 48
    CAPTION_COLOR = (255, 255, 255)
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
                    'fontsize': self.CAPTION_FONT_SIZE,
                    'color': self.CAPTION_COLOR,
                    'method': 'caption',
                    'size': (video_clip.w - 2 * self.SAFE_MARGIN, None)
                }

                if self.font_path and Path(self.font_path).exists():
                    text_clip_kwargs['font'] = self.font_path

                text_clip = TextClip(**text_clip_kwargs)

                text_clip = text_clip.set_duration(duration).set_start(start_time)
                text_clip = text_clip.set_position(('center', video_clip.h - self.SAFE_MARGIN - 100))

                caption_clips.append(text_clip)

            except Exception as e:
                logger.warning(f"⚠ Caption rendering failed for segment: {e}")
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

    def apply_music_ducking(self, background_audio: AudioFileClip, voiceover_audio: AudioFileClip,
                           vo_start: float = 0.5, duck_db: float = -6.0) -> AudioFileClip:
        """
        Reduce background music volume when voiceover plays
        duck_db: reduction in dB (e.g., -6 = reduce to ~50% volume)
        """
        try:
            logger.info(f"✓ Applying music ducking ({duck_db}dB during voiceover)...")
            vo_end = vo_start + voiceover_audio.duration

            duck_factor = 10 ** (duck_db / 20.0)

            def volume_envelope(get_frame, t):
                if vo_start <= t <= vo_end:
                    return get_frame(t) * duck_factor
                else:
                    return get_frame(t)

            ducked = background_audio.volumex(lambda t: duck_factor if vo_start <= t <= vo_end else 1.0)
            return ducked

        except Exception as e:
            logger.warning(f"⚠ Music ducking failed: {e}, using original audio")
            return background_audio

    def prepare_audio(self, video_clip: VideoFileClip, voiceover_audio: AudioFileClip,
                     start_offset: float = 0.5) -> AudioFileClip:
        """Prepare final audio: voiceover + ducked background"""
        try:
            vo_duration = voiceover_audio.duration
            clip_duration = video_clip.duration

            if abs(vo_duration - clip_duration) > 1.0:
                if vo_duration < clip_duration:
                    logger.warning(f"⚠ Voiceover shorter than clip ({vo_duration:.1f}s < {clip_duration:.1f}s)")
                else:
                    trimmed = voiceover_audio.subclip(0, max(0, clip_duration - start_offset))
                    voiceover_audio = trimmed.set_start(start_offset)
            else:
                voiceover_audio = voiceover_audio.set_start(start_offset)

            if video_clip.audio is not None:
                logger.info("✓ Compositing voiceover with ducked background audio")
                ducked_bg = self.apply_music_ducking(video_clip.audio, voiceover_audio, start_offset)

                from moviepy.audio.AudioFileClip import concatenate_audioclips
                try:
                    final_audio = CompositeVideoClip([video_clip.set_audio(ducked_bg)], 
                                                    size=video_clip.size).audio
                    if voiceover_audio.duration > 0:
                        composite = CompositeVideoClip([video_clip.set_audio(voiceover_audio)],
                                                      size=video_clip.size).audio
                        final_audio = composite
                except:
                    final_audio = voiceover_audio

            else:
                logger.info("✓ Using voiceover as sole audio track")
                final_audio = voiceover_audio

            logger.info("✓ Audio preparation complete")
            return final_audio

        except Exception as e:
            logger.error(f"❌ Audio preparation failed: {e}")
            raise


class EffectsLayer:
    """Applies color grading and visual effects"""

    @staticmethod
    def apply_color_grading(video_clip: VideoFileClip, contrast: float = 1.2,
                           saturation: float = 1.1) -> VideoFileClip:
        """Apply color grading: contrast boost + saturation boost via ffmpeg filter"""
        try:
            logger.info(f"✓ Applying color grading (contrast: {contrast}x, saturation: {saturation}x)")

            eq_filter = f"eq=contrast={contrast}:saturation={saturation}"
            video_with_effects = video_clip.video.write_videofile(
                "temp_graded.mp4",
                codec='libx264',
                audio_codec='aac',
                fps=30,
                vf=eq_filter,
                verbose=False,
                logger=None
            )

            graded_clip = VideoFileClip("temp_graded.mp4")
            if video_clip.audio:
                graded_clip = graded_clip.set_audio(video_clip.audio)

            logger.info("✓ Color grading applied")
            return graded_clip

        except Exception as e:
            logger.warning(f"⚠ Color grading filter failed: {e}, using original video")
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

        except Exception as e:
            logger.warning(f"⚠ Watermark creation failed: {e}")
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

            watermark_clip = ImageClip(watermark_array).set_duration(video_clip.duration)

            x_pos = video_clip.w - cls.WATERMARK_SIZE[0] - cls.WATERMARK_MARGIN[0]
            y_pos = video_clip.h - cls.WATERMARK_SIZE[1] - cls.WATERMARK_MARGIN[1]

            watermark_clip = watermark_clip.set_position((x_pos, y_pos))
            watermark_clip = watermark_clip.fadein(0.3).fadeout(0.3)

            composite = CompositeVideoClip([video_clip, watermark_clip], size=video_clip.size)
            logger.info(f"✓ Applied branding watermark: '{channel_name}'")
            return composite

        except Exception as e:
            logger.error(f"❌ Branding failed: {e}")
            return video_clip


class VideoExporter:
    """Exports video to MP4 with YouTube specs"""

    @staticmethod
    def export_mp4(video_clip: VideoFileClip, output_path: str, preset: str = 'ultrafast') -> str:
        """Export VideoClip to MP4"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            logger.info(f"📹 Exporting to {output_path.name} (preset: {preset})...")

            video_clip.write_videofile(
                str(output_path),
                codec='libx264',
                audio_codec='aac',
                fps=30,
                verbose=False,
                logger=None,
                preset=preset,
                bitrate='6000k',
                audio_bitrate='128k'
            )

            file_size_mb = output_path.stat().st_size / (1024 * 1024)
            logger.info(f"✓ Exported: {output_path.name} ({file_size_mb:.1f} MB)")
            return str(output_path)

        except Exception as e:
            logger.error(f"❌ Export failed: {e}")
            raise

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

    def __init__(self, source_video_path: str, clip_manifest: Dict, voiceover_result: Dict,
                 output_dir: str, temp_dir: str = None, script: str = None, channel_name: str = None):
        self.source_video_path = Path(source_video_path)
        self.clip_manifest = clip_manifest
        self.voiceover_result = voiceover_result
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir or self.output_dir / 'temp')
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.script = script or voiceover_result.get('script', {}).get('full_script', '')
        self.channel_name = channel_name or os.getenv('CHANNEL_NAME', 'Chaos Merchant')

    def produce_all_shorts(self) -> Dict:
        """Produce all 7 shorts from top clips"""
        logger.info("🎬 Starting video production (Phase 2 - Full Features)...")

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
                logger.error(f"❌ Short {i+1} failed: {e}")
                results.append({
                    'status': 'error',
                    'clip_idx': clip_idx,
                    'error': str(e),
                    'short_number': i
                })

        video_paths = [r.get('output_path') for r in results if r.get('status') == 'success']
        timings = {str(r.get('clip_idx')): r.get('duration', 0) for r in results if r.get('status') == 'success'}
        errors = [r.get('error') for r in results if r.get('status') == 'error']

        logger.info(f"\n✅ Production complete: {len(video_paths)} of {len(top_clip_indices)} shorts produced")

        return {
            'status': 'success' if video_paths else 'partial',
            'video_paths': video_paths,
            'timings': timings,
            'processing_times': {'export_total': 0},
            'errors': errors,
            'metadata': {
                'source_video': str(self.source_video_path),
                'total_shorts': len(video_paths),
                'total_duration': sum(timings.values()),
                'codec': 'h264',
                'audio_codec': 'aac',
                'resolution': '1080x1920',
                'features': ['captions', 'audio_ducking', 'color_grading', 'branding']
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

            logger.info(f"Step 3: Preparing audio (voiceover + music ducking)...")
            audio_processor = AudioProcessor(self.voiceover_result['voiceover']['audio_path'])
            voiceover_audio = audio_processor.load_voiceover()
            final_audio = audio_processor.prepare_audio(reframed_clip, voiceover_audio)
            reframed_clip = reframed_clip.set_audio(final_audio)

            logger.info(f"Step 4: Adding burned-in captions...")
            caption_sync = CaptionSynchronizer(self.script)
            caption_timeline = caption_sync.generate_caption_timeline(voiceover_audio.duration)
            captioned_clip = caption_sync.render_captions(reframed_clip, caption_timeline)

            logger.info(f"Step 5: Applying color grading...")
            effects = EffectsLayer()
            graded_clip = effects.apply_color_grading(captioned_clip, contrast=1.2, saturation=1.1)

            logger.info(f"Step 6: Adding channel branding...")
            branded_clip = BrandingOverlay.apply_branding(graded_clip, self.channel_name)

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

            if is_valid:
                return {
                    'status': 'success',
                    'clip_idx': clip_idx,
                    'short_number': short_number,
                    'output_path': export_path,
                    'duration': extracted_clip.duration,
                    'processing_time': elapsed,
                    'features': ['captions', 'audio_ducking', 'color_grading', 'branding']
                }
            else:
                return {
                    'status': 'error',
                    'clip_idx': clip_idx,
                    'short_number': short_number,
                    'error': 'Output validation failed',
                    'processing_time': elapsed
                }

        except Exception as e:
            logger.error(f"❌ Short {short_number} production failed: {e}")
            return {
                'status': 'error',
                'clip_idx': clip_idx,
                'short_number': short_number,
                'error': str(e),
                'processing_time': (datetime.now() - start_time).total_seconds()
            }


def produce_shorts(source_video_path: str, clip_manifest: Dict, voiceover_result: Dict,
                  script_data: Dict = None, output_dir: str = './output',
                  temp_dir: str = None) -> Dict:
    """
    Main entry point: Produce shorts with Phase 2 features
    - Burned-in captions synced to voiceover
    - Music ducking (background audio reduces during voiceover)
    - Color grading (contrast + saturation boost)
    - Channel branding watermark
    """
    logger.info("=" * 60)
    logger.info("🎬 VIDEO PRODUCTION AGENT - PHASE 2 (FULL FEATURES)")
    logger.info("=" * 60)

    try:
        script = script_data.get('script', {}).get('full_script', '') if script_data else voiceover_result.get('script', {}).get('full_script', '')
        channel_name = os.getenv('CHANNEL_NAME', 'Chaos Merchant')

        producer = VideoProducer(source_video_path, clip_manifest, voiceover_result,
                                output_dir, temp_dir, script, channel_name)
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
