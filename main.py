#!/usr/bin/env python3
"""
Chaos Merchant - Autonomous YouTube Shorts Production System
Main entry point for the application
"""

import os
import sys
import logging
import shutil
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --verify runs setup verification (core/setup_verification.py) and exits
# WITHOUT importing the full agent stack below - checked here, before
# those imports, so a genuinely broken/missing dependency in one of those
# modules can't crash the verification command itself, which is exactly
# the failure mode --verify exists to diagnose.
if '--verify' in sys.argv:
    from core.setup_verification import run_verification
    sys.exit(0 if run_verification() else 1)

# Configure logging - stdout (as before) plus a rotating file under
# LOG_DIR so the dashboard's Logs page has something real to tail. 10MB x 5
# backups is generous for text logs and self-limiting so it can never fill
# a disk unattended on a machine that runs for months.
LOG_DIR = Path(os.getenv('LOG_DIR', './logs'))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_DIR / 'chaos_merchant.log', maxBytes=10_000_000, backupCount=5)
    ]
)
logger = logging.getLogger(__name__)

# Import agents and core
from agents.watcher import create_watcher
from agents.trend_intelligence import generate_daily_trend_intelligence
from agents.competitor_monitor import CompetitorMonitor
from agents.analytics_feedback import run_analytics_feedback
from agents.comment_mining import run_comment_mining
from agents.thumbnail_research import run_thumbnail_research
from agents.clip_sourcing import run_clip_sourcing
from core.pipeline import run_pipeline
from core.scheduler import initialize_scheduler


def verify_environment():
    """
    Verify required environment variables and dependencies before starting.
    Hard-blocks (exit) on anything the pipeline cannot run at all without;
    warns loudly (but continues) on anything with a degraded-but-functional
    fallback, so the failure is visible here instead of 40 minutes into a
    pipeline run.
    """
    ok = True

    # --- Hard blockers: no possible fallback exists for these ---
    required_vars = ['ANTHROPIC_API_KEY', 'YOUTUBE_API_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"❌ Missing required environment variable(s): {', '.join(missing_vars)}")
        logger.error("   Fix: set these in your .env file")
        ok = False

    if not shutil.which('ffmpeg'):
        logger.error("❌ ffmpeg not found in PATH - video export cannot run without it")
        logger.error("   Fix (macOS): brew install ffmpeg")
        ok = False

    if not ok:
        return False

    # --- Soft warnings: pipeline can still run, but degraded ---

    # Voice synthesis: Kokoro (primary, needs package + valid model files) OR
    # ElevenLabs (fallback, needs API key + voice ID). Mirrors the exact
    # availability check generate_voiceover() uses at runtime - so this
    # catches the same "no voiceover engine available" failure here instead
    # of after Steps 1 completes.
    kokoro_ready = False
    try:
        import kokoro_onnx  # noqa: F401
        model_path = os.getenv('KOKORO_MODEL_PATH', 'kokoro-v1.0.onnx')
        voices_path = os.getenv('KOKORO_VOICES_PATH', 'voices-v1.0.bin')
        kokoro_ready = (
            os.path.exists(model_path) and os.path.getsize(model_path) > 1_000_000
            and os.path.exists(voices_path) and os.path.getsize(voices_path) > 1_000_000
        )
    except ImportError:
        pass

    elevenlabs_ready = bool(os.getenv('ELEVENLABS_API_KEY') and os.getenv('ELEVENLABS_VOICE_ID'))

    if not kokoro_ready and not elevenlabs_ready:
        logger.warning("⚠️  No voiceover engine available - pipeline WILL fail at Step 2 (Script + Voiceover)")
        logger.warning("   Fix: run setup.sh to auto-download Kokoro's model files, or set")
        logger.warning("        ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID in .env for the fallback engine")
    elif not kokoro_ready:
        logger.warning("⚠️  Kokoro (free, local) unavailable - falling back to ElevenLabs (paid) for every voiceover")

    # Captions: moviepy's TextClip(method='caption') shells out to ImageMagick.
    # There is no fallback - if this is missing, every short will silently
    # ship with no captions (the exact bug from last night's first run).
    if not (shutil.which('convert') or shutil.which('magick')):
        logger.warning("⚠️  ImageMagick not found - captions will NOT render on any short produced")
        logger.warning("   Fix (macOS): brew install imagemagick")
        logger.warning("   If already installed and captions still fail, check policy.xml")
        logger.warning("   (setup.sh attempts to auto-fix this - re-run it)")

    # Verify directories at the CONFIGURED paths (INPUT_DIR/OUTPUT_DIR/DATA_DIR),
    # not hardcoded relative names - so .env path configuration actually takes effect
    for env_var, default in [('INPUT_DIR', './input'), ('OUTPUT_DIR', './output'), ('DATA_DIR', './data')]:
        directory = os.getenv(env_var, default)
        Path(directory).mkdir(parents=True, exist_ok=True)
        logger.info(f"  {env_var}: {directory}")

    logger.info("✓ Environment verification passed")
    return True


def on_new_video(video_path):
    """
    Callback function when new video is detected. One video's failure must
    not crash the watcher/scheduler process (other videos still need to be
    processed, the scheduler still needs to run), so the exception is
    caught here rather than left to propagate - but it must be logged with
    a full traceback. This was previously the actual point where a Video
    Production crash (e.g. an interrupted ffmpeg export) died silently:
    core/pipeline.py's run() does re-raise on failure, but this was the
    last catch in the chain, and it only logged str(e) with no traceback
    and no re-raise - so a real production crash left nothing in the logs
    beyond a single vague line, and the watcher loop carried on as if
    nothing had happened.
    """
    logger.info(f"🚀 Processing video: {video_path}")
    try:
        result = run_pipeline(video_path)
        logger.info(f"✅ Video processed: {result['status']}")
    except Exception:
        logger.exception(f"❌ Error processing video: {video_path}")


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

    # Register Clip Sourcing - run times come from config/source_schedule.json
    # (default 07:30/18:00: morning run right after Trend Intelligence, so
    # it acts on same-day-fresh trends; evening run to catch same-day
    # virality) instead of hardcoded here, editable via the dashboard's
    # Sources tab. agents/clip_sourcing.py's _apply_calendar_guidance()
    # reads the SAME config file to derive runs-per-day, so the two can
    # never drift out of sync the way two independently hardcoded numbers
    # could. Doesn't touch the YouTube Data API quota at all (yt-dlp
    # scraping + PRAW, not the tracked API), so priority here only matters
    # for jobs.mark_running()'s double-fire prevention, not quota gating.
    from agents.clip_sourcing import _load_sourcing_schedule
    for run_time in _load_sourcing_schedule():
        scheduler.schedule_job(
            f'clip_sourcing_{run_time.replace(":", "")}',
            lambda: run_clip_sourcing(),
            run_time,
            quota_priority=40
        )

    # Register Competitor Monitor - every 3 hours, priority 50
    competitor_monitor = CompetitorMonitor(quota_tracker=scheduler.quota)
    scheduler.schedule_every_n_hours(
        'competitor_monitor',
        lambda: competitor_monitor.check_competitors(),
        3,
        quota_priority=50
    )

    # Register Analytics & Feedback - daily 9am, priority 30
    # (48h/7d performance marks, spike detection, hook library score updates)
    scheduler.schedule_job(
        'analytics_feedback',
        lambda: run_analytics_feedback(),
        '09:00',
        quota_priority=30
    )

    # Register Comment Mining - weekly Sunday 10am, priority 70
    scheduler.schedule_weekly(
        'comment_mining',
        lambda: run_comment_mining(),
        'sunday',
        '10:00',
        quota_priority=70
    )

    # Register Thumbnail Research - weekly Sunday 10am, priority 70
    scheduler.schedule_weekly(
        'thumbnail_research',
        lambda: run_thumbnail_research(),
        'sunday',
        '10:00',
        quota_priority=70
    )

    # Register Posting Queue Drain - periodically checks core/posting_queue.py
    # for anything due to publish. AUTO_POST_YOUTUBE gates this at drain time
    # (checked fresh every tick, not cached) - registering this job
    # unconditionally is safe and correct even with the flag off: drain_due_posts()
    # itself logs "disabled" and returns immediately when AUTO_POST_YOUTUBE
    # is false, exactly like every other AUTO_POST_* check in this codebase.
    from core.posting_queue import drain_due_posts
    posting_drain_minutes = int(os.getenv('POSTING_QUEUE_DRAIN_MINUTES', '15'))
    scheduler.schedule_every_n_minutes(
        'posting_queue_drain',
        lambda: drain_due_posts(),
        posting_drain_minutes,
        quota_priority=20
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
