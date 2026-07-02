#!/usr/bin/env python3
"""
Chaos Merchant - Autonomous YouTube Shorts Production System
Main entry point for the application
"""

import os
import sys
import logging
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import agents and core
from agents.watcher import create_watcher
from core.pipeline import run_pipeline


def verify_environment():
    """Verify required environment variables and dependencies"""
    required_vars = ['ANTHROPIC_API_KEY', 'YOUTUBE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please update your .env file")
        return False
    
    # Verify directories
    for directory in ['input', 'output', 'data']:
        Path(directory).mkdir(exist_ok=True)
    
    logger.info("✓ Environment verification passed")
    return True


def on_new_video(video_path):
    """Callback function when new video is detected"""
    logger.info(f"🚀 Processing video: {video_path}")
    try:
        result = run_pipeline(video_path)
        logger.info(f"✅ Video processed: {result['status']}")
    except Exception as e:
        logger.error(f"❌ Error processing video: {e}")


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("🎬 Chaos Merchant - Starting")
    logger.info("=" * 60)
    
    if not verify_environment():
        sys.exit(1)
    
    # Create and start watcher
    input_dir = os.getenv('INPUT_DIR', './input')
    logger.info(f"📁 Input directory: {input_dir}")
    
    watcher = create_watcher(input_dir, on_new_video=on_new_video)
    watcher.start()
    
    # Scan for existing videos
    existing = watcher.scan_existing()
    if existing:
        logger.info(f"Found {len(existing)} existing video(s)")
        for video in existing:
            on_new_video(str(video))
    
    try:
        logger.info("✓ System ready. Watching for new videos...")
        logger.info("Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n⏹️  Shutting down...")
        watcher.stop()
        logger.info("✓ Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        watcher.stop()
        sys.exit(1)


if __name__ == "__main__":
    main()
