"""
Utility functions for Chaos Merchant
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def load_json(file_path):
    """Load JSON file"""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading JSON from {file_path}: {e}")
        return None


def save_json(data, file_path):
    """Save data as JSON"""
    try:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving JSON to {file_path}: {e}")
        return False


def get_video_duration_estimate(fps, frame_count):
    """Calculate video duration"""
    if fps <= 0:
        return 0
    return frame_count / fps


def time_to_frame(time_seconds, fps):
    """Convert seconds to frame number"""
    if fps <= 0:
        return 0
    return int(time_seconds * fps)


def frame_to_time(frame_number, fps):
    """Convert frame number to seconds"""
    if fps <= 0:
        return 0
    return frame_number / fps


def format_duration(seconds):
    """Format seconds to HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def create_batch_id():
    """Create unique batch ID from timestamp"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


if __name__ == "__main__":
    print("Chaos Merchant Utilities")
    print(f"Duration format: {format_duration(3661)}")
    print(f"Batch ID: {create_batch_id()}")
