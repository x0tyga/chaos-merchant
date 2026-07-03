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
from agents.trend_intelligence import generate_daily_trend_intelligence
from agents.competitor_monitor import CompetitorMonitor
from core.pipeline import run_pipeline
from core.scheduler import initialize_scheduler


def verify_environment():
    """Verify required environment variables and dependencies"""
    required_vars = ['ANTHROPIC_API_KEY', 'YOUTUBE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.error(f"Missing environment variables: {', '.join(missing_vars)}")
        logger.error("Please update your .env file")
        return False

    # Verify directories at the CONFIGURED paths (INPUT_DIR/OUTPUT_DIR/DATA_DIR),
    # not hardcoded relative names - so .env path configuration actually takes effect
    for env_var, default in [('INPUT_DIR', './input'), ('OUTPUT_DIR', './output'), ('DATA_DIR', './data')]:
        directory = os.getenv(env_var, default)
        Path(directory).mkdir(parents=True, exist_ok=True)
        logger.info(f"  {env_var}: {directory}")

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

    # Initialize scheduler with agent registration
    scheduler = initialize_scheduler()

    # Register Trend Intelligence - daily 7am, priority 10
    scheduler.schedule_job(
        'trend_intelligence',
        lambda: generate_daily_trend_intelligence(),
        '07:00',
        quota_priority=10
    )

    # Register Competitor Monitor - every 3 hours, priority 50
    competitor_monitor = CompetitorMonitor(quota_tracker=scheduler.quota)
    scheduler.schedule_every_n_hours(
        'competitor_monitor',
        lambda: competitor_monitor.check_competitors(),
        3,
        quota_priority=50
    )

    # Start scheduler in background thread
    scheduler_thread = scheduler.run_in_thread()

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
