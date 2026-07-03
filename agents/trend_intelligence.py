"""
Trend Intelligence Agent - Step 12
Daily content strategy at 7am
Surfaces quality trends with scoring (velocity, volume, novelty, viral window)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import json
from pathlib import Path
import os

logger = logging.getLogger(__name__)

try:
    from anthropic import Anthropic
except ImportError:
    raise ImportError("anthropic SDK required: pip install anthropic")

try:
    import praw
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False
    logger.warning("praw not available - Reddit trends will be skipped (pip install praw)")

try:
    import feedparser
    FEEDPARSER_AVAILABLE = True
except ImportError:
    FEEDPARSER_AVAILABLE = False
    logger.warning("feedparser not available - RSS feeds will be skipped (pip install feedparser)")


class TrendFetcher:
    """Fetches real trends from multiple sources"""

    REDDIT_SUBREDDITS = ['GTA6', 'grandtheftauto', 'gaming']
    RSS_FEEDS = [
        'https://www.polygon.com/rss/index.xml',
        'https://feeds.ign.com/ign/all',
        'https://kotaku.com/rss',
    ]

    @staticmethod
    def fetch_reddit_trends() -> List[Tuple[str, float, int]]:
        """Fetch trending topics from Reddit subreddits"""
        trends = []
        try:
            reddit = praw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID', ''),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET', ''),
                user_agent=os.getenv('REDDIT_USER_AGENT', 'chaos-merchant/1.0')
            )

            for subreddit_name in TrendFetcher.REDDIT_SUBREDDITS:
                try:
                    subreddit = reddit.subreddit(subreddit_name)
                    for submission in subreddit.hot(limit=10):
                        trends.append((
                            submission.title,
                            min(submission.score / 10000, 1.0),  # velocity proxy
                            submission.score  # volume
                        ))
                    logger.info(f"✓ Fetched 10 posts from r/{subreddit_name}")
                except Exception as e:
                    logger.warning(f"⚠ Could not fetch r/{subreddit_name}: {e}")
                    continue

            return trends[:15]
        except Exception as e:
            logger.warning(f"⚠ Reddit API unavailable: {e}")
            return []

    @staticmethod
    def fetch_rss_trends() -> List[Tuple[str, float, int]]:
        """Fetch gaming news from RSS feeds"""
        trends = []
        try:
            for feed_url in TrendFetcher.RSS_FEEDS:
                try:
                    feed = feedparser.parse(feed_url)
                    for entry in feed.entries[:5]:
                        title = entry.get('title', 'Untitled')
                        # RSS doesn't have score, use entry index as volume proxy
                        trends.append((title, 0.5, 5000))
                    logger.info(f"✓ Fetched {min(5, len(feed.entries))} posts from {feed_url.split('/')[2]}")
                except Exception as e:
                    logger.warning(f"⚠ Could not fetch {feed_url}: {e}")
                    continue

            return trends
        except Exception as e:
            logger.warning(f"⚠ RSS feed unavailable: {e}")
            return []

    @staticmethod
    def get_trends() -> List[Tuple[str, float, int, float, int]]:
        """Fetch all trends from configured sources"""
        all_trends = []

        # Fetch Reddit trends
        if PRAW_AVAILABLE:
            reddit_trends = TrendFetcher.fetch_reddit_trends()
            for title, velocity, volume in reddit_trends:
                all_trends.append((title, velocity, volume, 0.75, 24))

        # Fetch RSS trends
        if FEEDPARSER_AVAILABLE:
            rss_trends = TrendFetcher.fetch_rss_trends()
            for title, velocity, volume in rss_trends:
                all_trends.append((title, velocity, volume, 0.70, 48))

        # Fallback: provide diversified gaming trends if APIs unavailable
        if not all_trends:
            logger.info("ℹ Using fallback trend set (all APIs unavailable)")
            all_trends = [
                ('GTA6 new exploit discovered', 0.95, 25000, 0.85, 8),
                ('Speedrunner breaks world record', 0.85, 18000, 0.72, 6),
                ('New game announced', 0.70, 12000, 0.80, 48),
                ('Graphics card benchmark results', 0.60, 8000, 0.65, 24),
                ('Esports tournament highlights', 0.75, 15000, 0.68, 12),
            ]

        # Remove duplicates and return top 10
        unique_trends = []
        seen = set()
        for trend in all_trends[:15]:
            trend_lower = trend[0].lower()
            if trend_lower not in seen:
                seen.add(trend_lower)
                unique_trends.append(trend)

        return unique_trends[:10]


class TrendScorer:
    """Scores trends by velocity, volume, novelty, and viral window"""

    @staticmethod
    def score_trend(trend_text: str, velocity: float, volume: int, novelty: float, hours_until_saturation: int = 24) -> Dict:
        """
        Score a single trend
        velocity: growth rate in last 6 hours (0.0-1.0)
        volume: absolute search/discussion volume
        novelty: 0.0 (already covered) to 1.0 (completely new)
        viral_window: estimated hours until trend peaks
        """

        # Composite score: velocity (40%) + novelty (40%) + volume_normalized (20%)
        volume_score = min(volume / 10000, 1.0)  # Normalize to 0-1
        composite_score = (velocity * 0.4) + (novelty * 0.4) + (volume_score * 0.2)

        urgency = "Post within 2 hours" if hours_until_saturation <= 12 else "Post within 24 hours"

        return {
            'trend': trend_text,
            'velocity': round(velocity, 2),
            'volume': volume,
            'novelty': round(novelty, 2),
            'composite_score': round(composite_score, 3),
            'viral_window_hours': hours_until_saturation,
            'urgency': urgency,
            'alerts_at': (datetime.now() + timedelta(hours=hours_until_saturation - 2)).isoformat() if hours_until_saturation > 2 else 'NOW'
        }


class TrendIntelligence:
    """Generates daily trend brief with 3+ distinct Chaos Merchant angles per trend"""

    def __init__(self):
        self.client = Anthropic()
        self.model = "claude-haiku-4-5-20251001"

    def generate_trend_angles(self, trend: str, context: str = "") -> Tuple[List[str], str]:
        """
        Use Claude to generate 3 distinct Chaos Merchant angles for a trend
        Returns: (list of angles, estimated_viral_window)
        """

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{
                    'role': 'user',
                    'content': f"""Generate 3 distinct Chaos Merchant YouTube Shorts angles for this trending topic:

TREND: {trend}
{f"CONTEXT: {context}" if context else ""}

For each angle, write as: "ANGLE [N]: [Specific gaming/internet culture hook]"

Make each angle unique and specific to gaming, internet culture, or trending moments.
Then add: VIRAL_WINDOW: [estimated hours this trend will be hot]

Example format:
ANGLE 1: [Specific glitch or moment angle]
ANGLE 2: [Speedrun or gameplay angle]
ANGLE 3: [Failed attempt or funny moment angle]
VIRAL_WINDOW: 24"""
                }]
            )

            content = response.content[0].text
            lines = content.strip().split('\n')

            angles = []
            viral_window = "24"

            for line in lines:
                if line.startswith('ANGLE'):
                    angles.append(line.replace('ANGLE', '').strip())
                elif line.startswith('VIRAL_WINDOW'):
                    viral_window = line.split(':')[1].strip().split()[0]

            return angles[:3], viral_window
        except Exception as e:
            logger.error(f"❌ Failed to generate angles: {e}")
            return [f"Gaming angle on {trend}", f"Speedrun angle on {trend}", f"Competitive angle on {trend}"], "24"

    def compile_brief(self, top_trends: List[Dict], gaming_calendar: Dict) -> Dict:
        """
        Compile final trend intelligence brief with quality-focused output
        """

        brief = {
            'generated_at': datetime.now().isoformat(),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'calendar_events': gaming_calendar.get('upcoming', []),
            'top_trends': [],
            'quality_notes': 'Quality > Quantity. Each trend has 3+ distinct angles.'
        }

        for trend in top_trends[:5]:  # Top 5 only
            angles, window = self.generate_trend_angles(
                trend['trend'],
                f"Volume: {trend['volume']}, Novelty: {trend['novelty']}"
            )

            trend_brief = {
                'trend': trend['trend'],
                'composite_score': trend['composite_score'],
                'velocity': trend['velocity'],
                'novelty': trend['novelty'],
                'urgency': trend['urgency'],
                'viral_window_hours': int(window),
                'angles': angles,
                'reference_links': [
                    f"https://www.google.com/search?q={trend['trend'].replace(' ', '+')}",
                    f"https://www.reddit.com/search/?q={trend['trend'].replace(' ', '%20')}"
                ]
            }

            brief['top_trends'].append(trend_brief)

        return brief


def generate_daily_trend_intelligence(channel_memory_recent_topics: List[str] = None) -> Dict:
    """
    Generate daily 7am trend intelligence brief

    Fetches real trends from:
    - Reddit (r/GTA6, r/grandtheftauto, r/gaming)
    - RSS feeds (Polygon, IGN, Kotaku)
    - Fallback mock trends if APIs unavailable

    Returns: Daily brief with scored trends + Chaos Merchant angles
    """

    logger.info("=" * 70)
    logger.info("📊 TREND INTELLIGENCE - Daily Content Strategy")
    logger.info("=" * 70)

    # Fetch real trends from multiple sources
    fetcher = TrendFetcher()
    real_trends = fetcher.get_trends()

    scorer = TrendScorer()
    scored_trends = []

    for trend_text, velocity, volume, novelty, window in real_trends:
        # Check against recent topics (14-day dedup)
        if channel_memory_recent_topics and trend_text.lower() in [t.lower() for t in channel_memory_recent_topics]:
            logger.info(f"  ⊗ {trend_text} (already covered recently, skipping)")
            continue

        scored = scorer.score_trend(trend_text, velocity, volume, novelty, window)
        scored_trends.append(scored)
        logger.info(f"  ✓ {trend_text} (score: {scored['composite_score']:.1%}, window: {window}h)")

    # Mock gaming calendar
    gaming_calendar = {
        'upcoming': [
            'GTA6 release Q1 2025',
            'Game Awards 2026 voting begins',
            'Summer Game Fest 2026'
        ]
    }

    # Generate brief
    intel = TrendIntelligence()
    brief = intel.compile_brief(scored_trends[:5], gaming_calendar)

    logger.info(f"\n✓ Trend intelligence complete: {len(brief['top_trends'])} trends with angles")
    logger.info(f"  Upcoming events: {len(brief['calendar_events'])}")
    logger.info("=" * 70)

    # Save brief
    brief_path = Path('./data/trend_intelligence_latest.json')
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    with open(brief_path, 'w') as f:
        json.dump(brief, f, indent=2)

    logger.info(f"✓ Brief saved: {brief_path}")

    return {
        'status': 'success',
        'brief': brief,
        'trends_analyzed': len(scored_trends),
        'timestamp': datetime.now().isoformat()
    }
