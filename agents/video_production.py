"""
Video Production Agent - Produces finished YouTube Shorts from clips
Transforms source video clips into 9:16 vertical format MP4s with voiceover
Phase 1 Focus: Extract, reframe, sync audio, export MP4 (20-25 min target)
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict
import numpy as np

try:
    from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, ImageClip
except ImportError:
    raise ImportError("moviepy required: pip install moviepy")

try:
    import cv2
except ImportError:
    raise ImportError("opencv-python required: pip install opencv-python")

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


class AudioProcessor:
    """Processes and mixes audio: voiceover + background"""

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

    def align_voiceover(self, voiceover_audio: AudioFileClip, clip_duration: float,
                        start_offset: float = 0.5) -> AudioFileClip:
        """Align voiceover to clip duration"""
        vo_duration = voiceover_audio.duration

        if abs(vo_duration - clip_duration) < 1.0:
            logger.info(f"✓ Voiceover duration matches clip ({vo_duration:.1f}s)")
            return voiceover_audio.set_start(start_offset)

        elif vo_duration < clip_duration:
            logger.warning(f"⚠ Voiceover shorter than clip ({vo_duration:.1f}s < {clip_duration:.1f}s)")
            return voiceover_audio.set_start(start_offset)

        else:
            logger.warning(f"⚠ Voiceover longer than clip ({vo_duration:.1f}s > {clip_duration:.1f}s)")
            trimmed = voiceover_audio.subclip(0, max(0, clip_duration - start_offset))
            logger.info(f"  Trimmed to {trimmed.duration:.1f}s")
            return trimmed.set_start(start_offset)

    def prepare_audio(self, video_clip: VideoFileClip, voiceover_audio: AudioFileClip,
                     start_offset: float = 0.5) -> AudioFileClip:
        """Prepare final audio track"""
        try:
            vo_aligned = self.align_voiceover(voiceover_audio, video_clip.duration, start_offset)
            vo_normalized = vo_aligned

            if video_clip.audio is not None:
                logger.info("✓ Compositing voiceover over background audio")
                composite = CompositeVideoClip([video_clip.set_audio(vo_normalized)],
                                              size=video_clip.size)
                return composite.audio
            else:
                logger.info("✓ Using voiceover as sole audio track")
                return vo_normalized

        except Exception as e:
            logger.error(f"❌ Audio preparation failed: {e}")
            raise


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
    """Main orchestrator for video production"""

    def __init__(self, source_video_path: str, clip_manifest: Dict, voiceover_result: Dict,
                 output_dir: str, temp_dir: str = None):
        self.source_video_path = Path(source_video_path)
        self.clip_manifest = clip_manifest
        self.voiceover_result = voiceover_result
        self.output_dir = Path(output_dir)
        self.temp_dir = Path(temp_dir or self.output_dir / 'temp')
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def produce_all_shorts(self) -> Dict:
        """Produce all 7 shorts from top clips"""
        logger.info("🎬 Starting video production for all clips...")

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
                'resolution': '1080x1920'
            },
            'timestamp': datetime.now().isoformat()
        }

    def produce_single_short(self, clip_idx: int, short_number: int) -> Dict:
        """Produce one finished short"""
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

            logger.info(f"Step 3: Preparing audio (voiceover + sync)...")
            audio_processor = AudioProcessor(self.voiceover_result['voiceover']['audio_path'])
            voiceover_audio = audio_processor.load_voiceover()
            final_audio = audio_processor.prepare_audio(reframed_clip, voiceover_audio)

            reframed_clip = reframed_clip.set_audio(final_audio)

            output_name = f"video_{self.source_video_path.stem}_{short_number:03d}.mp4"
            output_path = self.output_dir / output_name

            logger.info(f"Step 4: Exporting MP4...")
            exporter = VideoExporter()
            export_path = exporter.export_mp4(reframed_clip, str(output_path), preset='ultrafast')

            is_valid = exporter.validate_output(export_path)

            try:
                extractor.close()
                reframed_clip.close()
                voiceover_audio.close()
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
                    'processing_time': elapsed
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
    Main entry point: Produce shorts from source video

    Args:
        source_video_path: Path to source video
        clip_manifest: Clip Intelligence output
        voiceover_result: Script + Voiceover output
        script_data: Script data (optional)
        output_dir: Output directory for MP4s
        temp_dir: Temporary directory

    Returns:
        dict: Production manifest with video_paths, timings, errors
    """
    logger.info("=" * 60)
    logger.info("🎬 VIDEO PRODUCTION AGENT - PHASE 1 (MVP)")
    logger.info("=" * 60)

    try:
        producer = VideoProducer(source_video_path, clip_manifest, voiceover_result,
                                output_dir, temp_dir)
        result = producer.produce_all_shorts()

        logger.info("\n" + "=" * 60)
        logger.info(f"PRODUCTION COMPLETE: {len(result['video_paths'])} shorts produced")
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
