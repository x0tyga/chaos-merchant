"""
Thumbnail Generation Agent - Creates YouTube Shorts thumbnails via Canva MCP
Generates eye-catching, gaming-focused thumbnails that drive clicks
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import base64

from anthropic import Anthropic

logger = logging.getLogger(__name__)


class ThumbnailBriefGenerator:
    """Generates creative briefs and Canva prompts for thumbnails"""

    def __init__(self):
        self.client = Anthropic()

    def generate_brief_and_prompt(self, clip_data: Dict, seo_data: Dict, script: str) -> Dict:
        """
        Generate thumbnail brief and Canva-specific prompt
        
        Args:
            clip_data: Clip metadata (engagement_score, audio_features, etc.)
            seo_data: SEO metadata (best_title, keywords, hashtags)
            script: Full voiceover script
        
        Returns:
            dict: {brief, canva_prompt, fallback_strategy}
        """
        logger.info("📸 Generating thumbnail brief...")

        engagement_score = clip_data.get('engagement_score', 0.5)
        title = seo_data.get('best_title', 'Gaming Moment')
        keywords = seo_data.get('metadata', {}).get('keywords', [])

        prompt = f"""Generate a YouTube Shorts thumbnail brief for a gaming video.

Video Title: {title}
Keywords: {', '.join(keywords[:3])}
Content Energy: {'HIGH' if engagement_score > 0.7 else 'MEDIUM' if engagement_score > 0.4 else 'LOW'}
Script Snippet: {script[:100]}...

Create a JSON response with:
1. "brief": 2-3 sentence visual description (what the thumbnail should show)
2. "canva_prompt": Detailed prompt for Canva AI to generate the design (include colors, layout, text, style)
3. "fallback": Brief text-only description if Canva generation fails

Requirements:
- High contrast, eye-catching colors (gaming audience)
- Large readable text (gaming title/hook)
- Bright colors: neon, yellow, red, cyan preferred
- Gaming aesthetic: bold fonts, action-oriented
- Must grab attention in YouTube thumbnail grid
- Include emojis or gaming visual elements in description

Return ONLY valid JSON, no markdown."""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text

            try:
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    brief_data = json.loads(json_str)
                else:
                    raise ValueError("No JSON found")
            except (json.JSONDecodeError, ValueError):
                brief_data = {
                    'brief': 'Gaming moment with high energy and excitement',
                    'canva_prompt': f'YouTube thumbnail for "{title}" - bold neon colors, large text, gaming aesthetic, high contrast, action-focused, use bright yellow/cyan/red colors',
                    'fallback': title
                }

            logger.info(f"✓ Generated brief: {brief_data['brief'][:50]}...")
            return {
                'status': 'success',
                'brief': brief_data.get('brief', ''),
                'canva_prompt': brief_data.get('canva_prompt', ''),
                'fallback_text': brief_data.get('fallback', title),
                'title': title
            }

        except Exception as e:
            logger.error(f"❌ Brief generation failed: {e}")
            return {
                'status': 'error',
                'brief': 'Gaming thumbnail',
                'canva_prompt': f'YouTube gaming thumbnail for "{title}" - high contrast, bold colors, text overlay',
                'fallback_text': title,
                'title': title,
                'error': str(e)
            }


class CanvaThumbnailGenerator:
    """Creates thumbnails via Canva MCP"""

    def __init__(self):
        self.canva_available = True

    def generate_via_canva(self, canva_prompt: str, title: str, output_path: str) -> Optional[str]:
        """
        Generate thumbnail via Canva MCP generate-design tool
        
        Note: This requires Canva MCP to be available in the session.
        If unavailable, returns None (fallback to brief-only mode).
        """
        try:
            logger.info("🎨 Calling Canva MCP to generate thumbnail...")

            # Import here to handle cases where MCP tools aren't available
            try:
                from mcp_client import canva_generate_design
            except ImportError:
                logger.warning("⚠ Canva MCP not available in this session")
                return None

            # Call Canva MCP generate-design for youtube_thumbnail
            try:
                result = canva_generate_design(
                    query=canva_prompt,
                    design_type='youtube_thumbnail',
                    user_intent='Generate YouTube Shorts thumbnail for gaming video'
                )

                if result and 'design_url' in result:
                    logger.info(f"✓ Canva thumbnail generated: {result['design_url']}")
                    return result['design_url']
                else:
                    logger.warning("⚠ Canva returned no design URL")
                    return None

            except Exception as mcp_error:
                logger.warning(f"⚠ Canva MCP call failed: {mcp_error}")
                return None

        except Exception as e:
            logger.warning(f"⚠ Canva thumbnail generation failed: {e}")
            return None


class ThumbnailGenerator:
    """Main orchestrator for thumbnail generation"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.brief_generator = ThumbnailBriefGenerator()
        self.canva_generator = CanvaThumbnailGenerator()

    def generate_thumbnail(self, clip_data: Dict, seo_data: Dict, script: str,
                          short_number: int) -> Dict:
        """
        Generate thumbnail for one short video
        
        Returns:
            dict: {status, image_url or brief, thumbnail_type}
        """
        try:
            logger.info(f"📸 Generating thumbnail for short #{short_number}...")

            brief_result = self.brief_generator.generate_brief_and_prompt(clip_data, seo_data, script)

            if brief_result['status'] == 'error':
                logger.warning(f"⚠ Brief generation failed, using fallback")

            canva_result = self.canva_generator.generate_via_canva(
                brief_result['canva_prompt'],
                brief_result['title'],
                str(self.output_dir / f"thumbnail_{short_number:03d}.png")
            )

            if canva_result:
                logger.info(f"✓ Thumbnail generated via Canva: {canva_result}")
                return {
                    'status': 'success',
                    'thumbnail_type': 'canva_generated',
                    'image_url': canva_result,
                    'title': brief_result['title'],
                    'brief': brief_result['brief']
                }
            else:
                logger.info(f"ℹ Canva unavailable, returning brief for manual creation")
                return {
                    'status': 'brief_only',
                    'thumbnail_type': 'brief_only',
                    'brief': brief_result['brief'],
                    'canva_prompt': brief_result['canva_prompt'],
                    'fallback_text': brief_result['fallback_text'],
                    'title': brief_result['title'],
                    'instructions': 'Manual thumbnail creation: Use brief and Canva prompt to create thumbnail on home machine'
                }

        except Exception as e:
            logger.error(f"❌ Thumbnail generation failed: {e}")
            return {
                'status': 'error',
                'thumbnail_type': 'error',
                'error': str(e),
                'fallback_text': seo_data.get('best_title', 'Gaming Moment')
            }

    def generate_all_thumbnails(self, clip_manifest: Dict, seo_manifest: Dict,
                                voiceover_results: list) -> Dict:
        """Generate thumbnails for all 7 shorts, each using that specific
        clip's own SEO data and script (seo_manifest['per_clip'][i] /
        voiceover_results[i]) instead of one shared set reused for all 7."""
        logger.info("🎬 Starting thumbnail generation for all shorts...")

        results = []
        top_clip_indices = clip_manifest.get('top_clip_indices', [])
        clips = clip_manifest.get('clips', [])
        per_clip_seo = (seo_manifest or {}).get('per_clip', [])

        if not top_clip_indices or not clips:
            logger.error("❌ No clips found")
            return {
                'status': 'error',
                'error': 'No clips in manifest',
                'thumbnails': []
            }

        for i, clip_idx in enumerate(top_clip_indices[:7]):
            if clip_idx < len(clips):
                clip_data = clips[clip_idx]
                # Fall back to the shared top-level seo_manifest fields if
                # per_clip data isn't available for this index (e.g. that
                # clip's SEO generation failed) - still real data, just not
                # this specific clip's own.
                seo_data = per_clip_seo[i] if i < len(per_clip_seo) and per_clip_seo[i].get('status') == 'success' else (seo_manifest or {})
                voiceover_for_clip = voiceover_results[i] if i < len(voiceover_results) else {}
                script = voiceover_for_clip.get('script', {}).get('full_script', '')

                result = self.generate_thumbnail(clip_data, seo_data, script, i)
                results.append(result)

        generated_count = len([r for r in results if r['status'] == 'success'])
        brief_only_count = len([r for r in results if r['status'] == 'brief_only'])

        logger.info(f"✅ Thumbnail generation complete: {generated_count} generated, {brief_only_count} brief-only")

        return {
            'status': 'partial' if brief_only_count > 0 else 'success',
            'generated_count': generated_count,
            'brief_only_count': brief_only_count,
            'thumbnails': results,
            'metadata': {
                'total': len(results),
                'canva_generated': generated_count,
                'manual_required': brief_only_count
            },
            'timestamp': datetime.now().isoformat()
        }


def generate_thumbnails(clip_manifest: Dict, seo_manifest: Dict, voiceover_results: list,
                       output_dir: str = './output') -> Dict:
    """
    Main entry point: Generate thumbnails for all shorts

    Phase 2 approach:
    - If Canva MCP available in session: Generate thumbnail images directly
    - If Canva MCP unavailable: Return detailed brief + Canva prompt for manual creation

    Args:
        voiceover_results: list of per-clip voiceover results (one per
            short, same order as clip_manifest['top_clip_indices']), each
            shaped like generate_voiceover_for_clip()'s return value

    Returns fallback strategy so users can create on home machine if needed
    """
    logger.info("=" * 60)
    logger.info("📸 THUMBNAIL GENERATION AGENT - CANVA MCP EDITION")
    logger.info("=" * 60)

    try:
        generator = ThumbnailGenerator(output_dir)
        result = generator.generate_all_thumbnails(clip_manifest, seo_manifest, voiceover_results)

        logger.info("\n" + "=" * 60)
        logger.info(f"THUMBNAIL GENERATION COMPLETE")
        logger.info(f"Generated: {result['generated_count']} | Manual (brief-only): {result['brief_only_count']}")
        logger.info("=" * 60)

        return result

    except Exception as e:
        logger.error(f"❌ Thumbnail generation failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'thumbnails': [],
            'timestamp': datetime.now().isoformat()
        }
