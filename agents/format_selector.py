"""
Format Selector Agent - picks which script format a clip should use
Hybrid selection: a deterministic gate gates Reaction/Commentary to only
genuinely remarkable clips; everything else is a cheap Claude Haiku call
choosing among the remaining eligible formats, using the clip's content
description and trending context.

This exists because the channel is pivoting away from emotion-based
reaction scripts (AI voices can't convincingly fake human excitement, and
reaction content needs a human personality AI can't replicate) toward
information-based formats where the value is what's said, not how - see
agents/script_voiceover.py's VALID_FORMATS and prompts/formats/*.txt for
the format templates this selects between.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from anthropic import Anthropic

from core.cost_tracker import log_anthropic_usage
from agents.script_voiceover import VALID_FORMATS

logger = logging.getLogger(__name__)

# Reaction is a hard-gated format, not just an LLM preference: a clip must
# clear this viral_score (0-10 scale, same scale clip_intelligence.py
# already scores every segment on) before Reaction is even offered as a
# candidate to the model. This is enforced in code specifically so the LLM
# can't casually reach for "genuinely remarkable" language on a mundane
# clip just because it's an available option.
DEFAULT_REACTION_MIN_VIRAL_SCORE = 8.0

# Fallback format if the LLM call fails or returns something unusable -
# the most information-dense, broadly-applicable format, never Reaction
# (which must never be picked as a fallback given its gate exists for a
# reason - a failed selector call is not "genuinely remarkable").
FALLBACK_FORMAT = 'hidden_details'

# The format selector's quality depends entirely on the accuracy of the
# clip content description (agents/script_voiceover.py's
# ClipContentAnalyzer) - a vague or wrong description makes every format
# decision downstream wrong regardless of how good the selection logic
# itself is. Below this self-reported confidence (0.0-1.0, from the
# model's own rating of how clearly it could make out what's happening),
# skip the LLM tiebreak entirely rather than let it reason from an
# unreliable description - FALLBACK_FORMAT is always safe since it works
# from whatever metadata is available without needing to be confident
# about specific on-screen content.
DEFAULT_MIN_DESCRIPTION_CONFIDENCE = 0.5


class FormatSelector:
    """Hybrid format selector: deterministic Reaction gate + LLM tiebreak among the rest."""

    def __init__(self):
        self.client = Anthropic()
        try:
            self.reaction_min_viral_score = float(
                os.getenv('REACTION_MIN_VIRAL_SCORE', DEFAULT_REACTION_MIN_VIRAL_SCORE)
            )
        except (TypeError, ValueError):
            logger.warning(
                f"⚠ Invalid REACTION_MIN_VIRAL_SCORE value {os.getenv('REACTION_MIN_VIRAL_SCORE')!r} "
                f"- using default {DEFAULT_REACTION_MIN_VIRAL_SCORE}"
            )
            self.reaction_min_viral_score = DEFAULT_REACTION_MIN_VIRAL_SCORE

        try:
            self.min_description_confidence = float(
                os.getenv('FORMAT_SELECTOR_MIN_DESCRIPTION_CONFIDENCE', DEFAULT_MIN_DESCRIPTION_CONFIDENCE)
            )
        except (TypeError, ValueError):
            logger.warning(
                f"⚠ Invalid FORMAT_SELECTOR_MIN_DESCRIPTION_CONFIDENCE value "
                f"{os.getenv('FORMAT_SELECTOR_MIN_DESCRIPTION_CONFIDENCE')!r} - using default "
                f"{DEFAULT_MIN_DESCRIPTION_CONFIDENCE}"
            )
            self.min_description_confidence = DEFAULT_MIN_DESCRIPTION_CONFIDENCE

    def _eligible_formats(self, clip_data: Dict) -> List[str]:
        """Deterministic step: every format is eligible except Reaction, which requires
        clearing the viral_score gate - the only hardcoded rule for launch."""
        viral_score = clip_data.get('viral_score', clip_data.get('engagement_score', 0) * 10)
        eligible = [f for f in VALID_FORMATS if f != 'reaction']
        if viral_score >= self.reaction_min_viral_score:
            eligible.append('reaction')
        else:
            logger.info(
                f"ℹ Reaction format not eligible for this clip (viral_score {viral_score:.2f} "
                f"< threshold {self.reaction_min_viral_score}) - excluded from candidates"
            )
        return eligible

    def select_format(self, clip_data: Dict, clip_description: Optional[str] = None,
                      clip_description_confidence: Optional[float] = None,
                      trending_topics: Optional[List] = None,
                      format_mix: Optional[Dict[str, float]] = None) -> Tuple[str, str]:
        """
        Selects a format for one clip.

        Args:
            clip_data: A single clip dict from clip_manifest['clips']
                (engagement_score, viral_score, duration, etc.)
            clip_description: Factual content description from
                ClipContentAnalyzer, if available (same ground truth the
                script generator itself uses).
            clip_description_confidence: The model's own 0.0-1.0 confidence
                in clip_description (from get_clip_description()). None
                means "no description was attempted at all" (handled the
                same as before - the LLM judges from metadata only), which
                is deliberately distinct from "a description was attempted
                but rated low-confidence" (handled below).
            trending_topics: Trending topics for context.
            format_mix: Optional {format: target_share} guidance (e.g. from
                a future content calendar) - passed to the model as soft
                guidance, never a hard quota; the Reaction gate above always
                takes precedence over any requested mix.

        Returns:
            (format_type, rationale) - format_type is always one of
            VALID_FORMATS (never invented), rationale is a short
            human-readable explanation for logging/debugging.
        """
        if clip_description_confidence is not None and clip_description_confidence < self.min_description_confidence:
            logger.info(
                f"ℹ Clip content description confidence ({clip_description_confidence:.2f}) is below "
                f"threshold ({self.min_description_confidence}) - defaulting to '{FALLBACK_FORMAT}' "
                f"instead of risking a format decision based on an unreliable description"
            )
            return FALLBACK_FORMAT, f"description confidence {clip_description_confidence:.2f} below threshold {self.min_description_confidence}"

        eligible = self._eligible_formats(clip_data)

        if len(eligible) == 1:
            # Only Reaction was excluded and nothing else could be - can't
            # actually happen since VALID_FORMATS always has 4 non-Reaction
            # entries, but keep this as a defensive short-circuit rather
            # than spending an LLM call when there's only one real choice.
            return eligible[0], "only one format was eligible"

        try:
            format_type, rationale = self._select_via_llm(
                clip_data, clip_description, trending_topics, format_mix, eligible
            )
            if format_type not in eligible:
                logger.warning(
                    f"⚠ Format selector LLM returned '{format_type}', which isn't in this "
                    f"clip's eligible set {eligible} - falling back to '{FALLBACK_FORMAT}'"
                )
                return FALLBACK_FORMAT, "LLM returned an ineligible format, used fallback"
            return format_type, rationale
        except Exception as e:
            logger.warning(f"⚠ Format selector LLM call failed ({e}) - falling back to '{FALLBACK_FORMAT}'")
            return FALLBACK_FORMAT, f"LLM call failed ({e}), used fallback"

    def _select_via_llm(self, clip_data, clip_description, trending_topics,
                        format_mix, eligible: List[str]) -> Tuple[str, str]:
        content_section = (
            f"What is actually happening in this clip: {clip_description}"
            if clip_description else
            "No visual content description is available - judge only from the metadata below."
        )

        mix_section = (
            f"\nTarget format mix for this batch (soft guidance, not a hard quota - "
            f"pick whatever genuinely fits this clip best): {json.dumps(format_mix)}"
            if format_mix else ""
        )

        format_descriptions = {
            'hidden_details': "Hidden Details - point out a specific detail most viewers would miss and explain why it matters.",
            'news_recap': "News Recap - factual summary of confirmed information (leaks, announcements, updates).",
            'ranking': "Ranking/Countdown - places this clip within a ranked list of moments in this batch.",
            'comparison': "Comparison - factual side-by-side differences (old vs new, rumored vs confirmed).",
            'reaction': "Reaction & Commentary - reserved for genuinely remarkable clips; a knowledgeable friend explaining why, never hype.",
        }
        candidates_text = "\n".join(f"- {f}: {format_descriptions[f]}" for f in eligible)

        prompt = f"""Choose the single best script format for this specific clip from the
candidates below. Pick based on what the clip's content actually supports -
don't force a format that doesn't fit just to hit a mix target.

{content_section}

Clip data:
- Duration: {clip_data.get('duration', 0):.1f} seconds
- Engagement score: {round(clip_data.get('engagement_score', 0), 2)} (0-1 scale)
- Viral score: {round(clip_data.get('viral_score', 0), 2)} (0-10 scale)

Trending topics: {json.dumps(trending_topics or [], indent=2)}
{mix_section}

Candidate formats:
{candidates_text}

Output ONLY a JSON object: {{"format": "<one of the candidate format keys above>", "rationale": "<one sentence why>"}}"""

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        log_anthropic_usage('format_selector', response)

        text = response.content[0].text
        start_idx = text.find('{')
        end_idx = text.rfind('}') + 1
        if start_idx < 0 or end_idx <= start_idx:
            raise ValueError("No JSON found in format selector response")

        result = json.loads(text[start_idx:end_idx])
        format_type = result.get('format', '')
        rationale = result.get('rationale', '')
        return format_type, rationale


def select_format_for_clip(clip_data: Dict, clip_description: Optional[str] = None,
                           clip_description_confidence: Optional[float] = None,
                           trending_topics: Optional[List] = None,
                           format_mix: Optional[Dict[str, float]] = None) -> Tuple[str, str]:
    """Module-level entry point, matching the other agents' function-per-concern convention
    (optimize_seo(), generate_voiceover_for_clip(), etc.)."""
    selector = FormatSelector()
    format_type, rationale = selector.select_format(
        clip_data, clip_description, clip_description_confidence, trending_topics, format_mix
    )
    logger.info(f"✓ Format selected: {format_type} ({rationale})")
    return format_type, rationale
