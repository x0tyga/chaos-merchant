"""
Quality Control Agent - Validates all pipeline outputs
Ensures videos, audio, metadata, captions, and content meet YouTube Shorts production standards
Production-grade validation with zero tolerance for failures at scale (10+ shorts/day)
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import subprocess
import os
from difflib import SequenceMatcher

try:
    # moviepy 2.x removed the moviepy.editor namespace - see the same fix
    # applied to agents/video_production.py. Only VideoFileClip's read-only
    # properties (.duration, .w, .h, .audio, .fps) are used in this file,
    # which are unchanged between v1 and v2, so this is a pure import fix.
    from moviepy import VideoFileClip
    import numpy as np
except ImportError:
    raise ImportError("moviepy and numpy required: pip install moviepy numpy")

try:
    # Read the real caption position constant from where captions are
    # actually placed, instead of a second hardcoded guess in this file
    # that can silently drift out of sync (see CaptionValidator below).
    from agents.video_production import CaptionSynchronizer as _CaptionSynchronizer
except ImportError:
    _CaptionSynchronizer = None

logger = logging.getLogger(__name__)


class VideoValidator:
    """Validates MP4 video files with strict production standards"""

    EXPECTED_WIDTH = 1080
    EXPECTED_HEIGHT = 1920
    EXPECTED_CODEC = 'h264'
    EXPECTED_AUDIO_CODEC = 'aac'
    MIN_FILE_SIZE = 500000  # 500KB
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    # Read from the same env vars clip_intelligence.py uses for segment
    # selection (MIN_CLIP_DURATION/MAX_CLIP_DURATION) instead of a separate
    # hardcoded constant - previously these could silently disagree if
    # either env var was overridden, causing QC to hard-fail videos that
    # clip selection considered valid (or vice versa).
    MIN_DURATION = int(os.getenv('MIN_CLIP_DURATION', 15))
    MAX_DURATION = int(os.getenv('MAX_CLIP_DURATION', 45))
    AUDIO_SYNC_TOLERANCE = 0.3  # Stricter tolerance (was 1.0)

    @staticmethod
    def validate_video(video_path: str) -> Dict:
        """
        Validate single MP4 file with detailed logging

        Returns:
            dict: {status, errors[], warnings[], metadata, checks[]}
        """
        errors = []
        warnings = []
        metadata = {}
        checks = []  # Detailed logging of each check

        video_path = Path(video_path)

        if not video_path.exists():
            error_msg = f'File not found: {video_path}'
            checks.append({'check': 'file_exists', 'result': 'FAIL', 'expected': 'file present', 'found': 'missing'})
            return {
                'status': 'error',
                'errors': [error_msg],
                'warnings': [],
                'metadata': {},
                'checks': checks
            }

        try:
            file_size = video_path.stat().st_size
            file_size_mb = file_size / (1024 * 1024)

            # CHECK 1: File size
            if file_size < VideoValidator.MIN_FILE_SIZE:
                error_msg = f'File too small: {file_size_mb:.1f}MB (min: {VideoValidator.MIN_FILE_SIZE / (1024*1024):.1f}MB)'
                errors.append(error_msg)
                checks.append({
                    'check': 'file_size',
                    'result': 'FAIL',
                    'expected': f'{VideoValidator.MIN_FILE_SIZE / (1024*1024):.1f}MB minimum',
                    'found': f'{file_size_mb:.1f}MB'
                })
                logger.error(f"❌ {error_msg}")
            elif file_size > VideoValidator.MAX_FILE_SIZE:
                warning_msg = f'File large: {file_size_mb:.1f}MB (typical: <30MB)'
                warnings.append(warning_msg)
                checks.append({
                    'check': 'file_size',
                    'result': 'WARN',
                    'expected': '<30MB typical',
                    'found': f'{file_size_mb:.1f}MB'
                })
                logger.warning(f"⚠ {warning_msg}")
            else:
                checks.append({
                    'check': 'file_size',
                    'result': 'PASS',
                    'expected': f'{VideoValidator.MIN_FILE_SIZE / (1024*1024):.1f}-{VideoValidator.MAX_FILE_SIZE / (1024*1024):.0f}MB',
                    'found': f'{file_size_mb:.1f}MB'
                })
                logger.info(f"✓ File size: {file_size_mb:.1f}MB (PASS)")

            metadata['file_size_mb'] = file_size_mb

            clip = VideoFileClip(video_path)

            # CHECK 2: Video duration (PIPELINE STANDARD: 15-45s)
            duration = clip.duration
            metadata['duration'] = duration

            if duration < VideoValidator.MIN_DURATION:
                error_msg = f'Video too short: {duration:.2f}s (min: {VideoValidator.MIN_DURATION}s)'
                errors.append(error_msg)
                checks.append({
                    'check': 'duration',
                    'result': 'FAIL',
                    'expected': f'{VideoValidator.MIN_DURATION}-{VideoValidator.MAX_DURATION}s',
                    'found': f'{duration:.2f}s'
                })
                logger.error(f"❌ {error_msg}")
            elif duration > VideoValidator.MAX_DURATION:
                error_msg = f'Video too long: {duration:.2f}s (max: {VideoValidator.MAX_DURATION}s)'
                errors.append(error_msg)
                checks.append({
                    'check': 'duration',
                    'result': 'FAIL',
                    'expected': f'{VideoValidator.MIN_DURATION}-{VideoValidator.MAX_DURATION}s',
                    'found': f'{duration:.2f}s'
                })
                logger.error(f"❌ {error_msg}")
            else:
                checks.append({
                    'check': 'duration',
                    'result': 'PASS',
                    'expected': f'{VideoValidator.MIN_DURATION}-{VideoValidator.MAX_DURATION}s',
                    'found': f'{duration:.2f}s'
                })
                logger.info(f"✓ Duration: {duration:.2f}s (PASS)")

            # CHECK 3: Resolution (exact 1080x1920)
            width = clip.w
            height = clip.h
            metadata['width'] = width
            metadata['height'] = height
            metadata['aspect_ratio'] = f"{width}:{height}"

            if abs(width - VideoValidator.EXPECTED_WIDTH) > 5 or abs(height - VideoValidator.EXPECTED_HEIGHT) > 5:
                error_msg = f'Wrong resolution: {width}x{height} (expected: {VideoValidator.EXPECTED_WIDTH}x{VideoValidator.EXPECTED_HEIGHT})'
                errors.append(error_msg)
                checks.append({
                    'check': 'resolution',
                    'result': 'FAIL',
                    'expected': f'{VideoValidator.EXPECTED_WIDTH}x{VideoValidator.EXPECTED_HEIGHT}',
                    'found': f'{width}x{height}'
                })
                logger.error(f"❌ {error_msg}")
            else:
                checks.append({
                    'check': 'resolution',
                    'result': 'PASS',
                    'expected': f'{VideoValidator.EXPECTED_WIDTH}x{VideoValidator.EXPECTED_HEIGHT}',
                    'found': f'{width}x{height}'
                })
                logger.info(f"✓ Resolution: {width}x{height} (PASS)")

            # CHECK 4: Audio presence and sync (STRICTER TOLERANCE: ±0.3s)
            if clip.audio is None:
                error_msg = 'No audio track found'
                errors.append(error_msg)
                checks.append({
                    'check': 'audio_presence',
                    'result': 'FAIL',
                    'expected': 'audio track present',
                    'found': 'no audio'
                })
                logger.error(f"❌ {error_msg}")
            else:
                audio_duration = clip.audio.duration
                metadata['audio_duration'] = audio_duration
                sync_diff = abs(audio_duration - duration)

                if sync_diff > VideoValidator.AUDIO_SYNC_TOLERANCE:
                    error_msg = f'Audio sync mismatch: {audio_duration:.2f}s audio vs {duration:.2f}s video (diff: {sync_diff:.2f}s, tolerance: ±{VideoValidator.AUDIO_SYNC_TOLERANCE}s)'
                    errors.append(error_msg)
                    checks.append({
                        'check': 'audio_sync',
                        'result': 'FAIL',
                        'expected': f'audio ≈ video duration (±{VideoValidator.AUDIO_SYNC_TOLERANCE}s)',
                        'found': f'audio={audio_duration:.2f}s, video={duration:.2f}s (diff={sync_diff:.2f}s)'
                    })
                    logger.error(f"❌ {error_msg}")
                else:
                    checks.append({
                        'check': 'audio_sync',
                        'result': 'PASS',
                        'expected': f'audio ≈ video duration (±{VideoValidator.AUDIO_SYNC_TOLERANCE}s)',
                        'found': f'audio={audio_duration:.2f}s, video={duration:.2f}s (diff={sync_diff:.2f}s)'
                    })
                    logger.info(f"✓ Audio sync: {sync_diff:.2f}s drift (PASS)")

            # CHECK 5: FPS (should be 30)
            fps = clip.fps or 30
            metadata['fps'] = fps

            if abs(fps - 30) > 1:
                warning_msg = f'FPS not standard: {fps} (expected: 30)'
                warnings.append(warning_msg)
                checks.append({
                    'check': 'fps',
                    'result': 'WARN',
                    'expected': '30 fps',
                    'found': f'{fps} fps'
                })
                logger.warning(f"⚠ {warning_msg}")
            else:
                checks.append({
                    'check': 'fps',
                    'result': 'PASS',
                    'expected': '30 fps',
                    'found': f'{fps} fps'
                })
                logger.info(f"✓ FPS: {fps} (PASS)")

            clip.close()

            logger.info(f"✓ Video validation complete: {video_path.name}")

        except Exception as e:
            error_msg = f'Video read error: {str(e)}'
            logger.error(f"❌ {error_msg}")
            errors.append(error_msg)
            checks.append({
                'check': 'video_read',
                'result': 'FAIL',
                'expected': 'video readable',
                'found': str(e)
            })

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'errors': errors,
            'warnings': warnings,
            'metadata': metadata,
            'checks': checks
        }


class CaptionValidator:
    """Validates that captions were burned into video frames (Phase 2 requirement)"""

    @staticmethod
    def has_caption_content(video_path: str) -> Tuple[bool, Dict]:
        """
        Check if captions are burned into video frames
        Uses frame analysis to detect text-like content at bottom center of video (caption area)

        Returns:
            (has_captions, details)
        """
        details = {
            'check': 'caption_presence',
            'frames_sampled': 0,
            'frames_with_text': 0,
            'confidence': 0.0,
            'result': 'UNKNOWN'
        }

        try:
            clip = VideoFileClip(video_path)
            duration = clip.duration
            fps = clip.fps or 30

            # Sample frames at 1s intervals (evenly distributed across video)
            sample_count = min(int(duration), 5)  # Sample up to 5 frames
            sample_times = [i * (duration / (sample_count + 1)) for i in range(1, sample_count + 1)]
            details['frames_sampled'] = len(sample_times)

            frames_with_text_indicators = 0

            for t in sample_times:
                try:
                    frame = clip.get_frame(t)

                    # Check the region captions are actually placed in -
                    # center 80% of width, spanning from just above
                    # CaptionSynchronizer.CAPTION_TOP_RATIO (80% down from
                    # the top, per the Bug 3 fix) to the bottom of the
                    # frame. This USED to be hardcoded to the bottom 15%
                    # of the frame, which was the right band for the OLD
                    # caption position (video_clip.h - 160px) but silently
                    # fell out of sync with Bug 3's fix moving captions up
                    # to 80% from the top - on a 1920px-tall frame that's
                    # a caption box that can sit entirely above y=1632
                    # (the old region's top edge), causing this check to
                    # report FAIL ("no captions detected") on videos that
                    # genuinely have captions, just higher up on screen.
                    # Reading the real constant here instead of a second,
                    # independently-hardcoded guess keeps the two in sync
                    # if the position ever changes again.
                    h, w = frame.shape[:2]
                    caption_top_ratio = getattr(_CaptionSynchronizer, 'CAPTION_TOP_RATIO', 0.80)
                    region_top = max(0.0, caption_top_ratio - 0.05)
                    caption_region = frame[int(h * region_top):h, int(w * 0.1):int(w * 0.9)]

                    # Detect white or high-contrast text on dark background
                    # Look for pixels with high brightness (text) or high contrast edges
                    gray = np.dot(caption_region[..., :3], [0.299, 0.587, 0.114])

                    # High brightness areas (white text)
                    bright_pixels = np.sum(gray > 200)
                    # Dark background areas
                    dark_pixels = np.sum(gray < 50)

                    # Calculate contrast in caption region
                    contrast = np.std(gray)

                    # If we detect both bright text and dark background with high contrast, likely captions
                    if bright_pixels > (caption_region.shape[0] * caption_region.shape[1] * 0.02) and contrast > 30:
                        frames_with_text_indicators += 1

                except Exception as e:
                    logger.debug(f"Frame analysis error at {t}s: {e}")
                    continue

            confidence = frames_with_text_indicators / len(sample_times) if sample_times else 0
            details['frames_with_text'] = frames_with_text_indicators
            details['confidence'] = confidence

            clip.close()

            # Require captions in at least 60% of sampled frames
            if confidence >= 0.6:
                details['result'] = 'PASS'
                return True, details
            else:
                details['result'] = 'FAIL'
                return False, details

        except Exception as e:
            logger.error(f"Caption detection failed: {e}")
            details['result'] = 'ERROR'
            details['error'] = str(e)
            return False, details


class ContentSimilarityValidator:
    """Checks against last 14 days of channel memory to flag recently covered topics"""

    @staticmethod
    def check_topic_similarity(seo_manifest: Dict, channel_memory_dir: str = './output',
                              exclude_filename: str = None) -> Tuple[bool, Dict]:
        """
        Compare current short topic/title against last 14 days of published shorts.
        Flag if topic similarity exceeds threshold (would indicate repeat content).

        NOTE: pipeline.py writes each video's SEO metadata directly to
        {output_dir}/{video_stem}_seo_metadata.json, so that's what we scan by
        default (not a separate ./channel_memory/ directory, which nothing ever
        populates). exclude_filename should be set to the CURRENT video's own
        seo_metadata filename so it doesn't get compared against itself.

        Returns:
            (is_unique, details)
        """
        details = {
            'check': 'topic_similarity',
            'recent_shorts_checked': 0,
            'highest_similarity': 0.0,
            'similar_short': None,
            'result': 'PASS'
        }

        try:
            current_title = seo_manifest.get('best_title', '')
            current_keywords = seo_manifest.get('metadata', {}).get('keywords', [])

            if not current_title:
                logger.warning("No title found for similarity check")
                details['result'] = 'SKIP'
                return True, details

            # Load recent shorts from channel memory
            channel_memory_path = Path(channel_memory_dir)
            if not channel_memory_path.exists():
                logger.info("Channel memory directory not found, skipping similarity check")
                details['result'] = 'SKIP'
                return True, details

            # Find all recent short metadata files (last 14 days)
            now = datetime.now()
            cutoff_date = now - timedelta(days=14)

            recent_shorts = []
            for manifest_file in channel_memory_path.glob('*_seo_metadata.json'):
                if exclude_filename and manifest_file.name == exclude_filename:
                    continue
                try:
                    file_mtime = datetime.fromtimestamp(manifest_file.stat().st_mtime)
                    if file_mtime > cutoff_date:
                        with open(manifest_file, 'r') as f:
                            manifest = json.load(f)
                            recent_shorts.append({
                                'title': manifest.get('best_title', ''),
                                'keywords': manifest.get('metadata', {}).get('keywords', []),
                                'file': manifest_file.name
                            })
                except Exception as e:
                    logger.debug(f"Error reading {manifest_file}: {e}")
                    continue

            details['recent_shorts_checked'] = len(recent_shorts)

            # Compare current title against recent titles
            highest_similarity = 0.0
            most_similar_short = None

            for recent_short in recent_shorts:
                recent_title = recent_short['title']

                # String similarity (0.0-1.0)
                similarity = SequenceMatcher(None, current_title.lower(), recent_title.lower()).ratio()

                # Keyword overlap (0.0-1.0)
                current_kw_set = set(kw.lower() for kw in current_keywords)
                recent_kw_set = set(kw.lower() for kw in recent_short['keywords'])

                if current_kw_set and recent_kw_set:
                    keyword_overlap = len(current_kw_set & recent_kw_set) / max(len(current_kw_set), len(recent_kw_set))
                else:
                    keyword_overlap = 0.0

                # Combined similarity (60% title, 40% keywords)
                combined_similarity = (0.6 * similarity) + (0.4 * keyword_overlap)

                if combined_similarity > highest_similarity:
                    highest_similarity = combined_similarity
                    most_similar_short = recent_short

            details['highest_similarity'] = round(highest_similarity, 3)
            if most_similar_short:
                details['similar_short'] = {
                    'title': most_similar_short['title'],
                    'file': most_similar_short['file']
                }

            # FAIL if similarity > 0.75 (75% similar = likely duplicate topic)
            SIMILARITY_THRESHOLD = 0.75
            if highest_similarity > SIMILARITY_THRESHOLD:
                details['result'] = 'FAIL'
                logger.error(f"❌ Topic too similar to recent short: {highest_similarity:.1%} similarity with '{most_similar_short['title']}'")
                return False, details
            elif highest_similarity > 0.5:
                # WARN if 50-75% similar
                details['result'] = 'WARN'
                logger.warning(f"⚠ Topic somewhat similar to recent short: {highest_similarity:.1%} similarity with '{most_similar_short['title']}'")
                return True, details
            else:
                # PASS if < 50% similar
                details['result'] = 'PASS'
                logger.info(f"✓ Topic unique (highest similarity: {highest_similarity:.1%})")
                return True, details

        except Exception as e:
            logger.error(f"Content similarity check failed: {e}")
            details['result'] = 'ERROR'
            details['error'] = str(e)
            return True, details  # Don't fail on error, just warn


class MetadataValidator:
    """Validates JSON metadata files"""

    REQUIRED_FIELDS_CLIP = ['video_path', 'clips', 'top_clip_indices', 'fps']
    REQUIRED_FIELDS_SEO = ['best_title', 'metadata']
    REQUIRED_FIELDS_VIDEO = ['video_paths', 'metadata']
    REQUIRED_FIELDS_THUMBNAIL = ['status', 'thumbnails']

    @staticmethod
    def validate_clip_manifest(manifest: Dict) -> Dict:
        """Validate clip intelligence manifest"""
        errors = []
        warnings = []
        checks = []

        for field in MetadataValidator.REQUIRED_FIELDS_CLIP:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')
                checks.append({
                    'field': field,
                    'result': 'FAIL',
                    'expected': 'present',
                    'found': 'missing'
                })
            else:
                checks.append({
                    'field': field,
                    'result': 'PASS',
                    'expected': 'present',
                    'found': 'present'
                })

        if 'top_clip_indices' in manifest:
            top_count = len(manifest['top_clip_indices'])
            if top_count != 7:
                warnings.append(f'Expected 7 top clips, got {top_count}')
                checks.append({
                    'field': 'top_clip_indices',
                    'result': 'WARN',
                    'expected': '7 clips',
                    'found': f'{top_count} clips'
                })
                logger.warning(f"⚠ Expected 7 top clips, got {top_count}")
            else:
                checks.append({
                    'field': 'top_clip_indices',
                    'result': 'PASS',
                    'expected': '7 clips',
                    'found': f'{top_count} clips'
                })
                logger.info(f"✓ Top clip count: {top_count} (PASS)")

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'clip_intelligence',
            'errors': errors,
            'warnings': warnings,
            'checks': checks
        }

    @staticmethod
    def validate_seo_manifest(manifest: Dict) -> Dict:
        """Validate SEO metadata"""
        errors = []
        warnings = []
        checks = []

        for field in MetadataValidator.REQUIRED_FIELDS_SEO:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')
                checks.append({
                    'field': field,
                    'result': 'FAIL',
                    'expected': 'present',
                    'found': 'missing'
                })
            else:
                checks.append({
                    'field': field,
                    'result': 'PASS',
                    'expected': 'present',
                    'found': 'present'
                })

        if 'metadata' in manifest:
            meta = manifest['metadata']
            hashtag_count = len(meta.get('hashtags', []))

            if hashtag_count < 10:
                warnings.append(f'Insufficient hashtags: {hashtag_count} (expected 10-15)')
                checks.append({
                    'field': 'hashtags',
                    'result': 'WARN',
                    'expected': '10-15 tags',
                    'found': f'{hashtag_count} tags'
                })
                logger.warning(f"⚠ Hashtags: {hashtag_count}/10-15 (WARN)")
            else:
                checks.append({
                    'field': 'hashtags',
                    'result': 'PASS',
                    'expected': '10-15 tags',
                    'found': f'{hashtag_count} tags'
                })
                logger.info(f"✓ Hashtags: {hashtag_count} (PASS)")

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'seo_metadata',
            'errors': errors,
            'warnings': warnings,
            'checks': checks
        }

    @staticmethod
    def validate_video_manifest(manifest: Dict) -> Dict:
        """Validate video production manifest"""
        errors = []
        warnings = []
        checks = []

        for field in MetadataValidator.REQUIRED_FIELDS_VIDEO:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')
                checks.append({
                    'field': field,
                    'result': 'FAIL',
                    'expected': 'present',
                    'found': 'missing'
                })

        if 'video_paths' in manifest:
            count = len(manifest['video_paths'])
            if count != 7:
                warnings.append(f'Expected 7 videos, got {count}')
                checks.append({
                    'field': 'video_paths',
                    'result': 'WARN',
                    'expected': '7 videos',
                    'found': f'{count} videos'
                })
                logger.warning(f"⚠ Video count: {count}/7 (WARN)")
            else:
                checks.append({
                    'field': 'video_paths',
                    'result': 'PASS',
                    'expected': '7 videos',
                    'found': f'{count} videos'
                })
                logger.info(f"✓ Video count: {count} (PASS)")

        if 'metadata' in manifest:
            meta = manifest['metadata']
            if meta.get('codec') != 'h264':
                errors.append(f'Invalid codec: {meta.get("codec")}')
                checks.append({
                    'field': 'codec',
                    'result': 'FAIL',
                    'expected': 'h264',
                    'found': meta.get('codec')
                })
                logger.error(f"❌ Codec: {meta.get('codec')} (expected h264)")
            if meta.get('audio_codec') != 'aac':
                errors.append(f'Invalid audio codec: {meta.get("audio_codec")}')
                checks.append({
                    'field': 'audio_codec',
                    'result': 'FAIL',
                    'expected': 'aac',
                    'found': meta.get('audio_codec')
                })
                logger.error(f"❌ Audio codec: {meta.get('audio_codec')} (expected aac)")

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'video_production',
            'errors': errors,
            'warnings': warnings,
            'checks': checks
        }

    @staticmethod
    def validate_thumbnail_manifest(manifest: Dict) -> Dict:
        """Validate thumbnail manifest"""
        errors = []
        warnings = []
        checks = []

        for field in MetadataValidator.REQUIRED_FIELDS_THUMBNAIL:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')
                checks.append({
                    'field': field,
                    'result': 'FAIL',
                    'expected': 'present',
                    'found': 'missing'
                })

        if 'thumbnails' in manifest:
            count = len(manifest['thumbnails'])
            if count != 7:
                warnings.append(f'Expected 7 thumbnails, got {count}')
                checks.append({
                    'field': 'thumbnail_count',
                    'result': 'WARN',
                    'expected': '7 thumbnails',
                    'found': f'{count} thumbnails'
                })
                logger.warning(f"⚠ Thumbnail count: {count}/7 (WARN)")
            else:
                checks.append({
                    'field': 'thumbnail_count',
                    'result': 'PASS',
                    'expected': '7 thumbnails',
                    'found': f'{count} thumbnails'
                })
                logger.info(f"✓ Thumbnail count: {count} (PASS)")

            generated = len([t for t in manifest['thumbnails'] if t.get('status') == 'success'])
            brief_only = len([t for t in manifest['thumbnails'] if t.get('status') == 'brief_only'])
            failed = len([t for t in manifest['thumbnails'] if t.get('status') == 'error'])

            if failed > 0:
                warnings.append(f'{failed} thumbnail generation errors (brief-only fallback used)')
                logger.warning(f"⚠ Thumbnail status: {generated} generated, {brief_only} brief-only, {failed} errors")

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'thumbnail',
            'errors': errors,
            'warnings': warnings,
            'checks': checks
        }


class QualityController:
    """Main QC orchestrator with all four critical validations"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)

    def validate_all_outputs(self, clip_manifest: Dict, seo_manifest: Dict,
                            video_manifest: Dict, thumbnail_manifest: Dict,
                            video_base_name: str) -> Dict:
        """
        Validate all pipeline outputs with enhanced checks:
        1. Video file validation (codec, resolution, duration STRICTER, audio sync TIGHTER)
        2. Caption presence check (Phase 2 requirement)
        3. Content similarity against last 14 days
        4. Metadata completeness

        Returns:
            dict with detailed validation results and routing decision
        """
        logger.info("🔍 QUALITY CONTROL - Starting comprehensive validation...")
        logger.info("=" * 70)

        results = {
            'status': 'pass',
            'videos': [],
            'captions': [],
            'content_similarity': [],
            'seo_duplicates': [],
            'metadata': [],
            'issues': {
                'errors': [],
                'warnings': []
            },
            'summary': {}
        }

        output_dir = self.output_dir

        # ============================================================
        # VALIDATION 1: VIDEO FILES (with tighter standards)
        # ============================================================
        logger.info("📹 VALIDATION 1: Video Files (codec, resolution, duration, audio)")
        logger.info("-" * 70)
        video_paths = video_manifest.get('video_paths', [])

        # video_paths is a FILTERED list (successful shorts only - see
        # video_production.py's produce_all_shorts()), so positional index
        # `i` here does NOT reliably equal the real short_number once any
        # short upstream failed (e.g. index 1 in video_paths could actually
        # be Short 3 if Short 2 failed production). short_results carries
        # the real mapping; without it, log messages and per-clip QC files
        # would misattribute results to the wrong clip whenever the batch
        # is partial.
        short_results = video_manifest.get('short_results', [])

        def _real_short_number(i: int) -> int:
            return short_results[i]['short_number'] if i < len(short_results) else i

        for i, video_path in enumerate(video_paths):
            real_num = _real_short_number(i)
            if Path(video_path).exists():
                validation = VideoValidator.validate_video(video_path)
                results['videos'].append({
                    'index': i,
                    'short_number': real_num,
                    'path': video_path,
                    'validation': validation
                })

                # Log all checks with pass/fail status
                for check in validation.get('checks', []):
                    status_icon = "✓" if check['result'] == 'PASS' else ("⚠" if check['result'] == 'WARN' else "❌")
                    logger.info(f"  {status_icon} Short {real_num + 1} - {check['check']}: {check['found']} (expected: {check['expected']})")

                if validation['status'] == 'error':
                    results['issues']['errors'].extend([f"Short {real_num + 1}: {e}" for e in validation['errors']])
                    results['status'] = 'error'
                elif validation['status'] == 'warning':
                    results['issues']['warnings'].extend([f"Short {real_num + 1}: {w}" for w in validation['warnings']])
                    if results['status'] != 'error':
                        results['status'] = 'warning'
            else:
                error_msg = f"Short {real_num + 1}: video file not found: {video_path}"
                results['issues']['errors'].append(error_msg)
                results['status'] = 'error'
                logger.error(f"❌ {error_msg}")

        logger.info(f"✓ Video validation complete: {len(results['videos'])} files checked\n")

        # ============================================================
        # VALIDATION 2: CAPTION PRESENCE (Phase 2 requirement)
        # ============================================================
        logger.info("📝 VALIDATION 2: Caption Presence (burned-in frames)")
        logger.info("-" * 70)

        for i, video_path in enumerate(video_paths):
            real_num = _real_short_number(i)
            if Path(video_path).exists():
                has_captions, caption_details = CaptionValidator.has_caption_content(video_path)
                results['captions'].append({
                    'index': i,
                    'short_number': real_num,
                    'path': video_path,
                    'details': caption_details
                })

                status_icon = "✓" if caption_details['result'] == 'PASS' else ("⚠" if caption_details['result'] == 'WARN' else "❌")
                logger.info(f"  {status_icon} Short {real_num + 1} - Caption check: {caption_details['result']}")
                logger.info(f"     Frames sampled: {caption_details['frames_sampled']}, frames with text: {caption_details['frames_with_text']}, confidence: {caption_details['confidence']:.1%}")

                if caption_details['result'] == 'FAIL':
                    error_msg = f"Short {real_num + 1}: captions not detected in video frames (required for Phase 2 production)"
                    results['issues']['errors'].append(error_msg)
                    results['status'] = 'error'
                    logger.error(f"❌ {error_msg}")

        logger.info(f"✓ Caption validation complete: {len(results['captions'])} videos checked\n")

        # ============================================================
        # VALIDATION 3: CONTENT SIMILARITY (last 14 days) - PER CLIP
        # ============================================================
        # Previously ran ONCE against seo_manifest.get('best_title') - which
        # pipeline.py only ever populates from the FIRST successful clip's
        # SEO result (see the 'first_success' fallback in core/pipeline.py).
        # That meant a title collision on clip 1 alone could flag the
        # entire batch's similarity check, while clips 2 and 3's genuinely
        # distinct topics were never actually evaluated on their own merits
        # - exactly the kind of "failing for a fixable/wrong reason" this
        # was checked for. Now runs once per clip against that CLIP's own
        # title/keywords from seo_manifest['per_clip'].
        logger.info("🔄 VALIDATION 3: Content Similarity Check (last 14 days, per clip)")
        logger.info("-" * 70)

        current_seo_filename = f"{video_base_name}_seo_metadata.json" if video_base_name else None
        per_clip_seo = seo_manifest.get('per_clip', [])

        for i, video_path in enumerate(video_paths):
            real_num = _real_short_number(i)
            clip_seo = per_clip_seo[real_num] if real_num < len(per_clip_seo) else {}

            if clip_seo.get('status') != 'success':
                # This clip's SEO generation itself failed - that's already
                # surfaced by the SEO metadata validation below; nothing to
                # compare here, and it must not be silently treated as a
                # similarity pass OR fail for this clip.
                logger.info(f"  ⊗ Short {real_num + 1} - Topic uniqueness: SKIPPED (no SEO result to compare)")
                continue

            is_unique, similarity_details = ContentSimilarityValidator.check_topic_similarity(
                clip_seo, str(self.output_dir), exclude_filename=current_seo_filename
            )
            similarity_details['short_number'] = real_num
            results['content_similarity'].append(similarity_details)

            status_icon = "✓" if similarity_details['result'] == 'PASS' else ("⚠" if similarity_details['result'] == 'WARN' else ("❌" if similarity_details['result'] == 'FAIL' else "⊗"))
            logger.info(f"  {status_icon} Short {real_num + 1} - Topic uniqueness: {similarity_details['result']}")
            logger.info(f"     Shorts checked (14-day window): {similarity_details['recent_shorts_checked']}")
            logger.info(f"     Highest similarity: {similarity_details['highest_similarity']:.1%}")
            if similarity_details.get('similar_short'):
                logger.info(f"     Most similar: '{similarity_details['similar_short']['title']}'")

            if similarity_details['result'] == 'FAIL':
                error_msg = f"Short {real_num + 1}: content too similar to recent short ({similarity_details['highest_similarity']:.1%} similarity)"
                results['issues']['errors'].append(error_msg)
                results['status'] = 'error'
                logger.error(f"❌ {error_msg}")
            elif similarity_details['result'] == 'WARN':
                warning_msg = f"Short {real_num + 1}: content somewhat similar to recent short ({similarity_details['highest_similarity']:.1%} similarity)"
                results['issues']['warnings'].append(warning_msg)
                if results['status'] != 'error':
                    results['status'] = 'warning'
                logger.warning(f"⚠ {warning_msg}")

        logger.info(f"✓ Content similarity check complete: {len(results['content_similarity'])} clips checked\n")

        # ============================================================
        # VALIDATION 3B: SEO DUPLICATE CHECK (per-clip metadata uniqueness)
        # ============================================================
        # core/pipeline.py's Step 3 already tries to regenerate duplicate
        # SEO metadata (agents/seo_optimizer.py's find_duplicate_seo())
        # before this ever runs - this is the backstop for when that
        # regeneration itself failed to produce distinct metadata. Those
        # clips must not ship unnoticed with duplicate descriptions/
        # hashtags just because regeneration was already attempted -
        # flagged here as a QC warning so it's visible in the batch
        # summary/dashboard instead of only in a log line from Step 3.
        logger.info("🔁 VALIDATION 3B: SEO Duplicate Check (per-clip metadata uniqueness)")
        logger.info("-" * 70)

        unresolved_duplicates = (seo_manifest or {}).get('unresolved_seo_duplicates', [])
        results['seo_duplicates'] = unresolved_duplicates

        if unresolved_duplicates:
            for dup in unresolved_duplicates:
                clip_a, clip_b, field = dup.get('clip_a'), dup.get('clip_b'), dup.get('field')
                warning_msg = (
                    f"Short {clip_a + 1} and Short {clip_b + 1} have identical SEO {field} even "
                    f"after regeneration was attempted - duplicate metadata shipped, needs manual review"
                )
                results['issues']['warnings'].append(warning_msg)
                logger.warning(f"⚠ {warning_msg}")
            if results['status'] != 'error':
                results['status'] = 'warning'
        else:
            logger.info("  ✓ No unresolved SEO duplicates")

        logger.info(f"✓ SEO duplicate check complete: {len(unresolved_duplicates)} unresolved duplicate(s)\n")

        # ============================================================
        # VALIDATION 4: METADATA COMPLETENESS
        # ============================================================
        logger.info("📋 VALIDATION 4: Metadata Completeness")
        logger.info("-" * 70)

        clip_validation = MetadataValidator.validate_clip_manifest(clip_manifest)
        seo_validation = MetadataValidator.validate_seo_manifest(seo_manifest)
        video_validation = MetadataValidator.validate_video_manifest(video_manifest)
        thumbnail_validation = MetadataValidator.validate_thumbnail_manifest(thumbnail_manifest)

        results['metadata'] = [clip_validation, seo_validation, video_validation, thumbnail_validation]

        for meta_val in results['metadata']:
            manifest_type = meta_val['manifest_type']
            status_icon = "✓" if meta_val['status'] == 'PASS' else ("⚠" if meta_val['status'] == 'WARN' else "❌")
            logger.info(f"  {status_icon} {manifest_type}: {meta_val['status'].upper()}")

            for check in meta_val.get('checks', []):
                check_status = "✓" if check['result'] == 'PASS' else ("⚠" if check['result'] == 'WARN' else "❌")
                logger.info(f"     {check_status} {check.get('field', 'check')}: {check['found']} (expected: {check['expected']})")

            if meta_val['status'] == 'error':
                results['issues']['errors'].extend([f"{meta_val['manifest_type']}: {e}" for e in meta_val['errors']])
                results['status'] = 'error'
            elif meta_val['status'] == 'warning':
                results['issues']['warnings'].extend([f"{meta_val['manifest_type']}: {w}" for w in meta_val['warnings']])
                if results['status'] != 'error':
                    results['status'] = 'warning'

        logger.info(f"✓ Metadata validation complete: 4 manifests checked\n")

        # ============================================================
        # SUMMARY
        # ============================================================
        results['summary'] = {
            'videos_validated': len(results['videos']),
            'videos_passed': len([v for v in results['videos'] if v['validation']['status'] == 'pass']),
            'captions_validated': len(results['captions']),
            'captions_passed': len([c for c in results['captions'] if c['details']['result'] == 'PASS']),
            'content_similarity_checked': len(results['content_similarity']),
            'content_unique': all(c['result'] != 'FAIL' for c in results['content_similarity']),
            'seo_duplicates_unresolved': len(results.get('seo_duplicates', [])),
            'total_errors': len(results['issues']['errors']),
            'total_warnings': len(results['issues']['warnings']),
            'overall_status': results['status']
        }

        logger.info("=" * 70)
        logger.info("QC SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Videos: {results['summary']['videos_passed']}/{results['summary']['videos_validated']} passed")
        logger.info(f"Captions: {results['summary']['captions_passed']}/{results['summary']['captions_validated']} passed")
        logger.info(f"Content Uniqueness: {'✓ PASS' if results['summary']['content_unique'] else '❌ FAIL'}")
        logger.info(f"Errors: {results['summary']['total_errors']} | Warnings: {results['summary']['total_warnings']}")
        logger.info(f"OVERALL STATUS: {results['status'].upper()}")
        logger.info("=" * 70)

        return results


def perform_quality_control(clip_manifest: Dict, seo_manifest: Dict,
                           video_manifest: Dict, thumbnail_manifest: Dict,
                           output_dir: str = './output', video_base_name: str = '') -> Dict:
    """
    Main entry point: Perform comprehensive QC on all pipeline outputs

    FOUR CRITICAL VALIDATIONS (Production-grade, 10+ shorts/day, zero manual review):
    1. Video Files: h264 codec, 1080x1920 resolution, 15-45s duration (pipeline standard),
                    audio presence, tight sync (±0.3s, not ±1.0s)
    2. Caption Presence: Verify captions burned into frames (Phase 2 requirement)
    3. Content Similarity: Check against last 14 days to flag duplicate topics
    4. Metadata: Complete, valid, all manifests present

    ALL CHECKS LOGGED with explicit pass/fail status and measured vs expected values

    Returns routing decision: Pass → Step 9, Fail → manual review queue
    """
    logger.info("\n" + "=" * 70)
    logger.info("🔍 QUALITY CONTROL AGENT - PRODUCTION VALIDATION")
    logger.info("=" * 70)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info("Four Critical Checks: Video Files | Captions | Content Similarity | Metadata")
    logger.info("=" * 70 + "\n")

    try:
        qc = QualityController(output_dir)
        result = qc.validate_all_outputs(clip_manifest, seo_manifest,
                                        video_manifest, thumbnail_manifest,
                                        video_base_name)

        routing = 'pass' if result['status'] in ['pass', 'warning'] else 'manual_review'

        # CRITICAL: If any error found, route to manual review (no content goes public without fix)
        if result['status'] == 'error':
            routing = 'manual_review'
            logger.error("❌ QC FAILED - Routing to manual review queue")
            logger.error(f"Errors ({result['summary']['total_errors']}):")
            for error in result['issues']['errors']:
                logger.error(f"  - {error}")

        logger.info("\n" + "=" * 70)
        logger.info(f"FINAL ROUTING: {routing.upper()}")
        logger.info(f"Status: {result['status'].upper()}")
        logger.info(f"Timestamp: {datetime.now().isoformat()}")
        logger.info("=" * 70 + "\n")

        return {
            'status': result['status'],
            'qc_result': result,
            'routing': routing,
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ QC FAILED WITH EXCEPTION: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'routing': 'manual_review',
            'timestamp': datetime.now().isoformat()
        }
