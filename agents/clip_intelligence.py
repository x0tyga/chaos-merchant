"""
Clip Intelligence Agent - Scene detection and engagement scoring
Analyzes raw video to identify best clips for YouTube Shorts
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
import numpy as np
import cv2
import librosa
import librosa.feature

logger = logging.getLogger(__name__)


class VideoAnalyzer:
    """Analyzes video for scene changes and engagement potential"""

    def __init__(self, video_path):
        self.video_path = Path(video_path)
        self.cap = cv2.VideoCapture(str(self.video_path))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.frame_count / self.fps if self.fps > 0 else 0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def detect_scene_changes(self, threshold=25.0):
        """
        Detect scene changes using histogram comparison
        
        Args:
            threshold: Sensitivity threshold (0-100, higher = fewer cuts detected)
        
        Returns:
            list: Frame indices where scene changes occur
        """
        logger.info("🔍 Detecting scene changes...")
        scene_changes = []
        prev_frame = None
        frame_idx = 0

        while True:
            ret, frame = self.cap.read()
            if not ret:
                break

            if prev_frame is not None:
                # Convert to grayscale for comparison
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)

                # Compare histograms
                hist_curr = cv2.calcHist([gray], [0], None, [256], [0, 256])
                hist_prev = cv2.calcHist([prev_gray], [0], None, [256], [0, 256])

                # Normalize and compare
                hist_curr = cv2.normalize(hist_curr, hist_curr).flatten()
                hist_prev = cv2.normalize(hist_prev, hist_prev).flatten()
                difference = cv2.compareHist(hist_curr, hist_prev, cv2.HISTCMP_BHATTACHARYYA)

                # If difference exceeds threshold, it's a scene change
                if difference > (threshold / 100.0):
                    scene_changes.append(frame_idx)

            prev_frame = frame
            frame_idx += 1

            if frame_idx % 300 == 0:  # Log progress every 300 frames (~10s at 30fps)
                logger.info(f"  Analyzed {frame_idx}/{self.frame_count} frames ({frame_idx/self.frame_count*100:.1f}%)")

        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # Reset to start
        logger.info(f"✓ Found {len(scene_changes)} scene changes")
        return scene_changes

    def extract_audio_features(self):
        """
        Extract audio features for engagement scoring
        
        Returns:
            dict: Audio features by time
        """
        logger.info("🎵 Extracting audio features...")
        audio_path = str(self.video_path)
        
        try:
            # Load audio
            y, sr = librosa.load(audio_path, sr=22050)
            
            # Extract features
            energy = librosa.feature.rms(y=y)[0]
            spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
            zero_crossing_rate = librosa.feature.zero_crossing_rate(y)[0]
            
            # Compute frame times
            times = librosa.frames_to_time(np.arange(len(energy)), sr=sr)
            
            features = {
                'energy': energy.tolist(),
                'spectral_centroid': spectral_centroid.tolist(),
                'zero_crossing_rate': zero_crossing_rate.tolist(),
                'times': times.tolist(),
                'sr': sr
            }
            
            logger.info(f"✓ Extracted audio features ({len(energy)} frames)")
            return features
            
        except Exception as e:
            logger.warning(f"⚠️  Could not extract audio features: {e}")
            return None

    def segment_video(self, scene_changes, min_duration=None, max_duration=None):
        """
        Create video segments based on scene changes
        
        Shorter clips (15-45s) improve algorithm completion rate at launch by:
        - Reducing processing time per clip
        - Minimizing speech-to-silence segments
        - Enabling faster iteration and testing
        - Balancing content variety across shorts
        
        Args:
            scene_changes: List of frame indices with scene changes
            min_duration: Minimum segment duration in seconds (default: env var or 15)
            max_duration: Maximum segment duration in seconds (default: env var or 45)
        
        Returns:
            list: Segment dictionaries
        """
        # Load duration defaults from environment (configurable)
        if min_duration is None:
            min_duration = int(os.getenv('MIN_CLIP_DURATION', 15))
        if max_duration is None:
            max_duration = int(os.getenv('MAX_CLIP_DURATION', 45))
        
        logger.info(f"✂️  Creating video segments ({min_duration}s-{max_duration}s)...")
        segments = []

        # Add segment boundaries
        boundaries = [0] + scene_changes + [self.frame_count]

        for i in range(len(boundaries) - 1):
            start_frame = boundaries[i]
            end_frame = boundaries[i + 1]

            start_time = start_frame / self.fps
            end_time = end_frame / self.fps
            duration = end_time - start_time

            # Filter by duration
            if min_duration <= duration <= max_duration:
                segments.append({
                    'index': len(segments),
                    'start_frame': int(start_frame),
                    'end_frame': int(end_frame),
                    'start_time': float(start_time),
                    'end_time': float(end_time),
                    'duration': float(duration),
                    'scene_change_confidence': 0.85,  # High confidence for detected cuts
                })

        # Fallback: scene-change detection found no usable segments. This is
        # common on continuous gameplay footage with no sharp visual cuts -
        # 0 scene changes collapses boundaries to a single segment spanning
        # the entire video, which almost never fits [min_duration,
        # max_duration] and yields zero segments -> zero clips downstream,
        # no matter how scoring/thresholds are tuned. Without this fallback,
        # real footage with weak scene cuts always produces 0 clips.
        if not segments:
            logger.warning(
                f"⚠ No segments from scene-change boundaries "
                f"({len(scene_changes)} scene change(s) found) - "
                f"falling back to fixed-interval segmentation"
            )
            segments = self._fixed_interval_segments(min_duration, max_duration)

        logger.info(f"✓ Created {len(segments)} segments")
        return segments

    def _fixed_interval_segments(self, min_duration, max_duration):
        """
        Split the whole video into fixed-length, non-overlapping windows.
        Used when scene-change detection doesn't yield any boundaries that
        fit the configured duration range (e.g. continuous footage with no
        sharp cuts), so clip selection always has real candidates to work
        with instead of silently producing zero segments.
        """
        window_seconds = (min_duration + max_duration) / 2
        window_frames = int(window_seconds * self.fps)

        segments = []
        if window_frames <= 0:
            return segments

        start_frame = 0
        while start_frame < self.frame_count:
            end_frame = min(start_frame + window_frames, self.frame_count)
            start_time = start_frame / self.fps
            end_time = end_frame / self.fps
            duration = end_time - start_time

            if duration >= min_duration:
                segments.append({
                    'index': len(segments),
                    'start_frame': int(start_frame),
                    'end_frame': int(end_frame),
                    'start_time': float(start_time),
                    'end_time': float(end_time),
                    'duration': float(duration),
                    'scene_change_confidence': 0.3,  # No detected cut, fixed window
                })

            start_frame += window_frames

        return segments

    def score_segments(self, segments, audio_features):
        """
        Score segments for engagement potential
        
        Args:
            segments: List of segment dicts
            audio_features: Audio features dict
        
        Returns:
            list: Segments with engagement scores
        """
        logger.info("📊 Scoring segments...")
        
        if not audio_features:
            # Fallback: score by duration variation
            avg_duration = np.mean([s['duration'] for s in segments])
            for seg in segments:
                # Segments near average duration tend to be better balanced
                duration_score = 1.0 - abs(seg['duration'] - avg_duration) / avg_duration
                seg['engagement_score'] = float(np.clip(duration_score, 0.3, 1.0))
                seg['viral_score'] = round(seg['engagement_score'] * 10, 2)
            return segments
        
        # Extract audio for scoring
        energy = np.array(audio_features['energy'])
        sr = audio_features['sr']
        hop_length = 512
        
        for seg in segments:
            # Convert time to frames in audio
            start_frame_audio = int(seg['start_time'] * sr / hop_length)
            end_frame_audio = int(seg['end_time'] * sr / hop_length)
            
            # Clamp to valid range
            start_frame_audio = max(0, min(start_frame_audio, len(energy) - 1))
            end_frame_audio = max(0, min(end_frame_audio, len(energy)))
            
            if start_frame_audio >= end_frame_audio:
                seg['engagement_score'] = 0.5
                seg['viral_score'] = 5.0
                continue

            # Calculate energy metrics
            segment_energy = energy[start_frame_audio:end_frame_audio]
            energy_mean = np.mean(segment_energy) if len(segment_energy) > 0 else 0.5
            energy_variance = np.var(segment_energy) if len(segment_energy) > 0 else 0

            # Score: combination of energy level and variation
            # Higher energy + variation = more dynamic = higher engagement
            energy_score = np.clip(energy_mean, 0, 1)
            variance_score = np.clip(energy_variance / 0.1, 0, 1)  # Normalize variance

            engagement = (energy_score * 0.6 + variance_score * 0.4)
            seg['engagement_score'] = float(np.clip(engagement, 0.2, 1.0))
            # viral_score rescales engagement_score (0.2-1.0) onto a 0-10
            # scale for a more intuitive threshold (VIRAL_SCORE_THRESHOLD)
            seg['viral_score'] = round(seg['engagement_score'] * 10, 2)

            # Audio features
            seg['audio_features'] = {
                'energy': float(energy_mean),
                'loudness': float(energy_mean * 100),  # Normalized to 0-100
                'speech_presence': float(np.mean(audio_features['zero_crossing_rate'][start_frame_audio:end_frame_audio]) if len(segment_energy) > 0 else 0.5)
            }
        
        logger.info(f"✓ Scored {len(segments)} segments")
        return segments

    def select_top_clips(self, segments, num_clips=7):
        """
        Select top clips based on viral_score (0-10 scale), preferring
        segments that clear VIRAL_SCORE_THRESHOLD. Always backfills with the
        next-best scoring segments if too few clear the threshold, so this
        never returns zero clips when segments exist - a strict threshold
        should narrow quality, not silently zero out the whole batch.

        Args:
            segments: Scored segment list
            num_clips: Number of top clips to select

        Returns:
            list: Top clip indices
        """
        if not segments:
            logger.warning("⚠ No segments available to select clips from")
            return []

        threshold = float(os.getenv('VIRAL_SCORE_THRESHOLD', 3.0))

        # Sort by viral_score (falls back to engagement_score * 10 if missing)
        sorted_segments = sorted(
            enumerate(segments),
            key=lambda x: x[1].get('viral_score', x[1].get('engagement_score', 0) * 10),
            reverse=True
        )

        qualifying = [
            (idx, seg) for idx, seg in sorted_segments
            if seg.get('viral_score', 0) >= threshold
        ]

        if len(qualifying) >= num_clips:
            selected = qualifying[:num_clips]
        else:
            if qualifying:
                logger.warning(
                    f"⚠ Only {len(qualifying)} segment(s) cleared "
                    f"VIRAL_SCORE_THRESHOLD ({threshold}) - backfilling with "
                    f"next-best scoring segments"
                )
            else:
                logger.warning(
                    f"⚠ No segments cleared VIRAL_SCORE_THRESHOLD ({threshold}) "
                    f"- using best-available segments instead of returning zero clips"
                )
            selected = sorted_segments[:num_clips]

        top_indices = [idx for idx, seg in selected]
        top_indices.sort()  # Maintain chronological order

        logger.info(
            f"✓ Selected top {len(top_indices)} clips "
            f"(threshold: {threshold}, {len(qualifying)}/{len(segments)} cleared threshold)"
        )
        return top_indices

    def close(self):
        """Release video resources"""
        if self.cap:
            self.cap.release()


def analyze_video(video_path, num_clips=7, scene_threshold=25.0):
    """
    Main function to analyze video and generate clip manifest

    Args:
        video_path: Path to video file
        num_clips: Number of clips to extract (default: 7)
        scene_threshold: Scene detection sensitivity (0-100)

    Returns:
        dict: Analysis manifest with clip data
    """
    logger.info(f"🎬 Analyzing video: {video_path}")

    analyzer = VideoAnalyzer(video_path)

    try:
        # Autonomously-sourced clips (agents/clip_sourcing.py) are often
        # already short-form (a Reddit clip, a single viral YouTube short)
        # rather than a longer compilation for scene-detection to slice up
        # - forcing scene detection/segmentation on a video that's already
        # shorter than a single target segment can't produce a sensible
        # multi-clip split anyway. This check is provenance-agnostic (it
        # looks at the file's actual duration, not who/what produced it),
        # so a short manually-dropped clip benefits identically - it no
        # longer wastes time trying to force itself into 15-45s segments
        # that don't fit.
        short_clip_max_seconds = float(os.getenv('SHORT_CLIP_MAX_SECONDS', 90))
        if 0 < analyzer.duration <= short_clip_max_seconds:
            logger.info(
                f"ℹ Source video is {analyzer.duration:.1f}s (<= {short_clip_max_seconds}s) - "
                f"already short-form, skipping scene-detection/segmentation and mapping the "
                f"whole file to a single clip instead of slicing it"
            )
            # engagement_score/viral_score are set to the maximum of their
            # scales rather than measured: this clip already passed the
            # sourcing agent's popularity/copyright gate as worth using in
            # its entirety, so there's no "pick the best sub-segment"
            # decision left to make - the whole file IS the segment. Left
            # at the max also means a genuinely good already-viral clip
            # isn't artificially blocked from the Reaction format's
            # viral_score gate (agents/format_selector.py) just because
            # this path skips real per-segment scoring.
            segment = {
                'index': 0,
                'start_frame': 0,
                'end_frame': analyzer.frame_count,
                'start_time': 0.0,
                'end_time': float(analyzer.duration),
                'duration': float(analyzer.duration),
                'scene_change_confidence': 1.0,
                'engagement_score': 1.0,
                'viral_score': 10.0,
                'audio_features': {'energy': 0.5, 'loudness': 50.0, 'speech_presence': 0.5},
            }
            manifest = {
                'video_path': str(video_path),
                'duration': analyzer.duration,
                'fps': analyzer.fps,
                'resolution': {'width': analyzer.width, 'height': analyzer.height},
                'clips': [segment],
                'top_clip_indices': [0],
                'top_clips': [segment],
                'short_native': True,
                'generated_at': datetime.now().isoformat()
            }
            logger.info("✅ Analysis complete (short-native path): 1 segment, 1 selected")
            return manifest

        # Detect scene changes
        scene_changes = analyzer.detect_scene_changes(threshold=scene_threshold)
        
        # Create segments (uses MIN_CLIP_DURATION and MAX_CLIP_DURATION from env)
        segments = analyzer.segment_video(scene_changes)
        
        # Extract audio features
        audio_features = analyzer.extract_audio_features()
        
        # Score segments
        segments = analyzer.score_segments(segments, audio_features)
        
        # Select top clips
        top_clip_indices = analyzer.select_top_clips(segments, num_clips=num_clips)
        
        # Build manifest
        manifest = {
            'video_path': str(video_path),
            'duration': analyzer.duration,
            'fps': analyzer.fps,
            'resolution': {
                'width': analyzer.width,
                'height': analyzer.height
            },
            'clips': segments,
            'top_clip_indices': top_clip_indices,
            'top_clips': [segments[i] for i in top_clip_indices],
            'generated_at': datetime.now().isoformat()
        }
        
        logger.info(f"✅ Analysis complete: {len(segments)} segments, {len(top_clip_indices)} selected")
        
        return manifest
        
    finally:
        analyzer.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python clip_intelligence.py <video_path>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    result = analyze_video(video_path)
    print(json.dumps(result, indent=2))
