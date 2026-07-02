"""
Recovery System - Crash recovery and checkpoint management
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Manages crash recovery and checkpoints"""

    def __init__(self, checkpoint_dir='./data/checkpoints'):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def list_checkpoints(self):
        """List all available checkpoints"""
        if not self.checkpoint_dir.exists():
            return []
        
        checkpoints = list(self.checkpoint_dir.glob('*.json'))
        logger.info(f"Found {len(checkpoints)} checkpoint(s)")
        return checkpoints

    def get_failed_videos(self):
        """Get list of videos that failed during processing"""
        failed = []
        for checkpoint_file in self.list_checkpoints():
            with open(checkpoint_file, 'r') as f:
                checkpoint = json.load(f)
            failed.append({
                'video': checkpoint.get('video_path'),
                'step': checkpoint.get('step_name'),
                'checkpoint_file': checkpoint_file
            })
        return failed

    def cleanup_checkpoint(self, video_path):
        """Clean up checkpoint for completed video"""
        checkpoint_file = self.checkpoint_dir / f"{Path(video_path).stem}_checkpoint.json"
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info(f"Cleaned up checkpoint for {video_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    manager = RecoveryManager()
    failed = manager.get_failed_videos()
    print(f"Failed videos: {failed}")
