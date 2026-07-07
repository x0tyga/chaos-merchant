"""
Posting Schedule Optimizer - picks WHAT HOUR of the day to publish each
autonomously-queued Short, so core/posting_queue.py spaces posts out at
times that actually correlate with strong performance instead of firing
everything the instant QC passes.

DATA SOURCE NOTE (read before changing this): the YouTube Analytics API
does not expose a documented "audience active by hour" report - the "When
your viewers are on YouTube" chart in YouTube Studio is not backed by any
public Analytics API dimension/metric as of this writing. Reviewed the
current Analytics API dimensions/metrics reference to confirm this before
writing the fallback below, rather than assuming or faking a call that
doesn't exist.

The real, obtainable signal this uses instead: THIS channel's own history
of which hour-of-day a Short was actually posted at, correlated with that
Short's own subsequent performance (views/ctr/retention_30s/viral_score,
already tracked by agents/analytics_feedback.py once a Short has real
YouTube data). That's arguably a better optimization target than generic
"audience online" data anyway - it's the actual outcome metric, not a
proxy for it - and it's built entirely from data this system already
collects, no new API surface needed.

Until there's enough posting history to compute that (MIN_SAMPLES_FOR_REAL_DATA),
falls back to DEFAULT_OPTIMAL_HOURS: fixed, generically reasonable Shorts
posting windows (late morning, early evening, prime evening), so a brand
new channel still gets sensibly spaced-out posting from day one.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

# Generically reasonable Shorts posting windows for a channel with no
# performance history yet - not a real optimization, just sane defaults.
DEFAULT_OPTIMAL_HOURS = [12, 17, 20]

MIN_SAMPLES_FOR_REAL_DATA = 5


class PostingScheduleOptimizer:
    def __init__(self, data_dir: str = './data'):
        self.data_dir = data_dir
        self._db_path = None

    def _db(self) -> str:
        if self._db_path is None:
            from pathlib import Path
            self._db_path = str(Path(self.data_dir) / 'chaos_merchant.db')
        return self._db_path

    def get_optimal_hours(self, count: int = 3) -> List[int]:
        """
        Returns up to `count` distinct hour-of-day ints (0-23), best
        first. See module docstring for exactly what "best" means and why.
        """
        try:
            samples = self._get_hourly_performance()
        except Exception as e:
            logger.warning(f"⚠ Could not compute hourly performance, using default posting hours: {e}")
            samples = {}

        total_samples = sum(s['count'] for s in samples.values())
        if total_samples < MIN_SAMPLES_FOR_REAL_DATA:
            return self._padded_defaults(count)

        ranked = sorted(samples.items(), key=lambda kv: kv[1]['avg_viral_score'], reverse=True)
        hours = [hour for hour, _ in ranked][:count]
        if len(hours) < count:
            for h in DEFAULT_OPTIMAL_HOURS:
                if h not in hours:
                    hours.append(h)
                if len(hours) >= count:
                    break
        logger.info(f"✓ Optimal posting hours (real data, {total_samples} samples): {hours}")
        return hours[:count]

    def _padded_defaults(self, count: int) -> List[int]:
        if count <= len(DEFAULT_OPTIMAL_HOURS):
            return DEFAULT_OPTIMAL_HOURS[:count]
        # More slots requested than we have distinct default hours - repeat
        # the cycle rather than error (a high posts_per_day is a valid config).
        hours = []
        i = 0
        while len(hours) < count:
            hours.append(DEFAULT_OPTIMAL_HOURS[i % len(DEFAULT_OPTIMAL_HOURS)])
            i += 1
        return hours

    def _get_hourly_performance(self) -> dict:
        """
        Joins posting_queue's posted_at (when we actually posted it) against
        channel_shorts' viral_score (how it actually performed), grouped by
        hour-of-day. Both tables live in the same chaos_merchant.db, so a
        plain SQL join within one connection is enough - no cross-DB
        machinery needed.
        """
        import sqlite3
        conn = sqlite3.connect(self._db())
        cursor = conn.cursor()
        cursor.execute('''
            SELECT CAST(strftime('%H', pq.posted_at) AS INTEGER) AS hour,
                   COUNT(*), AVG(cs.viral_score)
            FROM posting_queue pq
            JOIN channel_shorts cs ON cs.youtube_id = pq.youtube_id
            WHERE pq.status = 'posted' AND cs.viral_score > 0
            GROUP BY hour
        ''')
        rows = cursor.fetchall()
        conn.close()
        return {
            int(hour): {'count': count, 'avg_viral_score': avg_viral or 0.0}
            for hour, count, avg_viral in rows if hour is not None
        }
