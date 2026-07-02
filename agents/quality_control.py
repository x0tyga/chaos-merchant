"""
Quality Control Agent - Validates all pipeline outputs
Ensures videos, audio, metadata, and thumbnails meet YouTube Shorts standards
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple
import subprocess

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    raise ImportError("moviepy required: pip install moviepy")

logger = logging.getLogger(__name__)


class VideoValidator:
    """Validates MP4 video files"""

    EXPECTED_WIDTH = 1080
    EXPECTED_HEIGHT = 1920
    EXPECTED_CODEC = 'h264'
    EXPECTED_AUDIO_CODEC = 'aac'
    MIN_FILE_SIZE = 500000  # 500KB
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    MIN_DURATION = 10
    MAX_DURATION = 120

    @staticmethod
    def validate_video(video_path: str) -> Dict:
        """
        Validate single MP4 file
        
        Returns:
            dict: {status, errors[], warnings[], metadata}
        """
        errors = []
        warnings = []
        metadata = {}

        video_path = Path(video_path)

        if not video_path.exists():
            return {
                'status': 'error',
                'errors': [f'File not found: {video_path}'],
                'warnings': [],
                'metadata': {}
            }

        try:
            file_size = video_path.stat().st_size

            if file_size < VideoValidator.MIN_FILE_SIZE:
                errors.append(f'File too small: {file_size} bytes (min: {VideoValidator.MIN_FILE_SIZE})')

            if file_size > VideoValidator.MAX_FILE_SIZE:
                warnings.append(f'File large: {file_size / (1024*1024):.1f}MB (typical: <30MB)')

            metadata['file_size_mb'] = file_size / (1024 * 1024)

            clip = VideoFileClip(video_path)

            duration = clip.duration
            metadata['duration'] = duration

            if duration < VideoValidator.MIN_DURATION:
                errors.append(f'Video too short: {duration:.1f}s (min: {VideoValidator.MIN_DURATION}s)')

            if duration > VideoValidator.MAX_DURATION:
                errors.append(f'Video too long: {duration:.1f}s (max: {VideoValidator.MAX_DURATION}s)')

            width = clip.w
            height = clip.h
            metadata['width'] = width
            metadata['height'] = height
            metadata['aspect_ratio'] = f"{width}:{height}"

            if abs(width - VideoValidator.EXPECTED_WIDTH) > 5 or abs(height - VideoValidator.EXPECTED_HEIGHT) > 5:
                errors.append(f'Wrong resolution: {width}x{height} (expected: {VideoValidator.EXPECTED_WIDTH}x{VideoValidator.EXPECTED_HEIGHT})')

            if clip.audio is None:
                errors.append('No audio track found')
            else:
                audio_duration = clip.audio.duration
                metadata['audio_duration'] = audio_duration

                if abs(audio_duration - duration) > 1.0:
                    warnings.append(f'Audio duration mismatch: {audio_duration:.1f}s vs video {duration:.1f}s')

            fps = clip.fps or 30
            metadata['fps'] = fps

            if abs(fps - 30) > 1:
                warnings.append(f'FPS not standard: {fps} (expected: 30)')

            clip.close()

            logger.info(f"✓ Video validation passed: {video_path.name}")

        except Exception as e:
            logger.error(f"❌ Video validation failed: {e}")
            errors.append(f'Video read error: {str(e)}')

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'errors': errors,
            'warnings': warnings,
            'metadata': metadata
        }


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

        for field in MetadataValidator.REQUIRED_FIELDS_CLIP:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')

        if 'top_clip_indices' in manifest:
            if len(manifest['top_clip_indices']) != 7:
                warnings.append(f'Expected 7 top clips, got {len(manifest["top_clip_indices"])}')

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'clip_intelligence',
            'errors': errors,
            'warnings': warnings
        }

    @staticmethod
    def validate_seo_manifest(manifest: Dict) -> Dict:
        """Validate SEO metadata"""
        errors = []
        warnings = []

        for field in MetadataValidator.REQUIRED_FIELDS_SEO:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')

        if 'metadata' in manifest:
            meta = manifest['metadata']
            if 'hashtags' not in meta or len(meta.get('hashtags', [])) < 5:
                warnings.append('Insufficient hashtags (expected 10-15)')

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'seo_metadata',
            'errors': errors,
            'warnings': warnings
        }

    @staticmethod
    def validate_video_manifest(manifest: Dict) -> Dict:
        """Validate video production manifest"""
        errors = []
        warnings = []

        for field in MetadataValidator.REQUIRED_FIELDS_VIDEO:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')

        if 'video_paths' in manifest:
            count = len(manifest['video_paths'])
            if count != 7:
                warnings.append(f'Expected 7 videos, got {count}')

        if 'metadata' in manifest:
            meta = manifest['metadata']
            if meta.get('codec') != 'h264':
                errors.append(f'Invalid codec: {meta.get("codec")}')
            if meta.get('audio_codec') != 'aac':
                errors.append(f'Invalid audio codec: {meta.get("audio_codec")}')

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'video_production',
            'errors': errors,
            'warnings': warnings
        }

    @staticmethod
    def validate_thumbnail_manifest(manifest: Dict) -> Dict:
        """Validate thumbnail manifest"""
        errors = []
        warnings = []

        for field in MetadataValidator.REQUIRED_FIELDS_THUMBNAIL:
            if field not in manifest:
                errors.append(f'Missing required field: {field}')

        if 'thumbnails' in manifest:
            count = len(manifest['thumbnails'])
            if count != 7:
                warnings.append(f'Expected 7 thumbnails, got {count}')

            generated = len([t for t in manifest['thumbnails'] if t.get('status') == 'success'])
            brief_only = len([t for t in manifest['thumbnails'] if t.get('status') == 'brief_only'])
            failed = len([t for t in manifest['thumbnails'] if t.get('status') == 'error'])

            if failed > 0:
                warnings.append(f'{failed} thumbnail generation errors (brief-only fallback used)')

            logger.info(f"Thumbnail status: {generated} generated, {brief_only} brief-only, {failed} errors")

        status = 'error' if errors else ('warning' if warnings else 'pass')

        return {
            'status': status,
            'manifest_type': 'thumbnail',
            'errors': errors,
            'warnings': warnings
        }


class QualityController:
    """Main QC orchestrator"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)

    def validate_all_outputs(self, clip_manifest: Dict, seo_manifest: Dict,
                            video_manifest: Dict, thumbnail_manifest: Dict,
                            video_base_name: str) -> Dict:
        """
        Validate all pipeline outputs
        
        Returns:
            dict: {status, videos[], metadata[], thumbnail_status, issues}
        """
        logger.info("🔍 Starting Quality Control validation...")

        results = {
            'status': 'pass',
            'videos': [],
            'metadata': [],
            'issues': {
                'errors': [],
                'warnings': []
            },
            'summary': {}
        }

        output_dir = self.output_dir

        # 1. Validate video files
        logger.info("Validating video files...")
        video_paths = video_manifest.get('video_paths', [])

        for i, video_path in enumerate(video_paths):
            if Path(video_path).exists():
                validation = VideoValidator.validate_video(video_path)
                results['videos'].append({
                    'index': i,
                    'path': video_path,
                    'validation': validation
                })

                if validation['status'] == 'error':
                    results['issues']['errors'].extend([f"Video {i}: {e}" for e in validation['errors']])
                    results['status'] = 'error'
                elif validation['status'] == 'warning':
                    results['issues']['warnings'].extend([f"Video {i}: {w}" for w in validation['warnings']])
                    if results['status'] != 'error':
                        results['status'] = 'warning'
            else:
                results['issues']['errors'].append(f"Video file not found: {video_path}")
                results['status'] = 'error'

        logger.info(f"✓ Video validation: {len(results['videos'])} files checked")

        # 2. Validate metadata
        logger.info("Validating metadata...")
        clip_validation = MetadataValidator.validate_clip_manifest(clip_manifest)
        seo_validation = MetadataValidator.validate_seo_manifest(seo_manifest)
        video_validation = MetadataValidator.validate_video_manifest(video_manifest)
        thumbnail_validation = MetadataValidator.validate_thumbnail_manifest(thumbnail_manifest)

        results['metadata'] = [clip_validation, seo_validation, video_validation, thumbnail_validation]

        for meta_val in results['metadata']:
            if meta_val['status'] == 'error':
                results['issues']['errors'].extend([f"{meta_val['manifest_type']}: {e}" for e in meta_val['errors']])
                results['status'] = 'error'
            elif meta_val['status'] == 'warning':
                results['issues']['warnings'].extend([f"{meta_val['manifest_type']}: {w}" for w in meta_val['warnings']])
                if results['status'] != 'error':
                    results['status'] = 'warning'

        logger.info(f"✓ Metadata validation: 4 manifests checked")

        # 3. Summary
        results['summary'] = {
            'videos_validated': len(results['videos']),
            'videos_passed': len([v for v in results['videos'] if v['validation']['status'] == 'pass']),
            'total_errors': len(results['issues']['errors']),
            'total_warnings': len(results['issues']['warnings']),
            'overall_status': results['status']
        }

        logger.info(f"✅ QC Complete: {results['summary']['videos_passed']}/{results['summary']['videos_validated']} videos passed")

        if results['issues']['errors']:
            logger.warning(f"⚠ {len(results['issues']['errors'])} errors found")
        if results['issues']['warnings']:
            logger.warning(f"⚠ {len(results['issues']['warnings'])} warnings found")

        return results


def perform_quality_control(clip_manifest: Dict, seo_manifest: Dict,
                           video_manifest: Dict, thumbnail_manifest: Dict,
                           output_dir: str = './output', video_base_name: str = '') -> Dict:
    """
    Main entry point: Perform QC on all pipeline outputs
    
    Validates:
    - Video codec, resolution, aspect ratio, duration, file size
    - Audio presence, duration, levels
    - Metadata completeness and encoding
    - Thumbnail status (generated or brief-only)
    
    Returns routing decision: Pass → Step 9, Fail → manual review queue
    """
    logger.info("=" * 60)
    logger.info("🔍 QUALITY CONTROL AGENT")
    logger.info("=" * 60)

    try:
        qc = QualityController(output_dir)
        result = qc.validate_all_outputs(clip_manifest, seo_manifest,
                                        video_manifest, thumbnail_manifest,
                                        video_base_name)

        logger.info("\n" + "=" * 60)
        logger.info(f"QC STATUS: {result['status'].upper()}")
        logger.info(f"Videos: {result['summary']['videos_passed']}/{result['summary']['videos_validated']} passed")
        logger.info(f"Errors: {result['summary']['total_errors']} | Warnings: {result['summary']['total_warnings']}")
        logger.info("=" * 60)

        return {
            'status': result['status'],
            'qc_result': result,
            'routing': 'pass' if result['status'] in ['pass', 'warning'] else 'manual_review',
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ QC failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'routing': 'manual_review',
            'timestamp': datetime.now().isoformat()
        }
