"""
Watcher Agent - File system monitoring for Chaos Merchant
Monitors input folder for new video files and triggers the pipeline
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

logger = logging.getLogger(__name__)


class VideoFileHandler(FileSystemEventHandler):
    """Handles new video file events"""

    SUPPORTED_FORMATS = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm')

    def __init__(self, callback):
        """
        Initialize handler with callback function
        
        Args:
            callback: Function to call when new video is detected
        """
        self.callback = callback
        self.processed_files = set()

    def on_created(self, event):
        """Called when a file is created"""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Check if file is a video
        if file_path.suffix.lower() in self.SUPPORTED_FORMATS:
            # Debounce: wait a bit for file to finish writing
            if file_path not in self.processed_files:
                self.processed_files.add(file_path)
                logger.info(f"📹 New video detected: {file_path.name}")
                self.callback(str(file_path))

    def on_modified(self, event):
        """Called when a file is modified"""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Skip if already processed
        if file_path in self.processed_files:
            return


class Watcher:
    """Main watcher class for monitoring video input folder"""

    def __init__(self, input_dir='./input', callback=None):
        """
        Initialize the watcher
        
        Args:
            input_dir: Directory to monitor (default: ./input)
            callback: Function to call on new video (signature: func(video_path))
        """
        self.input_dir = Path(input_dir)
        self.callback = callback or self._default_callback
        self.observer = None
        self.event_handler = None

    def _default_callback(self, video_path):
        """Default callback logs the video path"""
        logger.info(f"✓ Video ready for processing: {video_path}")

    def start(self):
        """Start watching the input directory"""
        # Create input directory if it doesn't exist
        self.input_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"🔍 Starting watcher on: {self.input_dir.absolute()}")
        
        # Create event handler and observer
        self.event_handler = VideoFileHandler(self.callback)
        self.observer = Observer()
        self.observer.schedule(self.event_handler, str(self.input_dir), recursive=False)
        
        # Start observer
        self.observer.start()
        logger.info("✓ Watcher started successfully")
        
        return self

    def stop(self):
        """Stop watching the input directory"""
        if self.observer:
            logger.info("⏹️  Stopping watcher...")
            self.observer.stop()
            self.observer.join()
            logger.info("✓ Watcher stopped")

    def scan_existing(self):
        """Scan for existing videos in input folder"""
        if not self.input_dir.exists():
            logger.warning(f"Input directory does not exist: {self.input_dir}")
            return []
        
        existing_videos = []
        for file in self.input_dir.glob('*'):
            if file.suffix.lower() in VideoFileHandler.SUPPORTED_FORMATS:
                existing_videos.append(file)
                logger.info(f"📹 Found existing video: {file.name}")
        
        return existing_videos


def create_watcher(input_dir='./input', on_new_video=None):
    """
    Factory function to create and configure a watcher
    
    Args:
        input_dir: Directory to monitor
        on_new_video: Callback function for new videos
    
    Returns:
        Configured Watcher instance
    """
    return Watcher(input_dir=input_dir, callback=on_new_video)


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Test the watcher
    logger.info("Testing Watcher Agent...")
    
    def test_callback(video_path):
        logger.info(f"TEST: Video detected - {video_path}")
    
    watcher = create_watcher('./input', on_new_video=test_callback)
    watcher.start()
    
    try:
        logger.info("Watcher running. Press Ctrl+C to stop.")
        while True:
            pass
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        watcher.stop()
