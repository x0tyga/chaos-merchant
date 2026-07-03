"""
Scheduler - Coordinates all agent execution with quota management and double-fire prevention
"""

import schedule
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Callable, Optional
import threading
import time

logger = logging.getLogger(__name__)


class QuotaTracker:
    """Tracks YouTube API quota usage and enforces prioritization"""

    DAILY_QUOTA = 10000  # YouTube Data API default daily quota

    def __init__(self, tracker_path: str = './data/quota_tracker.json'):
        self.tracker_path = Path(tracker_path)
        self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tracker()

    def _init_tracker(self):
        """Initialize quota tracking file"""
        if not self.tracker_path.exists():
            tracker = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'quota_used': 0,
                'quota_remaining': self.DAILY_QUOTA,
                'operations': []
            }
            self._save_tracker(tracker)
            logger.info(f"✓ Quota tracker initialized: {self.DAILY_QUOTA}/day")

    def _load_tracker(self) -> Dict:
        """Load quota data"""
        try:
            with open(self.tracker_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Failed to load tracker: {e}")
            return {'quota_used': 0, 'quota_remaining': self.DAILY_QUOTA}

    def _save_tracker(self, tracker: Dict):
        """Save quota data"""
        try:
            with open(self.tracker_path, 'w') as f:
                json.dump(tracker, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Failed to save tracker: {e}")

    def _reset_if_new_day(self):
        """Reset quota if date has changed"""
        tracker = self._load_tracker()
        today = datetime.now().strftime('%Y-%m-%d')

        if tracker.get('date') != today:
            tracker['date'] = today
            tracker['quota_used'] = 0
            tracker['quota_remaining'] = self.DAILY_QUOTA
            tracker['operations'] = []
            self._save_tracker(tracker)
            logger.info(f"✓ Quota reset for new day: {self.DAILY_QUOTA}/day")

    def use_quota(self, operation: str, quota_cost: int = 1) -> bool:
        """Record quota usage"""
        self._reset_if_new_day()
        tracker = self._load_tracker()

        remaining = tracker.get('quota_remaining', self.DAILY_QUOTA)
        if remaining < quota_cost:
            logger.error(f"❌ Quota insufficient: need {quota_cost}, have {remaining}")
            return False

        tracker['quota_used'] = tracker.get('quota_used', 0) + quota_cost
        tracker['quota_remaining'] = self.DAILY_QUOTA - tracker['quota_used']
        tracker['operations'].append({
            'operation': operation,
            'quota_cost': quota_cost,
            'timestamp': datetime.now().isoformat()
        })

        self._save_tracker(tracker)
        logger.info(f"✓ Quota used: {operation} ({quota_cost}) - {tracker['quota_remaining']}/{self.DAILY_QUOTA} remaining")
        return True

    def is_quota_low(self, threshold_percent: int = 20) -> bool:
        """Check if quota is running low"""
        tracker = self._load_tracker()
        remaining = tracker.get('quota_remaining', self.DAILY_QUOTA)
        threshold = (self.DAILY_QUOTA * threshold_percent) / 100
        return remaining < threshold

    def get_status(self) -> Dict:
        """Get current quota status"""
        self._reset_if_new_day()
        tracker = self._load_tracker()
        return {
            'quota_used': tracker.get('quota_used', 0),
            'quota_remaining': tracker.get('quota_remaining', self.DAILY_QUOTA),
            'quota_percent_used': (tracker.get('quota_used', 0) / self.DAILY_QUOTA) * 100,
            'is_low': self.is_quota_low()
        }


class JobTracker:
    """Prevents double-firing and re-running completed jobs"""

    def __init__(self, tracker_path: str = './data/job_tracker.json'):
        self.tracker_path = Path(tracker_path)
        self.tracker_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_tracker()

    def _init_tracker(self):
        """Initialize job tracking file"""
        if not self.tracker_path.exists():
            tracker = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'jobs': {}
            }
            self._save_tracker(tracker)

    def _load_tracker(self) -> Dict:
        """Load job data"""
        try:
            with open(self.tracker_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Failed to load job tracker: {e}")
            return {'date': datetime.now().strftime('%Y-%m-%d'), 'jobs': {}}

    def _save_tracker(self, tracker: Dict):
        """Save job data"""
        try:
            with open(self.tracker_path, 'w') as f:
                json.dump(tracker, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Failed to save job tracker: {e}")

    def _reset_if_new_day(self):
        """Reset jobs on new day"""
        tracker = self._load_tracker()
        today = datetime.now().strftime('%Y-%m-%d')

        if tracker.get('date') != today:
            tracker['date'] = today
            tracker['jobs'] = {}
            self._save_tracker(tracker)
            logger.info("✓ Job tracker reset for new day")

    def mark_running(self, job_name: str) -> bool:
        """Mark job as currently running"""
        self._reset_if_new_day()
        tracker = self._load_tracker()

        if job_name in tracker['jobs'] and tracker['jobs'][job_name].get('status') == 'running':
            logger.warning(f"⚠ Job already running, skipping: {job_name}")
            return False

        tracker['jobs'][job_name] = {
            'status': 'running',
            'start_time': datetime.now().isoformat()
        }
        self._save_tracker(tracker)
        logger.info(f"✓ Job marked running: {job_name}")
        return True

    def mark_complete(self, job_name: str, success: bool, duration: float, quota_used: int = 0):
        """Mark job as completed"""
        tracker = self._load_tracker()
        tracker['jobs'][job_name] = {
            'status': 'success' if success else 'failed',
            'start_time': tracker['jobs'].get(job_name, {}).get('start_time'),
            'end_time': datetime.now().isoformat(),
            'duration_seconds': duration,
            'quota_used': quota_used
        }
        self._save_tracker(tracker)

        status_icon = "✓" if success else "❌"
        logger.info(f"{status_icon} Job complete: {job_name} ({duration:.1f}s)")

    def already_run_today(self, job_name: str) -> bool:
        """Check if job already completed successfully today"""
        self._reset_if_new_day()
        tracker = self._load_tracker()

        job = tracker['jobs'].get(job_name, {})
        return job.get('status') == 'success'


class ChaosScheduler:
    """Main scheduler orchestrating all agents"""

    def __init__(self, quota_tracker: Optional[QuotaTracker] = None, job_tracker: Optional[JobTracker] = None):
        self.quota = quota_tracker or QuotaTracker()
        self.jobs = job_tracker or JobTracker()
        self.scheduled_jobs = {}
        self.running = False

        logger.info("✓ Scheduler initialized")

    def schedule_job(self, name: str, func: Callable, schedule_time: str, quota_priority: int = 100):
        """
        Schedule a job with priority for quota management
        quota_priority: lower = higher priority (0=critical, 100=lowest)
        """
        def wrapped_job():
            start = time.time()

            # Check if already running
            if not self.jobs.mark_running(name):
                logger.warning(f"⚠ Skipping {name} - job already running")
                return

            # Check quota if needed
            if quota_priority > 50 and self.quota.is_quota_low():
                logger.warning(f"⚠ Skipping {name} - quota low, prioritizing critical jobs")
                return

            try:
                logger.info(f"▶ Starting job: {name}")
                func()
                duration = time.time() - start
                self.jobs.mark_complete(name, success=True, duration=duration)
                logger.info(f"✓ Job complete: {name} ({duration:.1f}s)")
            except Exception as e:
                duration = time.time() - start
                logger.error(f"❌ Job failed: {name} - {e}")
                self.jobs.mark_complete(name, success=False, duration=duration)

        schedule.every().day.at(schedule_time).do(wrapped_job)
        self.scheduled_jobs[name] = {'func': func, 'priority': quota_priority}

        logger.info(f"✓ Job scheduled: {name} at {schedule_time} (priority: {quota_priority})")

    def schedule_every_n_hours(self, name: str, func: Callable, hours: int, quota_priority: int = 100):
        """Schedule job to run every N hours"""
        def wrapped_job():
            start = time.time()

            if not self.jobs.mark_running(name):
                logger.warning(f"⚠ Skipping {name} - job already running")
                return

            if quota_priority > 50 and self.quota.is_quota_low():
                logger.warning(f"⚠ Skipping {name} - quota low")
                return

            try:
                logger.info(f"▶ Starting job: {name}")
                func()
                duration = time.time() - start
                self.jobs.mark_complete(name, success=True, duration=duration)
            except Exception as e:
                duration = time.time() - start
                logger.error(f"❌ Job failed: {name} - {e}")
                self.jobs.mark_complete(name, success=False, duration=duration)

        schedule.every(hours).hours.do(wrapped_job)
        self.scheduled_jobs[name] = {'func': func, 'priority': quota_priority}

        logger.info(f"✓ Job scheduled: {name} every {hours}h (priority: {quota_priority})")

    def schedule_weekly(self, name: str, func: Callable, day: str, time: str, quota_priority: int = 100):
        """Schedule job to run weekly"""
        def wrapped_job():
            start = time.time()

            if not self.jobs.mark_running(name):
                logger.warning(f"⚠ Skipping {name} - job already running")
                return

            try:
                logger.info(f"▶ Starting job: {name}")
                func()
                duration = time.time() - start
                self.jobs.mark_complete(name, success=True, duration=duration)
            except Exception as e:
                duration = time.time() - start
                logger.error(f"❌ Job failed: {name} - {e}")
                self.jobs.mark_complete(name, success=False, duration=duration)

        getattr(schedule.every(), day).at(time).do(wrapped_job)
        self.scheduled_jobs[name] = {'func': func, 'priority': quota_priority}

        logger.info(f"✓ Job scheduled: {name} every {day} at {time} (priority: {quota_priority})")

    def run(self):
        """Start scheduler loop"""
        logger.info("=" * 70)
        logger.info("▶ SCHEDULER STARTING")
        logger.info("=" * 70)
        logger.info(f"Scheduled jobs: {len(self.scheduled_jobs)}")
        for name, info in self.scheduled_jobs.items():
            logger.info(f"  - {name} (priority: {info['priority']})")
        logger.info("=" * 70)

        self.running = True
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    def stop(self):
        """Stop scheduler"""
        self.running = False
        logger.info("✓ Scheduler stopped")

    def run_in_thread(self):
        """Run scheduler in background thread"""
        thread = threading.Thread(target=self.run, daemon=True)
        thread.start()
        return thread

    def get_status(self) -> Dict:
        """Get scheduler status"""
        return {
            'running': self.running,
            'scheduled_jobs': list(self.scheduled_jobs.keys()),
            'quota_status': self.quota.get_status(),
            'pending_jobs': len(schedule.jobs),
            'next_run_seconds': schedule.idle_seconds if schedule.jobs else None
        }


def initialize_scheduler() -> ChaosScheduler:
    """
    Initialize scheduler with all agent jobs

    Schedules:
    - Daily 7am: Trend Intelligence (priority: 10)
    - Daily 9am: Analytics & Feedback (priority: 5)
    - Every 3h: Competitor Monitor (priority: 50)
    - Weekly Sunday 8pm: Comment Mining (priority: 80)
    - Weekly Sunday 9pm: Content Gap Report (priority: 80)

    YouTube API quota prioritization:
    - If quota running low (<20%), skip:
      1. Competitor Monitor (priority 50)
      2. Trend Intelligence YouTube calls (part of priority 10)
      3. Never skip: Analytics (priority 5)
    """

    logger.info("=" * 70)
    logger.info("🎬 INITIALIZING SCHEDULER")
    logger.info("=" * 70)

    scheduler = ChaosScheduler()

    # Note: Actual agent functions would be imported and registered here
    # This is the scheduling framework - agents connect via:
    # scheduler.schedule_job('trend_intelligence', trend_intel_func, '07:00', quota_priority=10)
    # scheduler.schedule_job('analytics_feedback', analytics_func, '09:00', quota_priority=5)
    # etc.

    logger.info("✓ Scheduler ready for agent registration")
    logger.info("  Call: scheduler.schedule_job(name, func, time, quota_priority)")
    logger.info("=" * 70)

    return scheduler
