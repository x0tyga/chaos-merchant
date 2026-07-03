"""
Comment Mining Agent - Step 11
Runs weekly (Sunday). Mines comments from own recent shorts and top
competitor videos for repeated questions, excitement signals, confusion
points, controversy opportunities, and audience language patterns -
feeding both a content ideas backlog and a vocabulary reference the
script generator can read from.

Degrades gracefully when the channel has zero published shorts yet: own-
comment mining finds nothing (no youtube_id-linked shorts) and is
skipped cleanly, while competitor comment mining - which doesn't depend
on the user's own channel having any data at all - still runs normally
as long as competitors are configured in config/competitors.json.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from anthropic import Anthropic

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLEAPICLIENT_AVAILABLE = True
except ImportError:
    GOOGLEAPICLIENT_AVAILABLE = False
    logger.warning("googleapiclient not available - comment mining will be unavailable (pip install google-api-python-client)")

from core.memory import ChannelMemory


class CommentFetcher:
    """Public Data API v3 - top comments for a video. No OAuth needed."""

    def __init__(self):
        self.api_key = os.getenv('YOUTUBE_API_KEY', '')
        self.youtube = None
        if not GOOGLEAPICLIENT_AVAILABLE:
            return
        if self.api_key:
            try:
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)
            except Exception as e:
                logger.warning(f"⚠ YouTube API initialization failed: {e}")

    def get_top_comments(self, video_id: str, max_results: int = 40) -> List[Dict]:
        """
        Top comments by relevance for one video (YouTube caps a single
        commentThreads request at 100 - not paginated here since this
        agent only needs the top handful per video, aggregated across
        many videos, not every comment on any one video).
        """
        if not self.youtube:
            return []
        try:
            response = self.youtube.commentThreads().list(
                part='snippet',
                videoId=video_id,
                order='relevance',
                maxResults=min(max_results, 100),
                textFormat='plainText'
            ).execute()

            comments = []
            for item in response.get('items', []):
                top = item['snippet']['topLevelComment']['snippet']
                comments.append({
                    'text': top.get('textDisplay', ''),
                    'like_count': top.get('likeCount', 0),
                    'author': top.get('authorDisplayName', '')
                })
            return comments
        except HttpError as e:
            # Comments can be disabled on a video (403 commentsDisabled) -
            # a normal, expected condition, not worth escalating as an error.
            logger.info(f"ℹ Could not fetch comments for {video_id} (may have comments disabled): {e}")
            return []


class CommentAnalyzer:
    """Uses Claude to extract patterns from a batch of comments."""

    EMPTY_ANALYSIS = {
        'repeated_questions': [], 'excitement_signals': [], 'confusion_points': [],
        'controversy_opportunities': [], 'vocabulary_patterns': [], 'content_ideas': []
    }

    def __init__(self):
        self.client = Anthropic()

    def analyze(self, comments: List[Dict], context_label: str) -> Dict:
        if not comments:
            return dict(self.EMPTY_ANALYSIS)

        comment_texts = [c['text'] for c in comments[:200]]
        prompt = f"""Analyze these YouTube comments from {context_label} and extract patterns.

Comments:
{json.dumps(comment_texts, indent=2)[:8000]}

Generate a JSON object with:
- repeated_questions: list of questions asked multiple times across comments
- excitement_signals: list of phrases/moments that generated strong positive reaction
- confusion_points: list of things viewers seemed confused about
- controversy_opportunities: list of debate-worthy topics that emerged
- vocabulary_patterns: list of slang/phrases the audience actually uses
- content_ideas: list of 3-5 specific content ideas suggested by these comments

Output ONLY valid JSON."""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}]
            )
            text = response.content[0].text
            start_idx = text.find('{')
            end_idx = text.rfind('}') + 1
            if start_idx >= 0 and end_idx > start_idx:
                result = json.loads(text[start_idx:end_idx])
                return {**dict(self.EMPTY_ANALYSIS), **result}
            raise ValueError("No JSON found in response")
        except Exception as e:
            logger.warning(f"⚠ Comment analysis failed: {e}")
            return dict(self.EMPTY_ANALYSIS)


class InsightsStore:
    """Persists the ideas backlog and vocabulary reference for the script agent to read."""

    def __init__(self, data_dir: str = './data'):
        self.ideas_path = Path(data_dir) / 'ideas_backlog.json'
        self.vocab_path = Path('./prompts') / 'vocabulary_reference.txt'

    def add_ideas(self, ideas: List[str], source: str):
        if not ideas:
            return
        backlog = self._load_ideas()
        timestamp = datetime.now().isoformat()
        for idea in ideas:
            backlog.append({'idea': idea, 'source': source, 'added_at': timestamp, 'status': 'new'})

        self.ideas_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ideas_path, 'w') as f:
            json.dump(backlog, f, indent=2)

    def _load_ideas(self) -> List[Dict]:
        if not self.ideas_path.exists():
            return []
        try:
            with open(self.ideas_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠ Could not load ideas backlog: {e}")
            return []

    def add_vocabulary(self, patterns: List[str]):
        """Append new vocabulary patterns, deduped, to the reference file."""
        if not patterns:
            return

        existing = set()
        if self.vocab_path.exists():
            existing = set(line.strip() for line in self.vocab_path.read_text().splitlines() if line.strip() and not line.startswith('#'))

        new_patterns = [p for p in patterns if p and p not in existing]
        if not new_patterns:
            return

        self.vocab_path.parent.mkdir(parents=True, exist_ok=True)
        is_new_file = not self.vocab_path.exists()
        with open(self.vocab_path, 'a') as f:
            if is_new_file:
                f.write("# Audience vocabulary patterns (auto-collected by Comment Mining agent)\n")
            for p in new_patterns:
                f.write(f"{p}\n")


class CommentMiningAgent:
    """Main orchestrator - weekly pass over own + competitor comments."""

    def __init__(self, data_dir: str = './data'):
        self.data_dir = data_dir
        self.channel_memory = ChannelMemory(os.path.join(data_dir, 'chaos_merchant.db'))
        self.fetcher = CommentFetcher()
        self.analyzer = CommentAnalyzer()
        self.store = InsightsStore(data_dir)

    def run_weekly_mining(self) -> Dict:
        logger.info("=" * 70)
        logger.info("💬 COMMENT MINING - Weekly Analysis")
        logger.info("=" * 70)

        own_analysis = self._mine_own_comments()
        competitor_analysis = self._mine_competitor_comments()

        all_ideas = own_analysis.get('content_ideas', []) + competitor_analysis.get('content_ideas', [])
        all_vocab = own_analysis.get('vocabulary_patterns', []) + competitor_analysis.get('vocabulary_patterns', [])

        self.store.add_ideas(all_ideas, source='comment_mining')
        self.store.add_vocabulary(all_vocab)

        report = {
            'status': 'success',
            'own_shorts_analyzed': own_analysis.get('videos_analyzed', 0),
            'competitor_videos_analyzed': competitor_analysis.get('videos_analyzed', 0),
            'own_insights': own_analysis,
            'competitor_insights': competitor_analysis,
            'ideas_added': len(all_ideas),
            'vocabulary_added': len(all_vocab),
            'timestamp': datetime.now().isoformat()
        }

        self._save_dated_report(report)

        logger.info(
            f"\n✓ Comment mining complete: {report['own_shorts_analyzed']} own + "
            f"{report['competitor_videos_analyzed']} competitor videos analyzed, "
            f"{report['ideas_added']} idea(s) added, {report['vocabulary_added']} vocab pattern(s) added"
        )
        logger.info("=" * 70)

        return report

    def _mine_own_comments(self) -> Dict:
        """
        Top comments from up to the last 30 own shorts. Needs real
        youtube_id links (set via ChannelMemory.mark_published(), which
        the Publisher module calls once a short is actually uploaded) -
        cleanly returns an empty analysis on a channel with nothing
        published yet, rather than crashing on an empty video list.
        """
        recent_shorts = self._get_recent_own_shorts(limit=30)
        if not recent_shorts:
            logger.info("ℹ No published own shorts with a linked YouTube ID yet - skipping own-comment mining")
            return {**dict(CommentAnalyzer.EMPTY_ANALYSIS), 'videos_analyzed': 0}

        all_comments = []
        for short in recent_shorts:
            all_comments.extend(self.fetcher.get_top_comments(short['youtube_id'], max_results=40))

        if not all_comments:
            logger.info("ℹ No comments found on own shorts yet")
            return {**dict(CommentAnalyzer.EMPTY_ANALYSIS), 'videos_analyzed': len(recent_shorts)}

        analysis = self.analyzer.analyze(all_comments, context_label="our own recent Shorts")
        analysis['videos_analyzed'] = len(recent_shorts)
        return analysis

    def _get_recent_own_shorts(self, limit: int = 30) -> List[Dict]:
        """Published (youtube_id set) shorts, most recent first."""
        try:
            conn = sqlite3.connect(str(self.channel_memory.db_path))
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, youtube_id, title FROM channel_shorts
                WHERE youtube_id IS NOT NULL
                ORDER BY publish_date DESC LIMIT ?
            ''', (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [{'id': r[0], 'youtube_id': r[1], 'title': r[2]} for r in rows]
        except Exception as e:
            logger.error(f"❌ Failed to query recent own shorts: {e}")
            return []

    def _mine_competitor_comments(self) -> Dict:
        """
        Top comments across up to 5 competitor channels' recent videos
        (~200 comments total). Works independently of the user's own
        channel state - reuses CompetitorMonitor's existing config
        loading and YouTube fetching (agents/competitor_monitor.py) rather
        than duplicating that logic. Cleanly returns empty if no
        competitors are configured yet, same honest-empty-state pattern
        competitor_monitor.py itself already uses.
        """
        try:
            from agents.competitor_monitor import CompetitorMonitor
            monitor = CompetitorMonitor()
            competitors = monitor.load_competitors()
        except Exception as e:
            logger.warning(f"⚠ Could not load competitors: {e}")
            return {**dict(CommentAnalyzer.EMPTY_ANALYSIS), 'videos_analyzed': 0}

        if not competitors:
            logger.info(
                "ℹ No competitors configured yet - skipping competitor comment mining "
                "(add some with: python -m agents.competitor_monitor add @SomeChannel)"
            )
            return {**dict(CommentAnalyzer.EMPTY_ANALYSIS), 'videos_analyzed': 0}

        all_comments = []
        videos_analyzed = 0
        for competitor in competitors[:5]:
            channel_id = competitor.get('channel_id', '')
            recent_videos = monitor.youtube_fetcher.get_channel_recent_uploads(channel_id, max_results=3)
            for video in recent_videos:
                all_comments.extend(self.fetcher.get_top_comments(video['video_id'], max_results=40))
                videos_analyzed += 1

        if not all_comments:
            logger.info("ℹ No competitor comments found (competitors configured, but zero real results)")
            return {**dict(CommentAnalyzer.EMPTY_ANALYSIS), 'videos_analyzed': videos_analyzed}

        analysis = self.analyzer.analyze(all_comments[:200], context_label="top 5 competitor channels")
        analysis['videos_analyzed'] = videos_analyzed
        return analysis

    def _save_dated_report(self, report: Dict):
        insights_dir = Path(self.data_dir) / 'comment_insights'
        insights_dir.mkdir(parents=True, exist_ok=True)
        report_path = insights_dir / f"insights_{datetime.now().strftime('%Y%m%d')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        logger.info(f"✓ Dated insights report saved: {report_path}")


def run_comment_mining() -> Dict:
    """Main entry point, scheduled weekly Sunday 10am."""
    try:
        agent = CommentMiningAgent()
        return agent.run_weekly_mining()
    except Exception as e:
        logger.error(f"❌ Comment mining failed: {e}")
        return {'status': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_comment_mining()
    print(json.dumps(result, indent=2, default=str))
