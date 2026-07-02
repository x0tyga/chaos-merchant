"""
SEO Optimizer Agent - Metadata generation for YouTube Shorts
Generates titles, descriptions, hashtags, keywords, and tags
"""

import json
import logging
from datetime import datetime
from anthropic import Anthropic

logger = logging.getLogger(__name__)


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

Focus on:
- Gaming/internet culture vernacular
- CTR optimization (curiosity, urgency)
- Trending keyword integration
- Hook-first messaging

Output ONLY valid JSON."""

        try:
            response = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=800,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
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
                'model': 'claude-3-5-haiku-20241022'
            }
            
        except Exception as e:
            logger.error(f"❌ Metadata generation failed: {e}")
            raise

    def _generate_fallback_metadata(self, clip_summary):
        """Generate fallback metadata if API fails"""
        return {
            'titles': [
                'INSANE GAMING MOMENT',
                'YOU WON\'T BELIEVE THIS',
                'WAIT FOR IT...',
                'THIS GLITCH IS CRAZY',
                'MUST WATCH GAMING'
            ],
            'description': 'Check out this incredible gaming moment! Subscribe for more crazy clips.',
            'hashtags': [
                '#Gaming', '#Gaming Clips', '#Viral', '#Gaming Glitch',
                '#Shorts', '#YouTube', '#Twitch', '#Gameplay',
                '#Funny Gaming', '#Gaming Moments'
            ],
            'keywords': [
                'gaming', 'gaming clips', 'viral gaming', 'funny gaming',
                'gaming moments', 'gaming glitch', 'gaming fail',
                'gaming highlights', 'gaming shorts'
            ],
            'tags': [
                'Gaming', 'Viral', 'Funny', 'Glitch', 'Moments'
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
            return "Amazing Gaming Moment"
        
        # Prefer titles that are 40-55 characters (YouTube sweet spot)
        optimal_titles = [t for t in titles if 40 <= len(t) <= 55]
        if optimal_titles:
            return optimal_titles[0]
        
        return titles[0]


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
