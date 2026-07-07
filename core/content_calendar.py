"""
Content Calendar - volume and format-mix knobs for the autonomous pipeline
Deliberately a knob file (config/content_calendar.json), not a new
automation engine: it doesn't decide WHAT to source or WHEN to run (that's
agents/clip_sourcing.py's scheduled jobs in main.py, and the daily trend
intelligence brief agents/trend_intelligence.py already produces) - it
only says how MUCH content per day, how MANY of those get POSTED per day,
and what MIX of script formats to aim for. All are read as soft guidance,
not hard quotas:
- agents/clip_sourcing.py uses target_batches_per_day to derive a
  per-run download cap (on top of, never instead of, its own
  SOURCING_MAX_DOWNLOADS_PER_RUN rate-limiting safety ceiling).
- core/posting_queue.py uses posts_per_day to space out autonomous
  YouTube publishing (never posts an entire batch at once).
- agents/format_selector.py's LLM tiebreak treats get_effective_format_mix()
  as guidance ("aim for roughly this distribution"), never overriding the
  deterministic Reaction gate or picking a format that doesn't actually
  fit a clip's content just to hit a ratio.
"""

import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

CONTENT_CALENDAR_PATH = Path('./config/content_calendar.json')

# Approved starting mix (2026-07-07 pivot): Hidden Details and News Recap
# as the default workhorses (information-dense, broadly applicable to any
# clip), Ranking for batch-level structured content, Comparison used more
# sparingly, Reaction set to 0 at launch - it remains selectable ONLY via
# agents/format_selector.py's hard viral_score gate (REACTION_MIN_VIRAL_SCORE),
# never via this ratio, so a 0% guidance weight here does not disable it,
# it just means the LLM tiebreak never reaches for it on its own.
DEFAULT_FORMAT_MIX = {
    'hidden_details': 0.35,
    'news_recap': 0.30,
    'ranking': 0.20,
    'comparison': 0.10,
    'reaction': 0.0,
}

DEFAULT_TARGET_BATCHES_PER_DAY = 1

# How many finished Shorts get PUBLISHED to YouTube per day once
# AUTO_POST_YOUTUBE=true - see core/posting_queue.py. Distinct from
# target_batches_per_day above: that's SOURCING volume (how much gets
# produced), this is PUBLISHING pace (how much gets posted, spaced out
# across each day's optimal posting times rather than all at once).
DEFAULT_POSTS_PER_DAY = 3

# Rolling window (days) used by get_effective_format_mix() to correct next
# selections back toward the configured ratio if actual output has skewed.
REBALANCE_WINDOW_DAYS = 7
# Below this many produced shorts in the rolling window, there isn't enough
# signal to safely rebalance - the configured/default ratio is used as-is.
REBALANCE_MIN_SAMPLES = 5


def load_content_calendar() -> Dict:
    """
    Reads config/content_calendar.json, auto-creating it with sane
    defaults on first run (same pattern as config/gaming_calendar.json /
    config/competitors.json). Returns {'target_batches_per_day': int,
    'posts_per_day': int, 'format_mix': {format: share}} - always all
    three keys, even if the file on disk is missing one (falls back
    per-key, not all-or-nothing), so a partially-hand-edited file can't
    silently break format selection, sourcing volume, or posting pace.
    """
    if not CONTENT_CALENDAR_PATH.exists():
        CONTENT_CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        default = {
            '_note': (
                'Volume, posting-pace, and format-mix guidance for the autonomous '
                'pipeline - all three are soft targets, not hard quotas. '
                'target_batches_per_day guides how many videos agents/clip_sourcing.py '
                'aims to download per day (it never exceeds SOURCING_MAX_DOWNLOADS_PER_RUN '
                'in .env, which is the hard rate-limiting ceiling). posts_per_day guides '
                'how many finished Shorts core/posting_queue.py publishes to YouTube per '
                'day once AUTO_POST_YOUTUBE=true, spaced across that day\'s optimal '
                'posting times rather than fired all at once. format_mix guides '
                'agents/format_selector.py\'s LLM tiebreak toward roughly this '
                'distribution across a batch (auto-corrected over a rolling 7-day '
                'window by get_effective_format_mix() below) - it never overrides the '
                'Reaction format\'s viral_score gate, and never forces a format that '
                'genuinely doesn\'t fit a clip\'s content. Edit this file directly '
                'to change any of these.'
            ),
            'target_batches_per_day': DEFAULT_TARGET_BATCHES_PER_DAY,
            'posts_per_day': DEFAULT_POSTS_PER_DAY,
            'format_mix': DEFAULT_FORMAT_MIX,
        }
        with open(CONTENT_CALENDAR_PATH, 'w') as f:
            json.dump(default, f, indent=2)
        logger.info(f"✓ Created default content calendar config: {CONTENT_CALENDAR_PATH}")
        return {
            'target_batches_per_day': DEFAULT_TARGET_BATCHES_PER_DAY,
            'posts_per_day': DEFAULT_POSTS_PER_DAY,
            'format_mix': DEFAULT_FORMAT_MIX,
        }

    try:
        with open(CONTENT_CALENDAR_PATH) as f:
            raw = json.load(f)
        return {
            'target_batches_per_day': raw.get('target_batches_per_day', DEFAULT_TARGET_BATCHES_PER_DAY),
            'posts_per_day': raw.get('posts_per_day', DEFAULT_POSTS_PER_DAY),
            'format_mix': raw.get('format_mix', DEFAULT_FORMAT_MIX),
        }
    except Exception as e:
        logger.warning(f"⚠ Failed to load content calendar config, using defaults: {e}")
        return {
            'target_batches_per_day': DEFAULT_TARGET_BATCHES_PER_DAY,
            'posts_per_day': DEFAULT_POSTS_PER_DAY,
            'format_mix': DEFAULT_FORMAT_MIX,
        }


def get_effective_format_mix(data_dir: str = './data') -> Dict:
    """
    The configured format_mix, nudged by how the last REBALANCE_WINDOW_DAYS
    of actually-produced shorts have skewed - the "rebalances the next day"
    requirement. If a format has been over-produced relative to its target
    share, its effective weight is reduced (and vice versa for
    under-produced formats), so agents/format_selector.py's LLM tiebreak
    naturally corrects course over time instead of drifting further off
    the configured ratio. Never touches the Reaction viral_score gate -
    that stays purely deterministic regardless of this.

    Falls back to the raw configured mix (no correction) if there isn't
    enough production history yet (REBALANCE_MIN_SAMPLES) or if the
    channel_shorts lookup fails for any reason - a rebalance signal is a
    refinement, never a requirement for format selection to function.
    """
    base_mix = load_content_calendar()['format_mix']

    try:
        from core.memory import ChannelMemory
        db_path = str(Path(data_dir) / 'chaos_merchant.db')
        counts = ChannelMemory(db_path).get_format_counts(days=REBALANCE_WINDOW_DAYS)
    except Exception as e:
        logger.warning(f"⚠ Could not load format counts for rebalancing, using configured mix as-is: {e}")
        return base_mix

    total = sum(counts.values())
    if total < REBALANCE_MIN_SAMPLES:
        return base_mix

    actual_ratio = {fmt: counts.get(fmt, 0) / total for fmt in base_mix}
    # Push each format's weight in the opposite direction of its skew:
    # over-represented (actual > target) formats shrink, under-represented
    # ones grow. Clamped at 0 so a heavily-overused format can't go negative.
    corrected = {
        fmt: max(0.0, base_mix[fmt] + (base_mix[fmt] - actual_ratio.get(fmt, 0.0)))
        for fmt in base_mix
    }
    total_corrected = sum(corrected.values())
    if total_corrected <= 0:
        return base_mix

    effective = {fmt: round(v / total_corrected, 4) for fmt, v in corrected.items()}
    logger.info(f"✓ Effective format mix (rebalanced over last {REBALANCE_WINDOW_DAYS}d, {total} samples): {effective}")
    return effective
