"""
Thumbnail Research Agent - Step 14
Runs weekly (Sunday). Scrapes trending gaming Shorts thumbnails via
yt-dlp, analyzes color palette/composition/contrast with Pillow,
cross-references against own CTR data (analytics/performance_log.csv,
written by agents/analytics_feedback.py), and updates
prompts/thumbnail_prompt.txt when a clear pattern emerges - git-committed
for rollback, same pattern as Analytics & Feedback's prompt updates.

Degrades gracefully with zero own CTR data yet: trending-thumbnail
scraping and analysis (which doesn't depend on the user's own channel at
all) still runs normally; the cross-reference step against own
performance simply reports "insufficient own data" instead of crashing
on an empty comparison.
"""

import csv
import json
import logging
import os
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not available - thumbnail research will be unavailable (pip install yt-dlp)")

try:
    from PIL import Image
    import io
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("Pillow not available - thumbnail image analysis will be unavailable (pip install Pillow)")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from anthropic import Anthropic

from core.cost_tracker import log_anthropic_usage

TRENDING_SEARCH_QUERY = os.getenv('THUMBNAIL_RESEARCH_QUERY', 'gaming shorts')
TRENDING_SAMPLE_SIZE = 50
MIN_OWN_DATA_POINTS = 5  # minimum own CTR samples before cross-referencing is meaningful


class TrendingThumbnailFetcher:
    """Pulls trending Shorts metadata (including thumbnail URLs) via yt-dlp search - no API key needed."""

    def fetch_trending(self, query: str = TRENDING_SEARCH_QUERY, limit: int = TRENDING_SAMPLE_SIZE) -> List[Dict]:
        if not YTDLP_AVAILABLE:
            logger.warning("⚠ yt-dlp not installed, skipping trending thumbnail fetch")
            return []

        ydl_opts = {
            'quiet': True,
            'skip_download': True,
            'extract_flat': 'in_playlist',
        }
        search_target = f"ytsearch{limit}:{query}"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search_target, download=False)
        except Exception as e:
            logger.warning(f"⚠ yt-dlp trending search failed: {e}")
            return []

        entries = (info or {}).get('entries', []) or []
        results = []
        for entry in entries:
            if not entry:
                continue
            thumbnail_url = entry.get('thumbnail')
            if not thumbnail_url and entry.get('thumbnails'):
                thumbnail_url = entry['thumbnails'][-1].get('url')
            results.append({
                'video_id': entry.get('id'),
                'title': entry.get('title', ''),
                'channel': entry.get('channel') or entry.get('uploader', ''),
                'view_count': entry.get('view_count'),
                'thumbnail_url': thumbnail_url
            })

        logger.info(f"✓ Fetched {len(results)} trending video entries for '{query}'")
        return results


class ThumbnailImageAnalyzer:
    """Downloads and analyzes thumbnail images: dominant colors, brightness/contrast."""

    def analyze(self, thumbnail_url: str) -> Optional[Dict]:
        if not PIL_AVAILABLE or not REQUESTS_AVAILABLE or not thumbnail_url:
            return None

        try:
            response = requests.get(thumbnail_url, timeout=10)
            response.raise_for_status()
            img = Image.open(io.BytesIO(response.content)).convert('RGB')
            img_small = img.resize((80, 80))  # downsample for fast palette analysis

            pixels = list(img_small.getdata())
            # Quantize to reduce near-duplicate colors before counting
            quantized = [(r // 32 * 32, g // 32 * 32, b // 32 * 32) for r, g, b in pixels]
            color_counts = Counter(quantized)
            dominant_colors = [c for c, _ in color_counts.most_common(3)]

            brightness_values = [(r * 0.299 + g * 0.587 + b * 0.114) for r, g, b in pixels]
            avg_brightness = sum(brightness_values) / len(brightness_values)
            contrast = (max(brightness_values) - min(brightness_values)) if brightness_values else 0

            return {
                'dominant_colors': [f'#{c[0]:02x}{c[1]:02x}{c[2]:02x}' for c in dominant_colors],
                'avg_brightness': round(avg_brightness, 1),
                'contrast_range': round(contrast, 1),
                'width': img.width,
                'height': img.height
            }
        except Exception as e:
            logger.warning(f"⚠ Could not analyze thumbnail {thumbnail_url}: {e}")
            return None


class PerformanceCrossReference:
    """Cross-references trending thumbnail patterns against own CTR data."""

    def __init__(self, performance_log_path: str = './analytics/performance_log.csv'):
        self.performance_log_path = Path(performance_log_path)

    def get_own_ctr_summary(self) -> Optional[Dict]:
        """
        Average CTR from our own logged performance data. Returns None if
        there's insufficient own data yet (fresh channel or too few
        logged checks) - callers skip the cross-reference step entirely
        rather than comparing trending patterns against a meaningless
        1-or-0-sample average.
        """
        if not self.performance_log_path.exists():
            return None

        try:
            with open(self.performance_log_path, 'r', newline='') as f:
                rows = list(csv.DictReader(f))
        except Exception as e:
            logger.warning(f"⚠ Could not read performance log: {e}")
            return None

        ctrs = []
        for row in rows:
            try:
                ctr = float(row.get('thumbnail_ctr') or 0)
                if ctr > 0:
                    ctrs.append(ctr)
            except (ValueError, TypeError):
                continue

        if len(ctrs) < MIN_OWN_DATA_POINTS:
            logger.info(
                f"ℹ Only {len(ctrs)} own CTR data point(s) logged (need {MIN_OWN_DATA_POINTS}+) - "
                f"skipping cross-reference against trending patterns"
            )
            return None

        return {'avg_ctr': round(sum(ctrs) / len(ctrs), 4), 'sample_size': len(ctrs)}


class ThumbnailPatternAnalyzer:
    """Uses Claude to synthesize a research summary from raw trending-thumbnail analyses."""

    def __init__(self):
        self.client = Anthropic()

    def synthesize(self, analyzed_thumbnails: List[Dict], own_ctr_summary: Optional[Dict]) -> Dict:
        if not analyzed_thumbnails:
            return {'status': 'no_data', 'patterns': [], 'recommended_prompt_additions': []}

        summary_data = [
            {
                'title': t.get('title', '')[:80],
                'dominant_colors': t.get('image_analysis', {}).get('dominant_colors'),
                'avg_brightness': t.get('image_analysis', {}).get('avg_brightness'),
                'contrast_range': t.get('image_analysis', {}).get('contrast_range')
            }
            for t in analyzed_thumbnails if t.get('image_analysis')
        ]

        if not summary_data:
            return {'status': 'no_data', 'patterns': [], 'recommended_prompt_additions': []}

        own_context = (
            f"Our own channel's average thumbnail CTR is {own_ctr_summary['avg_ctr']:.1%} "
            f"(from {own_ctr_summary['sample_size']} samples)."
            if own_ctr_summary else
            "We don't have enough of our own CTR data yet to compare against - "
            "treat this as general trending-pattern research only."
        )

        prompt = f"""Analyze these {len(summary_data)} trending gaming Shorts thumbnails' color/
composition data and identify patterns.

{own_context}

Thumbnail data:
{json.dumps(summary_data, indent=2)[:6000]}

Generate a JSON object with:
- patterns: list of 3-5 specific visual patterns observed (color choices, brightness, contrast trends)
- recommended_prompt_additions: list of 2-4 specific, actionable additions to a thumbnail generation prompt template based on these patterns

Output ONLY valid JSON."""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )
            log_anthropic_usage('thumbnail_research', response)
            text = response.content[0].text
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            if start_idx >= 0 and end_idx > start_idx:
                result = json.loads(text[start_idx:end_idx])
                result['status'] = 'success'
                return result
            raise ValueError("No JSON found")
        except Exception as e:
            logger.warning(f"⚠ Pattern synthesis failed: {e}")
            return {'status': 'error', 'patterns': [], 'recommended_prompt_additions': []}


class ThumbnailPromptUpdater:
    """Writes recommended additions to prompts/thumbnail_prompt.txt and commits them."""

    def __init__(self, prompt_path: str = './prompts/thumbnail_prompt.txt', repo_dir: str = '.'):
        self.prompt_path = Path(prompt_path)
        self.repo_dir = repo_dir

    def apply_additions(self, additions: List[str]) -> bool:
        if not additions:
            return False

        try:
            self.prompt_path.parent.mkdir(parents=True, exist_ok=True)
            is_new = not self.prompt_path.exists()

            with open(self.prompt_path, 'a') as f:
                if is_new:
                    f.write(
                        "# Thumbnail generation guidance\n"
                        "# Auto-maintained by agents/thumbnail_research.py from weekly trending-thumbnail research.\n"
                        "# agents/thumbnail.py reads this file (if present) as additional style guidance.\n\n"
                    )
                f.write(f"\n# Added {datetime.now().strftime('%Y-%m-%d')} from trending thumbnail research:\n")
                for addition in additions:
                    f.write(f"- {addition}\n")

            subprocess.run(['git', 'add', str(self.prompt_path)], cwd=self.repo_dir, check=True, capture_output=True)
            subprocess.run(
                ['git', 'commit', '-m',
                 f"Auto-update thumbnail_prompt.txt from weekly trending research\n\n"
                 f"Auto-committed by Thumbnail Research agent for rollback capability."],
                cwd=self.repo_dir, check=True, capture_output=True
            )
            logger.info(f"✓ Thumbnail prompt updated and committed: {self.prompt_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"⚠ Thumbnail prompt git commit failed (maybe nothing new to commit): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Thumbnail prompt update failed: {e}")
            return False


class ThumbnailResearchAgent:
    """Main orchestrator - weekly trending thumbnail research pass."""

    def __init__(self, data_dir: str = './data'):
        self.data_dir = data_dir
        self.fetcher = TrendingThumbnailFetcher()
        self.image_analyzer = ThumbnailImageAnalyzer()
        self.cross_ref = PerformanceCrossReference()
        self.pattern_analyzer = ThumbnailPatternAnalyzer()
        self.prompt_updater = ThumbnailPromptUpdater()

    def run_weekly_research(self) -> Dict:
        logger.info("=" * 70)
        logger.info("🖼️  THUMBNAIL RESEARCH - Weekly Analysis")
        logger.info("=" * 70)

        trending = self.fetcher.fetch_trending()
        if not trending:
            logger.info("ℹ No trending thumbnails fetched this run (yt-dlp unavailable or search returned nothing)")
            return {'status': 'no_data', 'thumbnails_analyzed': 0, 'timestamp': datetime.now().isoformat()}

        analyzed = []
        for entry in trending:
            image_analysis = self.image_analyzer.analyze(entry.get('thumbnail_url'))
            if image_analysis:
                analyzed.append({**entry, 'image_analysis': image_analysis})

        if not analyzed:
            logger.info("ℹ Fetched trending video metadata but could not analyze any thumbnail images "
                        "(Pillow/requests unavailable, or all downloads failed)")
            return {'status': 'partial', 'thumbnails_analyzed': 0, 'trending_fetched': len(trending),
                     'timestamp': datetime.now().isoformat()}

        own_ctr_summary = self.cross_ref.get_own_ctr_summary()
        synthesis = self.pattern_analyzer.synthesize(analyzed, own_ctr_summary)

        prompt_updated = False
        if synthesis.get('recommended_prompt_additions'):
            prompt_updated = self.prompt_updater.apply_additions(synthesis['recommended_prompt_additions'])

        report = {
            'status': 'success',
            'thumbnails_analyzed': len(analyzed),
            'trending_fetched': len(trending),
            'own_data_available': own_ctr_summary is not None,
            'own_ctr_summary': own_ctr_summary,
            'patterns': synthesis.get('patterns', []),
            'recommended_prompt_additions': synthesis.get('recommended_prompt_additions', []),
            'prompt_updated': prompt_updated,
            'timestamp': datetime.now().isoformat()
        }

        self._save_dated_report(report)

        logger.info(
            f"\n✓ Thumbnail research complete: {report['thumbnails_analyzed']}/{report['trending_fetched']} "
            f"thumbnails analyzed, own data available: {report['own_data_available']}, "
            f"prompt updated: {prompt_updated}"
        )
        logger.info("=" * 70)

        return report

    def _save_dated_report(self, report: Dict):
        research_dir = Path(self.data_dir) / 'thumbnail_research'
        research_dir.mkdir(parents=True, exist_ok=True)
        report_path = research_dir / f"research_{datetime.now().strftime('%Y%m%d')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"✓ Dated research report saved: {report_path}")


def run_thumbnail_research() -> Dict:
    """Main entry point, scheduled weekly Sunday 10am."""
    try:
        agent = ThumbnailResearchAgent()
        return agent.run_weekly_research()
    except Exception as e:
        logger.error(f"❌ Thumbnail research failed: {e}")
        return {'status': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_thumbnail_research()
    print(json.dumps(result, indent=2, default=str))
