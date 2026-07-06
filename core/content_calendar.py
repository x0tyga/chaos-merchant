"""
Content Calendar - volume and format-mix knobs for the autonomous pipeline
Deliberately a knob file (config/content_calendar.json), not a new
automation engine: it doesn't decide WHAT to source or WHEN to run (that's
agents/clip_sourcing.py's scheduled jobs in main.py, and the daily trend
intelligence brief agents/trend_intelligence.py already produces) - it
only says how MUCH content per day and what MIX of script formats to aim
for. Both are read as soft guidance, not hard quotas:
- agents/clip_sourcing.py uses target_batches_per_day to derive a
  per-run download cap (on top of, never instead of, its own
  SOURCING_MAX_DOWNLOADS_PER_RUN rate-limiting safety ceiling).
- agents/format_selector.py's LLM tiebreak treats format_mix as guidance
  ("aim for roughly this distribution"), never overriding the
  deterministic Reaction gate or picking a format that doesn't actually
  fit a clip's content just to hit a ratio.
"""

import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

CONTENT_CALENDAR_PATH = Path('./config/content_calendar.json')

# Starting mix proposed during scoping: Hidden Details and News Recap as
# the default workhorses (information-dense, broadly applicable to any
# clip), Ranking/Comparison for batch-level structured content, Reaction
# capped low and reserved for standout clips (it's also hard-gated by
# viral_score in agents/format_selector.py regardless of this ratio).
DEFAULT_FORMAT_MIX = {
    'hidden_details': 0.35,
    'news_recap': 0.20,
    'ranking': 0.20,
    'comparison': 0.15,
    'reaction': 0.10,
}

DEFAULT_TARGET_BATCHES_PER_DAY = 1


def load_content_calendar() -> Dict:
    """
    Reads config/content_calendar.json, auto-creating it with sane
    defaults on first run (same pattern as config/gaming_calendar.json /
    config/competitors.json). Returns {'target_batches_per_day': int,
    'format_mix': {format: share}} - always both keys, even if the file
    on disk is missing one (falls back per-key, not all-or-nothing), so a
    partially-hand-edited file can't silently break format selection or
    volume guidance.
    """
    if not CONTENT_CALENDAR_PATH.exists():
        CONTENT_CALENDAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        default = {
            '_note': (
                'Volume and format-mix guidance for the autonomous pipeline - both '
                'are soft targets, not hard quotas. target_batches_per_day guides '
                'how many videos agents/clip_sourcing.py aims to download per day '
                '(it never exceeds SOURCING_MAX_DOWNLOADS_PER_RUN in .env, which is '
                'the hard rate-limiting ceiling). format_mix guides '
                'agents/format_selector.py\'s LLM tiebreak toward roughly this '
                'distribution across a batch - it never overrides the Reaction '
                'format\'s viral_score gate, and never forces a format that '
                'genuinely doesn\'t fit a clip\'s content. Edit this file directly '
                'to change either.'
            ),
            'target_batches_per_day': DEFAULT_TARGET_BATCHES_PER_DAY,
            'format_mix': DEFAULT_FORMAT_MIX,
        }
        with open(CONTENT_CALENDAR_PATH, 'w') as f:
            json.dump(default, f, indent=2)
        logger.info(f"✓ Created default content calendar config: {CONTENT_CALENDAR_PATH}")
        return {'target_batches_per_day': DEFAULT_TARGET_BATCHES_PER_DAY, 'format_mix': DEFAULT_FORMAT_MIX}

    try:
        with open(CONTENT_CALENDAR_PATH) as f:
            raw = json.load(f)
        return {
            'target_batches_per_day': raw.get('target_batches_per_day', DEFAULT_TARGET_BATCHES_PER_DAY),
            'format_mix': raw.get('format_mix', DEFAULT_FORMAT_MIX),
        }
    except Exception as e:
        logger.warning(f"⚠ Failed to load content calendar config, using defaults: {e}")
        return {'target_batches_per_day': DEFAULT_TARGET_BATCHES_PER_DAY, 'format_mix': DEFAULT_FORMAT_MIX}
