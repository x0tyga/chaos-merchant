"""
Cost Tracker - estimates real spend across every cost-bearing call in the
pipeline, fed by single-line calls at each call site. Powers the
dashboard's cost widget and core/posting_queue.py's cost-per-Short
attribution. Purely additive telemetry: neither logging function ever
raises, so a tracking failure can never break the agent that already got
its real result back.

Two cost KINDS are logged to the same cost_log.json, distinguished by a
'kind' field:
- 'anthropic_api' (log_anthropic_usage): real, metered Claude API spend -
  token-based, always nonzero for any real call.
- 'download_bandwidth' (log_download_usage): agents/clip_sourcing.py's
  yt-dlp downloads. yt-dlp itself has no metered API fee, but the bytes
  transferred are a real resource cost IF this is running on infrastructure
  that bills egress/bandwidth (a cloud VM) - it is NOT a real cost on the
  documented home-machine deployment (CLAUDE.md's Canva MCP section),
  which has no metered network. DOWNLOAD_COST_PER_GB_USD (.env, default
  0.0) controls this - left at 0.0 for the honest default, set to a real
  $/GB figure only if deployed somewhere that actually bills for it.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# $ per 1M tokens (input, output). Update as pricing changes; unknown models
# fall back to DEFAULT_PRICING rather than skipping the estimate entirely.
PRICING = {
    'claude-haiku-4-5-20251001': (1.00, 5.00),
    'claude-sonnet-5': (3.00, 15.00),
    'claude-opus-4-8': (5.00, 25.00),
}
DEFAULT_PRICING = (3.00, 15.00)

MAX_LOGGED_ENTRIES = 5000  # cap file growth; oldest entries drop first


def _log_path(data_dir: str = './data') -> Path:
    return Path(data_dir) / 'cost_log.json'


def _append_entry(entry: Dict, data_dir: str) -> None:
    path = _log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    entries = []
    if path.exists():
        try:
            with open(path, 'r') as f:
                entries = json.load(f)
        except Exception:
            entries = []

    entries.append(entry)
    entries = entries[-MAX_LOGGED_ENTRIES:]

    with open(path, 'w') as f:
        json.dump(entries, f, indent=2)


def log_anthropic_usage(agent: str, response, model: str = None, data_dir: str = './data') -> None:
    """Record token usage + estimated cost from a Messages API response."""
    try:
        usage = getattr(response, 'usage', None)
        if usage is None:
            return
        input_tokens = getattr(usage, 'input_tokens', 0) or 0
        output_tokens = getattr(usage, 'output_tokens', 0) or 0
        resolved_model = model or getattr(response, 'model', None) or 'unknown'
        in_price, out_price = PRICING.get(resolved_model, DEFAULT_PRICING)
        cost = (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

        _append_entry({
            'timestamp': datetime.now().isoformat(),
            'kind': 'anthropic_api',
            'agent': agent,
            'model': resolved_model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'estimated_cost_usd': round(cost, 6)
        }, data_dir)
    except Exception as e:
        logger.debug(f"Cost tracking skipped (non-fatal): {e}")


def log_download_usage(source_url: str, platform: str, bytes_downloaded: int, data_dir: str = './data') -> None:
    """
    Record a yt-dlp download's real bandwidth cost, tagged with the exact
    source_url so core.posting_queue can later attribute it to whichever
    batch that source video eventually produces (source downloads happen
    at sourcing time, well before the pipeline run that turns them into
    Shorts, so time-window correlation like get_cost_between() can't find
    them - they must be looked up by source_url instead, via
    get_cost_for_source_url()).
    """
    try:
        rate_per_gb = float(os.getenv('DOWNLOAD_COST_PER_GB_USD', '0.0'))
        gb = bytes_downloaded / (1024 ** 3)
        cost = gb * rate_per_gb

        _append_entry({
            'timestamp': datetime.now().isoformat(),
            'kind': 'download_bandwidth',
            'agent': 'clip_sourcing',
            'source_url': source_url,
            'platform': platform,
            'bytes_downloaded': bytes_downloaded,
            'estimated_cost_usd': round(cost, 6)
        }, data_dir)
    except Exception as e:
        logger.debug(f"Download cost tracking skipped (non-fatal): {e}")


def get_cost_for_source_url(source_url: Optional[str], data_dir: str = './data') -> float:
    """Sum of estimated_cost_usd for every logged entry tagged with this exact source_url (download cost lookup)."""
    if not source_url:
        return 0.0
    path = _log_path(data_dir)
    if not path.exists():
        return 0.0
    try:
        with open(path, 'r') as f:
            entries = json.load(f)
    except Exception as e:
        logger.warning(f"⚠ Could not read cost log: {e}")
        return 0.0
    return round(sum(e.get('estimated_cost_usd', 0.0) for e in entries if e.get('source_url') == source_url), 6)


def get_cost_between(start_iso: str, end_iso: str, data_dir: str = './data') -> float:
    """
    Sum of estimated_cost_usd for every logged call whose timestamp falls
    within [start_iso, end_iso]. Used by core/posting_queue.py to attribute
    a batch's real Anthropic API spend (script/SEO generation calls) across
    the shorts it produced - the content calendar's "cost per Short
    produced/posted" requirement. Returns 0.0 (never raises) if the log
    doesn't exist or is unreadable, same graceful-degradation contract as
    get_summary() below.
    """
    path = _log_path(data_dir)
    if not path.exists():
        return 0.0
    try:
        with open(path, 'r') as f:
            entries = json.load(f)
    except Exception as e:
        logger.warning(f"⚠ Could not read cost log: {e}")
        return 0.0

    try:
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
    except Exception:
        return 0.0

    total = 0.0
    for e in entries:
        try:
            ts = datetime.fromisoformat(e['timestamp'])
        except Exception:
            continue
        if start <= ts <= end:
            total += e.get('estimated_cost_usd', 0.0)
    return round(total, 6)


def get_summary(data_dir: str = './data', days: int = 30) -> Dict:
    """
    Aggregate cost by agent and by day for the last `days` days. Returns a
    clean zeroed summary if nothing has been logged yet - a fresh install
    checking the dashboard before any pipeline run should never error.
    """
    path = _log_path(data_dir)
    empty = {'total_cost_usd': 0.0, 'total_calls': 0, 'by_agent': {}, 'by_day': {}, 'recent': []}

    if not path.exists():
        return empty

    try:
        with open(path, 'r') as f:
            entries = json.load(f)
    except Exception as e:
        logger.warning(f"⚠ Could not read cost log: {e}")
        return empty

    cutoff = datetime.now() - timedelta(days=days)
    by_agent, by_day = {}, {}
    total_cost, total_calls = 0.0, 0

    for e in entries:
        try:
            ts = datetime.fromisoformat(e['timestamp'])
        except Exception:
            continue
        if ts < cutoff:
            continue
        cost = e.get('estimated_cost_usd', 0.0)
        total_cost += cost
        total_calls += 1
        by_agent[e['agent']] = by_agent.get(e['agent'], 0.0) + cost
        day = ts.strftime('%Y-%m-%d')
        by_day[day] = by_day.get(day, 0.0) + cost

    return {
        'total_cost_usd': round(total_cost, 4),
        'total_calls': total_calls,
        'by_agent': {k: round(v, 4) for k, v in by_agent.items()},
        'by_day': dict(sorted(by_day.items())),
        'recent': entries[-50:]
    }
