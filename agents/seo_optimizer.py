"""
SEO Optimizer Agent - Metadata generation for YouTube Shorts
Generates titles, descriptions, hashtags, keywords, and tags
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from anthropic import Anthropic

from core.cost_tracker import log_anthropic_usage

logger = logging.getLogger(__name__)

SEO_PROMPT_PATH = Path('./prompts/seo_optimization.txt')

DEFAULT_SEO_INSTRUCTIONS = """This channel covers chaotic, high-energy viral moments across ANY topic -
gaming, golf, sports, internet culture, unexpected/unhinged moments -
not just gaming. GTA6 is the current primary focus given its release
timing, but match the vernacular and hashtags to whatever this specific
clip's content actually is.

TITLE APPROACH (SPECIFIC & CONTENT-FOCUSED, 40-55 characters ideal):
- AVOID generic clickbait ("YOU WON'T BELIEVE THIS", "INSANE MOMENT")
- Name the actual subject (game/sport/topic) and the specific moment/detail
- Each title must be UNIQUE to this specific clip
- Example (good): "GOLFER SNAPS DRIVER AFTER TRIPLE BOGEY"
- Example (avoid): "INSANE MOMENT" (too generic, no topic signal)

Focus on:
- Vernacular that matches the clip's actual topic (gaming slang for
  gaming content, sports/golf terminology for sports content, etc.)
- CTR optimization (curiosity, urgency)
- Trending keyword integration
- Hook-first messaging
- Hashtags: mix specific (#GolfFail, #GameGlitch) with broad (#Viral,
  #Shorts) matched to the clip's actual topic"""


def _load_seo_instructions() -> str:
    """
    Reads tone/style/focus instructions from prompts/seo_optimization.txt
    if present - this is what the dashboard's Settings page edits to tune
    generated metadata without touching code. Falls back to
    DEFAULT_SEO_INSTRUCTIONS if the file is missing or empty. The required
    JSON output schema is always defined in code, never read from this
    file, so an edit here can change tone/vocabulary/focus but can never
    break JSON parsing downstream.
    """
    try:
        if SEO_PROMPT_PATH.exists():
            content = SEO_PROMPT_PATH.read_text().strip()
            if content:
                return content
    except Exception as e:
        logger.warning(f"⚠ Could not read SEO prompt template: {e}")
    return DEFAULT_SEO_INSTRUCTIONS


class SEOOptimizer:
    """Generates SEO-optimized metadata for YouTube Shorts"""

    def __init__(self):
        self.client = Anthropic()

    def generate_metadata(self, clip_data, script_data, trending_topics=None):
        """
        Generate comprehensive SEO metadata
        
        Args:
            clip_data: Clip intelligence manifest
            script_data: Generated script with hook and content
            trending_topics: Current trending topics
        
        Returns:
            dict: Complete metadata package
        """
        logger.info("🔍 Generating SEO metadata...")
        
        # Build context for Claude
        script = script_data.get('script', {})
        hook = script.get('hook', '')
        main_content = script.get('main_content', '')
        cta = script.get('cta', '')
        
        clip_summary = f"Hook: {hook}. Content: {main_content}"
        instructions = _load_seo_instructions()

        prompt = f"""Generate YouTube Shorts SEO metadata.

Video Content:
{clip_summary}

Trending Topics: {json.dumps(trending_topics or [], indent=2)}

Generate a JSON object with:
- titles: list of 5 CTR-optimized titles (8-60 chars each)
- description: Short YouTube description (under 150 chars)
- hashtags: list of 10-15 relevant hashtags
- keywords: list of 10 search keywords
- tags: list of 5-8 video tags

{instructions}

Output ONLY valid JSON."""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            log_anthropic_usage('seo_optimizer', response)

            response_text = response.content[0].text

            # Extract JSON
            try:
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    metadata = json.loads(json_str)
                else:
                    raise ValueError("No JSON found")
            except (json.JSONDecodeError, ValueError):
                logger.warning("Failed to parse metadata JSON, using fallback")
                metadata = self._generate_fallback_metadata(clip_summary)
            
            logger.info(f"✓ Metadata generated ({len(metadata.get('titles', []))} titles)")
            
            return {
                'status': 'success',
                'metadata': metadata,
                'model': 'claude-haiku-4-5-20251001'
            }
            
        except Exception as e:
            logger.error(f"❌ Metadata generation failed: {e}")
            raise

    def _generate_fallback_metadata(self, clip_summary):
        """Generate fallback metadata if API fails"""
        return {
            'titles': [
                'INSANE VIRAL MOMENT',
                'YOU WON\'T BELIEVE THIS',
                'WAIT FOR IT...',
                'THIS MOMENT IS CRAZY',
                'MUST WATCH CHAOS'
            ],
            'description': 'Check out this incredible chaotic moment! Subscribe for more crazy clips.',
            'hashtags': [
                '#Viral', '#Chaos', '#Shorts', '#YouTube',
                '#CrazyMoment', '#UnbelievableMoment'
            ],
            'keywords': [
                'viral moment', 'chaotic moment', 'crazy clip',
                'unbelievable moment', 'viral shorts', 'must watch'
            ],
            'tags': [
                'Viral', 'Chaos', 'Funny', 'Crazy', 'Moments'
            ]
        }

    def select_best_title(self, metadata):
        """
        Select best title from candidates
        Scores by length and keyword distribution
        
        Args:
            metadata: Metadata dict with titles list
        
        Returns:
            str: Best title
        """
        titles = metadata.get('titles', [])
        if not titles:
            return "Amazing Chaotic Moment"
        
        # Prefer titles that are 40-55 characters (YouTube sweet spot)
        optimal_titles = [t for t in titles if 40 <= len(t) <= 55]
        if optimal_titles:
            return optimal_titles[0]
        
        return titles[0]


def find_duplicate_seo(seo_results: List[Dict]) -> List[Tuple[int, int, str]]:
    """
    Pairwise-compares successful SEO results within a batch for exact
    duplicate descriptions or hashtag sets. Per-clip SEO only means
    anything if each clip's metadata is genuinely distinct - two different
    clips in the same batch ending up with an identical description or
    identical hashtag set means the model effectively ignored per-clip
    context, which is a real generation bug, not a stylistic quirk to
    shrug off.

    Only compares clips with status == 'success' (a failed/error result
    has no metadata to compare and isn't a "duplicate" in any meaningful
    sense). Hashtag comparison is order-independent (a set, not a list) -
    the same 12 hashtags in a different order is still a duplicate.

    Returns a list of (i, j, field) tuples for every colliding pair
    (i < j, both indices into seo_results), where field is 'description'
    or 'hashtags'. Empty list means no duplicates found.
    """
    pairs = []
    successful = [i for i, r in enumerate(seo_results) if r.get('status') == 'success']

    for a in range(len(successful)):
        i = successful[a]
        meta_i = seo_results[i].get('metadata', {})
        desc_i = (meta_i.get('description') or '').strip()
        hashtags_i = frozenset(meta_i.get('hashtags', []) or [])

        for b in range(a + 1, len(successful)):
            j = successful[b]
            meta_j = seo_results[j].get('metadata', {})
            desc_j = (meta_j.get('description') or '').strip()
            hashtags_j = frozenset(meta_j.get('hashtags', []) or [])

            if desc_i and desc_i == desc_j:
                pairs.append((i, j, 'description'))
            elif hashtags_i and hashtags_i == hashtags_j:
                pairs.append((i, j, 'hashtags'))

    return pairs


def optimize_seo(clip_data, script_data, trending_topics=None):
    """
    Main function to generate SEO metadata
    
    Args:
        clip_data: Clip intelligence manifest
        script_data: Generated script
        trending_topics: Trending topics
    
    Returns:
        dict: Complete SEO metadata
    """
    logger.info("🎯 Starting SEO optimization...")
    
    optimizer = SEOOptimizer()
    result = optimizer.generate_metadata(clip_data, script_data, trending_topics)
    
    if result['status'] != 'success':
        raise RuntimeError("SEO optimization failed")
    
    metadata = result['metadata']
    
    # Select best title
    best_title = optimizer.select_best_title(metadata)
    
    return {
        'status': 'success',
        'metadata': metadata,
        'best_title': best_title,
        'timestamp': datetime.now().isoformat()
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    # Test data
    test_clip = {'duration': 30, 'clips': []}
    test_script = {
        'script': {
            'hook': 'THIS GLITCH IS INSANE',
            'main_content': 'Check out this unbelievable gaming moment',
            'cta': 'Subscribe for more!'
        }
    }
    
    print("Testing SEO Optimizer...")
    result = optimize_seo(test_clip, test_script, ['gaming', 'viral'])
    print(json.dumps(result, indent=2))
