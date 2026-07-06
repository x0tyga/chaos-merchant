"""
Memory System - Hook Library and Channel Memory
Brain of the Chaos Merchant system with obsessive logging and data integrity
"""

import sqlite3
import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)


class DatabaseBackup:
    """Automatic backup system for memory databases"""

    @staticmethod
    def backup_database(db_path: str, backup_dir: str = './data/backups'):
        """Create timestamped backup of database"""
        db_path = Path(db_path)
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        if db_path.exists():
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = backup_dir / f"{db_path.stem}_{timestamp}.db"
            try:
                shutil.copy2(db_path, backup_path)
                logger.info(f"✓ Database backed up: {backup_path.name}")
                return True
            except Exception as e:
                logger.error(f"❌ Backup failed: {e}")
                return False
        return False


class HookLibrary:
    """
    Tracks every hook ever used - the system's learned writing style library
    Prevents repetition, enables diversity preservation, auto-generates variations
    """

    # Minimum usage before a hook has enough signal to be judged proven/declining
    MIN_USAGE_FOR_JUDGMENT = 3
    PROVEN_WINNER_CTR = 0.08          # 8%+ CTR
    PROVEN_WINNER_RETENTION = 0.50    # 50%+ retention at 30s
    DECLINING_CTR = 0.02              # under 2% CTR
    DECLINING_RETENTION = 0.15        # under 15% retention at 30s

    def __init__(self, db_path: str = './data/chaos_merchant.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        logger.info(f"✓ HookLibrary initialized: {self.db_path}")

    def _init_database(self):
        """Create hook library table with strict schema"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")  # Write-ahead logging for integrity
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS hooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL UNIQUE,
                    style TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    ctr REAL DEFAULT 0.0,
                    retention_30s REAL DEFAULT 0.0,
                    first_used DATE,
                    last_used DATE,
                    status TEXT DEFAULT 'new',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS hook_usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hook_id INTEGER NOT NULL,
                    short_id TEXT,
                    video_title TEXT,
                    ctr REAL,
                    retention_30s REAL,
                    batch_id TEXT,
                    viral_score REAL,
                    used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (hook_id) REFERENCES hooks(id)
                )
            ''')

            # CREATE TABLE IF NOT EXISTS is a no-op on tables that already
            # exist, so batch_id/viral_score need an explicit migration for
            # any pre-existing database created before these columns did.
            for column, coltype in [('batch_id', 'TEXT'), ('viral_score', 'REAL')]:
                try:
                    cursor.execute(f'ALTER TABLE hook_usage_log ADD COLUMN {column} {coltype}')
                except sqlite3.OperationalError:
                    pass  # column already exists

            conn.commit()
            conn.close()
            logger.info("✓ Hook library database schema initialized")
        except Exception as e:
            logger.error(f"❌ Database init failed: {e}")
            raise

    def add_hook(self, text: str, style: str) -> bool:
        """Add new hook to library"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO hooks (text, style, first_used, last_used, status)
                VALUES (?, ?, ?, ?, 'new')
            ''', (text, style, datetime.now().date(), datetime.now().date()))

            conn.commit()
            hook_id = cursor.lastrowid
            conn.close()

            logger.info(f"✓ Hook added [ID:{hook_id}] Style:{style} Status:new")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"⚠ Hook already exists (deduped): {text[:50]}...")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to add hook: {e}")
            return False

    def get_or_create_hook(self, text: str, style: str) -> Optional[int]:
        """
        Get the hook's ID if it already exists (hooks.text is UNIQUE), or
        insert it as new and return the new ID either way. Unlike add_hook()
        (which returns bool and discards the ID on a duplicate), this always
        gives back a usable ID - needed by the pipeline to log usage without
        tracking IDs across separate runs/batches.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('SELECT id FROM hooks WHERE text = ?', (text,))
            row = cursor.fetchone()
            if row:
                conn.close()
                return row[0]

            cursor.execute('''
                INSERT INTO hooks (text, style, first_used, last_used, status)
                VALUES (?, ?, ?, ?, 'new')
            ''', (text, style, datetime.now().date(), datetime.now().date()))
            conn.commit()
            hook_id = cursor.lastrowid
            conn.close()

            logger.info(f"✓ Hook added [ID:{hook_id}] Style:{style} Status:new")
            return hook_id
        except Exception as e:
            logger.error(f"❌ Failed to get_or_create hook: {e}")
            return None

    def log_hook_production(self, hook_id: int, batch_id: str, viral_score: float,
                            short_id: str = None, title: str = None) -> bool:
        """
        Record that a hook was used in a produced batch, before any real
        YouTube performance data exists yet. This is placeholder logging
        only, feeding the future Analytics agent - it deliberately does NOT
        touch ctr/retention_30s/status (those stay untouched until
        record_usage() is later called with actual YouTube data). Calling
        record_usage() here instead would pollute the hook's real CTR/
        retention averages with fake zero-performance rows and could
        prematurely mark a hook 'declining'.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO hook_usage_log (hook_id, short_id, video_title, batch_id, viral_score)
                VALUES (?, ?, ?, ?, ?)
            ''', (hook_id, short_id, title, batch_id, viral_score))

            conn.commit()
            conn.close()

            logger.info(f"✓ Hook production logged [ID:{hook_id}] Batch:{batch_id} ViralScore:{viral_score:.1f}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to log hook production: {e}")
            return False

    def _compute_status(self, usage_count: int, avg_ctr: float, avg_retention: float, current_status: str) -> str:
        """
        Determine hook status from performance data.
        new -> testing (first use) -> proven_winner / declining (once enough data exists)
        Retired hooks stay retired (auto_retire is the only way in/out of that state).
        """
        if current_status == 'retired':
            return 'retired'

        if usage_count < 1:
            return 'new'

        if usage_count < self.MIN_USAGE_FOR_JUDGMENT:
            return 'testing'

        if avg_ctr >= self.PROVEN_WINNER_CTR and avg_retention >= self.PROVEN_WINNER_RETENTION:
            return 'proven_winner'

        if avg_ctr < self.DECLINING_CTR or avg_retention < self.DECLINING_RETENTION:
            return 'declining'

        return 'testing'

    def record_usage(self, hook_id: int, short_id: str, title: str, ctr: float, retention: float) -> bool:
        """Record hook performance data and update its status (new -> testing -> proven_winner/declining)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Log usage
            cursor.execute('''
                INSERT INTO hook_usage_log (hook_id, short_id, video_title, ctr, retention_30s)
                VALUES (?, ?, ?, ?, ?)
            ''', (hook_id, short_id, title, ctr, retention))

            # Update hook stats
            cursor.execute('''
                SELECT AVG(ctr), AVG(retention_30s), COUNT(*) FROM hook_usage_log WHERE hook_id = ?
            ''', (hook_id,))
            avg_ctr, avg_retention, count = cursor.fetchone()
            avg_ctr = avg_ctr or 0
            avg_retention = avg_retention or 0

            cursor.execute('SELECT status FROM hooks WHERE id = ?', (hook_id,))
            row = cursor.fetchone()
            current_status = row[0] if row else 'new'
            new_status = self._compute_status(count, avg_ctr, avg_retention, current_status)

            cursor.execute('''
                UPDATE hooks SET
                    usage_count = ?,
                    ctr = ?,
                    retention_30s = ?,
                    last_used = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (count, avg_ctr, avg_retention, datetime.now().date(), new_status, hook_id))

            conn.commit()
            conn.close()

            status_change = f" [{current_status} -> {new_status}]" if new_status != current_status else f" [{new_status}]"
            logger.info(f"✓ Hook usage recorded [ID:{hook_id}] CTR:{ctr:.1%} Retention:{retention:.1%}{status_change}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to record usage: {e}")
            return False

    def auto_retire(self, retention_threshold: float = 0.15) -> int:
        """
        Retire hooks that have enough usage data but are performing below the
        retention threshold. Retired hooks are excluded from get_top_performers()
        and ensure_diversity() going forward.

        Returns: number of hooks retired
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, text FROM hooks
                WHERE status != 'retired'
                  AND usage_count >= ?
                  AND retention_30s < ?
            ''', (self.MIN_USAGE_FOR_JUDGMENT, retention_threshold))

            to_retire = cursor.fetchall()

            if to_retire:
                cursor.execute('''
                    UPDATE hooks SET status = 'retired', updated_at = CURRENT_TIMESTAMP
                    WHERE status != 'retired' AND usage_count >= ? AND retention_30s < ?
                ''', (self.MIN_USAGE_FOR_JUDGMENT, retention_threshold))
                conn.commit()

            conn.close()

            logger.info(f"✓ Auto-retire complete: {len(to_retire)} hook(s) retired (retention < {retention_threshold:.1%})")
            for hook_id, text in to_retire:
                logger.info(f"  - Retired [ID:{hook_id}]: {text[:50]}...")

            return len(to_retire)
        except Exception as e:
            logger.error(f"❌ Failed to auto-retire hooks: {e}")
            return 0

    def get_top_performers(self, limit: int = 5) -> List[Dict]:
        """Get highest performing hooks (proven winners)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id, text, style, usage_count, ctr, retention_30s, status
                FROM hooks
                WHERE status IN ('testing', 'proven_winner')
                ORDER BY ctr DESC, retention_30s DESC
                LIMIT ?
            ''', (limit,))

            results = []
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'text': row[1],
                    'style': row[2],
                    'usage_count': row[3],
                    'ctr': row[4],
                    'retention': row[5],
                    'status': row[6]
                })

            conn.close()
            logger.info(f"✓ Retrieved {len(results)} top performing hooks")
            return results
        except Exception as e:
            logger.error(f"❌ Failed to get top performers: {e}")
            return []

    def prevent_repetition(self, days: int = 7) -> List[str]:
        """Get hooks already used in past N days (prevent repetition)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cutoff_date = (datetime.now() - timedelta(days=days)).date()
            cursor.execute('''
                SELECT DISTINCT text FROM hooks WHERE last_used > ?
            ''', (cutoff_date,))

            used_hooks = [row[0] for row in cursor.fetchall()]
            conn.close()

            logger.info(f"✓ Retrieved {len(used_hooks)} hooks from last {days} days (repetition prevention)")
            return used_hooks
        except Exception as e:
            logger.error(f"❌ Failed to check repetition: {e}")
            return []

    def ensure_diversity(self) -> Dict:
        """Ensure at least 3 active hook styles in rotation"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Count active hooks by style
            cursor.execute('''
                SELECT style, COUNT(*) as count
                FROM hooks
                WHERE status IN ('testing', 'proven_winner')
                GROUP BY style
            ''')

            style_counts = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            # Report diversity status
            active_styles = len(style_counts)
            status = "✓ PASS" if active_styles >= 3 else "❌ ALERT"

            logger.info(f"{status} Hook diversity: {active_styles} active styles (required: 3+)")
            logger.info(f"  Style breakdown: {style_counts}")

            return {
                'active_styles': active_styles,
                'style_breakdown': style_counts,
                'diversity_ok': active_styles >= 3
            }
        except Exception as e:
            logger.error(f"❌ Failed to check diversity: {e}")
            return {'active_styles': 0, 'diversity_ok': False}


class ChannelMemory:
    """
    Tracks every Short produced - performance, topics, patterns
    Enables series detection, prevents topic repetition, guides content strategy
    """

    def __init__(self, db_path: str = './data/chaos_merchant.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        logger.info(f"✓ ChannelMemory initialized: {self.db_path}")

    def _init_database(self):
        """Create channel memory table"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channel_shorts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    youtube_id TEXT UNIQUE,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    source_video TEXT,
                    script_summary TEXT,
                    hook_text TEXT,
                    thumbnail_style TEXT,
                    caption_style TEXT,
                    views INTEGER DEFAULT 0,
                    ctr REAL DEFAULT 0.0,
                    retention_30s REAL DEFAULT 0.0,
                    viral_score REAL DEFAULT 0.0,
                    publish_date DATE,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    short_id INTEGER NOT NULL,
                    views INTEGER,
                    ctr REAL,
                    retention_30s REAL,
                    viral_score REAL,
                    sampled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (short_id) REFERENCES channel_shorts(id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_checks (
                    short_id INTEGER NOT NULL,
                    mark TEXT NOT NULL,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(short_id, mark)
                )
            ''')

            # CREATE TABLE IF NOT EXISTS is a no-op on tables that already
            # exist, so format_used needs an explicit migration for any
            # pre-existing database created before the multi-format script
            # system - same pattern as HookLibrary's batch_id/viral_score
            # migration above.
            try:
                cursor.execute('ALTER TABLE channel_shorts ADD COLUMN format_used TEXT')
            except sqlite3.OperationalError:
                pass  # column already exists

            conn.commit()
            conn.close()
            logger.info("✓ Channel memory database schema initialized")
        except Exception as e:
            logger.error(f"❌ Database init failed: {e}")
            raise

    def add_short(self, title: str, topic: str, source_video: str, script_summary: str,
                  hook_text: str, thumbnail_style: str, caption_style: str,
                  format_used: str = None) -> bool:
        """Add newly published short to channel memory"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO channel_shorts
                (title, topic, source_video, script_summary, hook_text, thumbnail_style, caption_style, publish_date, format_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, topic, source_video, script_summary, hook_text, thumbnail_style, caption_style, datetime.now().date(), format_used))

            conn.commit()
            short_id = cursor.lastrowid
            conn.close()

            logger.info(f"✓ Short added to memory [ID:{short_id}] Topic:{topic} Format:{format_used}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to add short: {e}")
            return False

    def update_performance(self, youtube_id: str, views: int, ctr: float, retention: float) -> bool:
        """Update short performance from YouTube API"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Calculate viral score (views * CTR * retention as composite)
            viral_score = views * max(ctr, 0.01) * max(retention, 0.01)

            # Get short ID
            cursor.execute('SELECT id FROM channel_shorts WHERE youtube_id = ?', (youtube_id,))
            result = cursor.fetchone()
            if not result:
                logger.warning(f"⚠ Short not found: {youtube_id}")
                conn.close()
                return False

            short_id = result[0]

            # Log historical performance
            cursor.execute('''
                INSERT INTO performance_history (short_id, views, ctr, retention_30s, viral_score)
                VALUES (?, ?, ?, ?, ?)
            ''', (short_id, views, ctr, retention, viral_score))

            # Update current metrics
            cursor.execute('''
                UPDATE channel_shorts SET
                    views = ?,
                    ctr = ?,
                    retention_30s = ?,
                    viral_score = ?,
                    last_updated = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (views, ctr, retention, viral_score, short_id))

            conn.commit()
            conn.close()

            logger.info(f"✓ Performance updated [YouTube:{youtube_id}] Views:{views} CTR:{ctr:.1%} VScore:{viral_score:.0f}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update performance: {e}")
            return False

    def mark_published(self, title: str, youtube_id: str) -> Optional[int]:
        """
        Link a channel_shorts row (matched by title, most recent match if
        duplicates) to its real YouTube video ID once actually published,
        and reset publish_date to this moment - add_short() sets
        publish_date at pipeline/production time, which can differ from
        when a short is actually uploaded. Called by the Publisher module.

        Returns the short's internal id, or None if no title match found.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                SELECT id FROM channel_shorts WHERE title = ? ORDER BY created_at DESC LIMIT 1
            ''', (title,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                logger.warning(f"⚠ No channel_shorts entry found matching title: {title[:60]}")
                return None

            short_id = row[0]
            cursor.execute('''
                UPDATE channel_shorts SET youtube_id = ?, publish_date = ? WHERE id = ?
            ''', (youtube_id, datetime.now().date(), short_id))
            conn.commit()
            conn.close()

            logger.info(f"✓ Marked published [ID:{short_id}] YouTube:{youtube_id}")
            return short_id
        except sqlite3.IntegrityError:
            logger.warning(f"⚠ youtube_id already linked to another short: {youtube_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to mark published: {e}")
            return None

    def get_shorts_due_for_check(self, target_days_ago: int, tolerance_days: int = 1, mark: str = None) -> List[Dict]:
        """
        Shorts with a real youtube_id, published target_days_ago days ago
        (+/- tolerance_days), that have NOT already been checked at this
        mark (e.g. '48h', '7d') - so a daily job doesn't re-log the same
        short's same checkpoint every time it runs. Returns [] on a fresh
        channel with nothing published yet (no crash, no special-casing
        needed by callers) or once every due short has already been checked.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            target_date = (datetime.now() - timedelta(days=target_days_ago)).date()
            low = target_date - timedelta(days=tolerance_days)
            high = target_date + timedelta(days=tolerance_days)

            cursor.execute('''
                SELECT id, youtube_id, title, topic, publish_date, hook_text
                FROM channel_shorts
                WHERE youtube_id IS NOT NULL AND publish_date BETWEEN ? AND ?
            ''', (low, high))
            candidates = cursor.fetchall()

            due = []
            for row in candidates:
                short_id = row[0]
                if mark:
                    cursor.execute('''
                        SELECT 1 FROM performance_checks WHERE short_id = ? AND mark = ?
                    ''', (short_id, mark))
                    if cursor.fetchone():
                        continue  # already checked at this mark
                due.append({
                    'id': short_id, 'youtube_id': row[1], 'title': row[2],
                    'topic': row[3], 'publish_date': row[4], 'hook_text': row[5]
                })

            conn.close()
            return due
        except Exception as e:
            logger.error(f"❌ Failed to query shorts due for check: {e}")
            return []

    def mark_checked(self, short_id: int, mark: str) -> bool:
        """Record that a short has been checked at a given mark ('48h', '7d')."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS performance_checks (
                    short_id INTEGER NOT NULL,
                    mark TEXT NOT NULL,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(short_id, mark)
                )
            ''')
            cursor.execute('''
                INSERT OR IGNORE INTO performance_checks (short_id, mark) VALUES (?, ?)
            ''', (short_id, mark))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"❌ Failed to mark checked: {e}")
            return False

    def prevent_topic_repeat(self, days: int = 14) -> List[str]:
        """Get topics already covered in past N days"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cutoff_date = (datetime.now() - timedelta(days=days)).date()
            cursor.execute('''
                SELECT DISTINCT topic FROM channel_shorts WHERE publish_date > ?
            ''', (cutoff_date,))

            recent_topics = [row[0] for row in cursor.fetchall()]
            conn.close()

            logger.info(f"✓ Retrieved {len(recent_topics)} topics from last {days} days (repeat prevention)")
            return recent_topics
        except Exception as e:
            logger.error(f"❌ Failed to check topic repeat: {e}")
            return []

    def detect_series_opportunities(self, percentile: int = 90) -> List[Dict]:
        """Detect top 10% performing shorts that could become series (Part 2)"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Compute the percentile threshold in Python against the SAME filtered
            # set (ctr > 0) used below, rather than mixing a COUNT(*) over all rows
            # (including unmeasured ctr=0 shorts) with an OFFSET applied to a
            # filtered subset - that mismatch used to make the offset overshoot
            # and silently fall back to an arbitrary threshold.
            cursor.execute('SELECT ctr FROM channel_shorts WHERE ctr > 0 ORDER BY ctr ASC')
            measured_ctrs = [row[0] for row in cursor.fetchall()]

            if measured_ctrs:
                idx = min(int(len(measured_ctrs) * percentile / 100), len(measured_ctrs) - 1)
                threshold = measured_ctrs[idx]
            else:
                threshold = 0.05

            # Get top performers
            cursor.execute('''
                SELECT id, title, topic, ctr, viral_score, publish_date
                FROM channel_shorts
                WHERE ctr > ?
                ORDER BY ctr DESC
                LIMIT 10
            ''', (threshold,))

            series = []
            for row in cursor.fetchall():
                series.append({
                    'id': row[0],
                    'title': row[1],
                    'topic': row[2],
                    'ctr': row[3],
                    'viral_score': row[4],
                    'date': row[5],
                    'series_idea': f"Part 2: {row[2]}"
                })

            conn.close()

            logger.info(f"✓ Detected {len(series)} series opportunities (top {100-percentile}%)")
            for s in series:
                logger.info(f"  - {s['series_idea']} (CTR: {s['ctr']:.1%})")

            return series
        except Exception as e:
            logger.error(f"❌ Failed to detect series: {e}")
            return []

    def get_gap_report(self) -> Dict:
        """Generate content gap report - what topics are missing"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                SELECT topic, COUNT(*) as count
                FROM channel_shorts
                WHERE publish_date > date('now', '-30 days')
                GROUP BY topic
                ORDER BY count DESC
            ''')

            topic_coverage = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            logger.info(f"✓ Gap report generated")
            logger.info(f"  Topics covered (30-day window): {list(topic_coverage.keys())}")
            logger.info(f"  Coverage breakdown: {topic_coverage}")

            return {
                'topics_covered': list(topic_coverage.keys()),
                'coverage_breakdown': topic_coverage,
                'potential_gaps': []  # Would be populated by trend intelligence
            }
        except Exception as e:
            logger.error(f"❌ Failed to generate gap report: {e}")
            return {}

    def get_format_performance(self, min_samples: int = 1) -> Dict:
        """
        Aggregate performance (avg CTR/retention/viral_score) per script
        format, for the multi-format pivot's "track and report, don't
        auto-adjust" requirement - this is purely a reporting surface, no
        code currently reads this to change format-selection behavior.
        Shorts with no format_used recorded (pre-migration rows, or any
        row logged before the format pivot) are grouped under 'unknown'
        rather than silently excluded, so the report accounts for 100% of
        published shorts.

        Returns: {'by_format': {format: {count, avg_ctr, avg_retention,
        avg_viral_score}}, 'total_shorts': int}
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute('''
                SELECT COALESCE(format_used, 'unknown') as fmt,
                       COUNT(*), AVG(ctr), AVG(retention_30s), AVG(viral_score)
                FROM channel_shorts
                GROUP BY fmt
                ORDER BY AVG(ctr) DESC
            ''')

            rows = cursor.fetchall()
            conn.close()

            by_format = {}
            total = 0
            for fmt, count, avg_ctr, avg_retention, avg_viral in rows:
                total += count
                if count < min_samples:
                    continue
                by_format[fmt] = {
                    'count': count,
                    'avg_ctr': round(avg_ctr or 0, 4),
                    'avg_retention': round(avg_retention or 0, 4),
                    'avg_viral_score': round(avg_viral or 0, 2)
                }

            logger.info(f"✓ Format performance report generated ({total} shorts, {len(by_format)} format(s) with data)")
            for fmt, stats in by_format.items():
                logger.info(f"  - {fmt}: {stats['count']} shorts, CTR {stats['avg_ctr']:.1%}, retention {stats['avg_retention']:.1%}")

            return {'by_format': by_format, 'total_shorts': total}
        except Exception as e:
            logger.error(f"❌ Failed to generate format performance report: {e}")
            return {'by_format': {}, 'total_shorts': 0}


class SourceRegistry:
    """
    Tracks every clip the autonomous sourcing agent (agents/clip_sourcing.py)
    has ever seen, downloaded, or rejected - the mechanism that actually
    guarantees a clip is never downloaded twice. Checked BEFORE any yt-dlp
    probe/download call is made, not just checked against whatever
    currently happens to be sitting in the input folder (which wouldn't
    survive a process restart or a file later being moved/deleted
    downstream by the pipeline) - independent of agents/watcher.py's
    in-memory-only dedup, which has that exact gap.
    """

    def __init__(self, db_path: str = './data/chaos_merchant.db'):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        logger.info(f"✓ SourceRegistry initialized: {self.db_path}")

    def _init_database(self):
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sourced_clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_url TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    title TEXT,
                    popularity_signal REAL,
                    duration_seconds REAL,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    rejection_reason TEXT,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
            conn.close()
            logger.info("✓ Source registry database schema initialized")
        except Exception as e:
            logger.error(f"❌ SourceRegistry database init failed: {e}")
            raise

    def is_known(self, source_url: str) -> bool:
        """True if this URL has already been downloaded OR rejected - either way, it must
        never be probed or downloaded again."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM sourced_clips WHERE source_url = ?', (source_url,))
            found = cursor.fetchone() is not None
            conn.close()
            return found
        except Exception as e:
            logger.error(f"❌ SourceRegistry lookup failed: {e}")
            # Fail OPEN (treat as unknown) rather than closed: a lookup
            # error causing a duplicate download is wasteful but harmless,
            # while failing closed would silently block ALL sourcing
            # forever on a transient DB error - the worse outcome.
            return False

    def record_downloaded(self, source_url: str, platform: str, file_path: str,
                          popularity_signal: float, duration_seconds: float,
                          title: str = None) -> bool:
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sourced_clips
                (source_url, platform, title, popularity_signal, duration_seconds, file_path, status)
                VALUES (?, ?, ?, ?, ?, ?, 'downloaded')
            ''', (source_url, platform, title, popularity_signal, duration_seconds, file_path))
            conn.commit()
            conn.close()
            logger.info(f"✓ Recorded downloaded clip: {source_url}")
            return True
        except sqlite3.IntegrityError:
            logger.warning(f"⚠ Source URL already registered (race or duplicate call): {source_url}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to record downloaded clip: {e}")
            return False

    def record_rejected(self, source_url: str, platform: str, popularity_signal: float,
                        rejection_reason: str, title: str = None) -> bool:
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sourced_clips
                (source_url, platform, title, popularity_signal, status, rejection_reason)
                VALUES (?, ?, ?, ?, 'rejected', ?)
            ''', (source_url, platform, title, popularity_signal, rejection_reason))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"❌ Failed to record rejected clip: {e}")
            return False

    def get_recent(self, limit: int = 50) -> List[Dict]:
        """Most recently discovered clips (downloaded or rejected), for reporting/debugging."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute('''
                SELECT source_url, platform, title, popularity_signal, status, rejection_reason, discovered_at
                FROM sourced_clips ORDER BY discovered_at DESC LIMIT ?
            ''', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [
                {'source_url': r[0], 'platform': r[1], 'title': r[2], 'popularity_signal': r[3],
                 'status': r[4], 'rejection_reason': r[5], 'discovered_at': r[6]}
                for r in rows
            ]
        except Exception as e:
            logger.error(f"❌ Failed to fetch recent sourced clips: {e}")
            return []


def initialize_memory_system() -> Tuple[HookLibrary, ChannelMemory]:
    """Initialize both memory systems with backup"""
    logger.info("=" * 70)
    logger.info("🧠 INITIALIZING MEMORY SYSTEM")
    logger.info("=" * 70)

    db_path = './data/chaos_merchant.db'

    # Create backup before operations
    DatabaseBackup.backup_database(db_path)

    hook_lib = HookLibrary(db_path)
    channel_mem = ChannelMemory(db_path)

    # Verify diversity
    diversity = hook_lib.ensure_diversity()

    logger.info("=" * 70)
    logger.info(f"✓ Memory system ready")
    logger.info(f"  Hook Library: tracking script hooks")
    logger.info(f"  Channel Memory: tracking published shorts")
    logger.info(f"  Diversity status: {diversity['active_styles']} styles")
    logger.info("=" * 70)

    return hook_lib, channel_mem
