"""
Dashboard data access layer - every function here reads real state off
disk/SQLite (job/quota trackers, output batch folders, the hook/channel
memory DB, analytics CSV, trend/research JSON dumps, prompt files) and
returns a clean empty/default value if that state doesn't exist yet
(fresh install, before the first pipeline run) rather than raising -
routes in app.py never need their own "nothing to show yet" branches.

Expects to be run with the project root as the working directory (same
convention as main.py, setup.sh, and every agent's default `./data`,
`./output`, `./prompts`, `./config` paths) - run the dashboard with
`python dashboard/app.py` from the repository root.
"""

import csv
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv('DATA_DIR', './data'))
OUTPUT_DIR = Path(os.getenv('OUTPUT_DIR', './output'))
INPUT_DIR = Path(os.getenv('INPUT_DIR', './input'))
PROMPTS_DIR = Path('./prompts')
ANALYTICS_DIR = Path('./analytics')
LOG_DIR = Path(os.getenv('LOG_DIR', './logs'))
DB_PATH = DATA_DIR / 'chaos_merchant.db'
ENV_PATH = Path('./.env')

VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm')


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"⚠ Could not read {path}: {e}")
        return default


# ---------------------------------------------------------------------------
# Home - pipeline status/queue
# ---------------------------------------------------------------------------

def get_input_queue() -> List[str]:
    """Videos sitting in INPUT_DIR not yet consumed by the watcher."""
    if not INPUT_DIR.exists():
        return []
    return sorted(
        f.name for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )


def get_checkpoints() -> List[Dict]:
    """In-progress/crashed pipeline runs with a recoverable checkpoint."""
    checkpoint_dir = DATA_DIR / 'checkpoints'
    if not checkpoint_dir.exists():
        return []
    results = []
    for f in sorted(checkpoint_dir.glob('*.json')):
        data = _read_json(f, {})
        results.append({
            'video': data.get('video_path', f.stem),
            'step': data.get('step_name', 'unknown'),
            'file': f.name
        })
    return results


def get_job_status() -> Dict:
    """Scheduled job run status from data/job_tracker.json."""
    data = _read_json(DATA_DIR / 'job_tracker.json', {'date': None, 'jobs': {}})
    return data.get('jobs', {})


def get_quota_status() -> Dict:
    data = _read_json(DATA_DIR / 'quota_tracker.json', {})
    daily_quota = 10000
    used = data.get('quota_used', 0)
    return {
        'quota_used': used,
        'quota_remaining': data.get('quota_remaining', daily_quota),
        'quota_percent_used': round((used / daily_quota) * 100, 1) if daily_quota else 0
    }


def get_cost_summary(days: int = 7) -> Dict:
    from core.cost_tracker import get_summary
    return get_summary(data_dir=str(DATA_DIR), days=days)


# ---------------------------------------------------------------------------
# Output - batches + viral scores
# ---------------------------------------------------------------------------

def get_batches() -> List[Dict]:
    """Every packaged batch folder, newest first, with its BATCH_MANIFEST.json."""
    if not OUTPUT_DIR.exists():
        return []
    batches = []
    for d in sorted(OUTPUT_DIR.glob('batch_*'), reverse=True):
        manifest = _read_json(d / 'manifests' / 'BATCH_MANIFEST.json', {})
        if not manifest:
            continue
        batches.append({
            'batch_id': manifest.get('batch_id', d.name),
            'folder': d.name,
            'created_at': manifest.get('created_at'),
            'status': manifest.get('status', 'unknown'),
            'qc_routing': manifest.get('qc_routing', 'unknown'),
            'video_count': manifest.get('video_count', 0),
            'ready_for_upload': manifest.get('ready_for_upload', False)
        })
    return batches


def get_batch_detail(folder_name: str) -> Optional[Dict]:
    """One batch's manifest + upload metadata + hook-logged viral scores."""
    d = OUTPUT_DIR / folder_name
    if not d.exists() or not d.is_dir():
        return None

    manifest = _read_json(d / 'manifests' / 'BATCH_MANIFEST.json', {})
    batch_id = manifest.get('batch_id', folder_name)

    shorts = []
    metadata_dir = d / 'upload_metadata'
    if metadata_dir.exists():
        for f in sorted(metadata_dir.glob('*.json')):
            shorts.append(_read_json(f, {}))

    viral_scores = _get_hook_viral_scores_for_batch(batch_id)

    return {
        'batch_id': batch_id,
        'folder': folder_name,
        'manifest': manifest,
        'shorts': shorts,
        'viral_scores': viral_scores
    }


def _get_hook_viral_scores_for_batch(batch_id: str) -> List[Dict]:
    """
    Pre-publish viral scores logged by Pipeline._log_hook_usage() at
    production time (hook_usage_log.batch_id/viral_score) - real data
    engagement/audio scoring produced, not a placeholder. Real YouTube
    performance (ctr/retention) only exists after Analytics & Feedback's
    48h/7d checks run, so those columns are commonly still 0/NULL here on
    a freshly produced batch - that's expected, not a bug.
    """
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute('''
            SELECT short_id, viral_score, ctr, retention_30s
            FROM hook_usage_log WHERE batch_id = ? ORDER BY short_id
        ''', (batch_id,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {'short_id': r[0], 'viral_score': r[1], 'ctr': r[2], 'retention_30s': r[3]}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"⚠ Could not read hook viral scores for batch {batch_id}: {e}")
        return []


# ---------------------------------------------------------------------------
# Analytics - views/CTR/retention over time, top hooks, recent shorts
# ---------------------------------------------------------------------------

def get_performance_log(limit: int = 200) -> List[Dict]:
    """Raw rows from analytics/performance_log.csv (written by analytics_feedback.py)."""
    path = ANALYTICS_DIR / 'performance_log.csv'
    if not path.exists():
        return []
    try:
        with open(path, 'r', newline='') as f:
            rows = list(csv.DictReader(f))
        return rows[-limit:]
    except Exception as e:
        logger.warning(f"⚠ Could not read performance log: {e}")
        return []


def get_top_hooks(limit: int = 10) -> List[Dict]:
    if not DB_PATH.exists():
        return []
    from core.memory import HookLibrary
    return HookLibrary(str(DB_PATH)).get_top_performers(limit=limit)


def get_recent_shorts(limit: int = 20) -> List[Dict]:
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute('''
            SELECT title, topic, views, ctr, retention_30s, viral_score, publish_date, youtube_id
            FROM channel_shorts ORDER BY created_at DESC LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {'title': r[0], 'topic': r[1], 'views': r[2], 'ctr': r[3], 'retention_30s': r[4],
             'viral_score': r[5], 'publish_date': r[6], 'youtube_id': r[7]}
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"⚠ Could not read recent shorts: {e}")
        return []


# ---------------------------------------------------------------------------
# Trends - today's brief, competitor alerts, ideas backlog
# ---------------------------------------------------------------------------

def get_trend_brief() -> Optional[Dict]:
    return _read_json(DATA_DIR / 'trend_intelligence_latest.json', None)


def get_competitor_alerts(limit: int = 20) -> List[Dict]:
    alerts = _read_json(DATA_DIR / 'competitor_alerts_latest.json', [])
    return alerts[-limit:] if isinstance(alerts, list) else []


def get_ideas_backlog(limit: int = 50) -> List[Dict]:
    ideas = _read_json(DATA_DIR / 'ideas_backlog.json', [])
    return list(reversed(ideas))[:limit] if isinstance(ideas, list) else []


def get_competitors() -> List[Dict]:
    from agents.competitor_monitor import CompetitorMonitor
    return CompetitorMonitor().load_competitors()


def add_competitor(handle_or_url: str, category: str = 'gaming') -> Optional[Dict]:
    from agents.competitor_monitor import CompetitorMonitor
    return CompetitorMonitor().add_competitor(handle_or_url, category)


# ---------------------------------------------------------------------------
# Research - thumbnail research, comment insights, content gaps
# ---------------------------------------------------------------------------

def get_latest_thumbnail_research() -> Optional[Dict]:
    research_dir = DATA_DIR / 'thumbnail_research'
    if not research_dir.exists():
        return None
    files = sorted(research_dir.glob('research_*.json'), reverse=True)
    return _read_json(files[0], None) if files else None


def get_latest_comment_insights() -> Optional[Dict]:
    insights_dir = DATA_DIR / 'comment_insights'
    if not insights_dir.exists():
        return None
    files = sorted(insights_dir.glob('insights_*.json'), reverse=True)
    return _read_json(files[0], None) if files else None


def get_content_gap_report() -> Dict:
    if not DB_PATH.exists():
        return {'topics_covered': [], 'coverage_breakdown': {}, 'potential_gaps': []}
    from core.memory import ChannelMemory
    return ChannelMemory(str(DB_PATH)).get_gap_report()


# ---------------------------------------------------------------------------
# Settings - .env and prompt files, editable in-browser
# ---------------------------------------------------------------------------

def read_env_file() -> str:
    if ENV_PATH.exists():
        return ENV_PATH.read_text()
    example = Path('./.env.example')
    if example.exists():
        return example.read_text()
    return ''


def write_env_file(content: str) -> None:
    """Backs up the previous .env (timestamped) before overwriting - this
    file holds live API keys, a bad paste shouldn't be unrecoverable."""
    if ENV_PATH.exists():
        backup_dir = DATA_DIR / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f".env_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
        backup_path.write_text(ENV_PATH.read_text())
    ENV_PATH.write_text(content)


def _safe_prompt_path(name: str) -> Optional[Path]:
    """
    Only allow a bare filename (no path separators/traversal) ending in
    .txt, resolved inside prompts/ - the settings page hands this whatever
    a browser form submits, so it must not be able to read/write outside
    that one directory no matter what's in the request.
    """
    if not name or '/' in name or '\\' in name or '..' in name or not name.endswith('.txt'):
        return None
    return PROMPTS_DIR / name


def list_prompt_files() -> List[Dict]:
    if not PROMPTS_DIR.exists():
        return []
    results = []
    for f in sorted(PROMPTS_DIR.glob('*.txt')):
        stat = f.stat()
        results.append({
            'name': f.name,
            'size_bytes': stat.st_size,
            'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    return results


def read_prompt_file(name: str) -> Optional[str]:
    path = _safe_prompt_path(name)
    if not path or not path.exists():
        return None
    return path.read_text()


def write_prompt_file(name: str, content: str) -> bool:
    path = _safe_prompt_path(name)
    if not path:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


# ---------------------------------------------------------------------------
# Logs - tail the pipeline's rotating log file
# ---------------------------------------------------------------------------

def tail_log(n: int = 300) -> List[str]:
    log_path = LOG_DIR / 'chaos_merchant.log'
    if not log_path.exists():
        return []
    try:
        with open(log_path, 'r', errors='replace') as f:
            lines = f.readlines()
        return [line.rstrip('\n') for line in lines[-n:]]
    except Exception as e:
        logger.warning(f"⚠ Could not read log file: {e}")
        return []
