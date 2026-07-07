"""
Cost Tracker - estimates Anthropic API spend from response.usage, fed by a
single-line call at every agent's Claude call site. Powers the dashboard's
cost widget. Purely additive telemetry: log_anthropic_usage() never raises,
so a tracking failure can never break the agent that already got its real
response back.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

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

        path = _log_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        entries = []
        if path.exists():
            try:
                with open(path, 'r') as f:
                    entries = json.load(f)
            except Exception:
                entries = []

        entries.append({
            'timestamp': datetime.now().isoformat(),
            'agent': agent,
            'model': resolved_model,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'estimated_cost_usd': round(cost, 6)
        })
        entries = entries[-MAX_LOGGED_ENTRIES:]

        with open(path, 'w') as f:
            json.dump(entries, f, indent=2)
    except Exception as e:
        logger.debug(f"Cost tracking skipped (non-fatal): {e}")


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
