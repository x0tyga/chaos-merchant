"""
Competitor Monitor Agent - Step 13
Monitors 5-15 competitors every 3 hours for viral spikes
Alert quality > volume - false positives train you to ignore alerts
"""

import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import os

logger = logging.getLogger(__name__)

try:
    from anthropic import Anthropic
except ImportError:
    raise ImportError("anthropic SDK required: pip install anthropic")

from core.cost_tracker import log_anthropic_usage

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLEAPICLIENT_AVAILABLE = True
except ImportError:
    GOOGLEAPICLIENT_AVAILABLE = False
    logger.warning("googleapiclient not available - YouTube API will be unavailable (pip install google-api-python-client)")


class YouTubeCompetitorFetcher:
    """Fetches real competitor data from YouTube API"""

    def __init__(self):
        self.api_key = os.getenv('YOUTUBE_API_KEY', '')
        self.youtube = None
        if not GOOGLEAPICLIENT_AVAILABLE:
            logger.warning("⚠ googleapiclient not installed - competitor monitoring will use fallback data")
        elif self.api_key:
            try:
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)
            except Exception as e:
                logger.warning(f"⚠ YouTube API initialization failed: {e}")

    def get_channel_recent_uploads(self, channel_id: str, max_results: int = 5) -> List[Dict]:
        """Fetch recent uploads from a competitor channel"""
        if not self.youtube:
            logger.warning("⚠ YouTube API not available")
            return []

        try:
            # Get uploads playlist for channel
            channel_response = self.youtube.channels().list(
                part='contentDetails',
                id=channel_id
            ).execute()

            if not channel_response.get('items'):
                logger.warning(f"⚠ Channel not found: {channel_id}")
                return []

            uploads_playlist_id = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # Get recent videos from uploads playlist
            videos_response = self.youtube.playlistItems().list(
                part='snippet',
                playlistId=uploads_playlist_id,
                maxResults=max_results
            ).execute()

            videos = []
            for item in videos_response.get('items', []):
                video_id = item['snippet']['resourceId']['videoId']
                videos.append({
                    'video_id': video_id,
                    'title': item['snippet']['title'],
                    'published_at': item['snippet']['publishedAt'],
                    'thumbnail': item['snippet']['thumbnails'].get('high', {}).get('url', '')
                })

            logger.info(f"✓ Fetched {len(videos)} recent uploads from {channel_id}")
            return videos

        except HttpError as e:
            logger.warning(f"⚠ YouTube API error for {channel_id}: {e}")
            return []

    def get_video_stats(self, video_id: str) -> Optional[Dict]:
        """Get view count and engagement stats for a video"""
        if not self.youtube:
            return None

        try:
            response = self.youtube.videos().list(
                part='statistics',
                id=video_id
            ).execute()

            if not response.get('items'):
                return None

            stats = response['items'][0]['statistics']
            return {
                'video_id': video_id,
                'views': int(stats.get('viewCount', 0)),
                'likes': int(stats.get('likeCount', 0)),
                'comments': int(stats.get('commentCount', 0))
            }

        except HttpError as e:
            logger.warning(f"⚠ Could not fetch stats for {video_id}: {e}")
            return None

    def resolve_channel_id(self, handle_or_url: str) -> Optional[Dict]:
        """
        Resolve a YouTube handle (@name) or channel URL to a real
        channel_id + display name via the Data API, so competitors can be
        added by URL instead of hand-typing channel IDs.

        Accepts:
        - '@SomeHandle' or 'SomeHandle'
        - 'https://www.youtube.com/@SomeHandle'
        - 'https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx'
        """
        if not self.youtube:
            logger.error("❌ YouTube API not available - cannot resolve channel")
            return None

        raw = handle_or_url.strip()

        # Direct channel ID URL - no handle resolution needed, just verify it exists
        if '/channel/' in raw:
            channel_id = raw.split('/channel/')[-1].split('/')[0].split('?')[0]
            try:
                response = self.youtube.channels().list(part='snippet', id=channel_id).execute()
                items = response.get('items', [])
                if items:
                    return {'channel_id': channel_id, 'channel': items[0]['snippet']['title']}
                logger.error(f"❌ No channel found for ID: {channel_id}")
                return None
            except HttpError as e:
                logger.error(f"❌ Could not resolve channel ID {channel_id}: {e}")
                return None

        # Extract handle from a /@handle URL, or treat the whole input as a handle
        if '/@' in raw:
            handle = '@' + raw.split('/@')[-1].split('/')[0].split('?')[0]
        else:
            handle = '@' + raw.lstrip('@')

        try:
            response = self.youtube.channels().list(part='id,snippet', forHandle=handle).execute()
            items = response.get('items', [])
            if not items:
                logger.error(f"❌ No channel found for handle: {handle}")
                return None
            return {'channel_id': items[0]['id'], 'channel': items[0]['snippet']['title']}
        except HttpError as e:
            logger.error(f"❌ Could not resolve handle {handle}: {e}")
            return None


class CompetitorAlert:
    """Generates high-quality competitor alerts with analysis"""

    def __init__(self):
        self.client = Anthropic()
        self.model = "claude-haiku-4-5-20251001"
        self.alert_history_path = Path('./data/competitor_alerts_history.json')
        self._init_history()

    def _init_history(self):
        """Initialize alert history to prevent duplicate alerts"""
        if not self.alert_history_path.exists():
            self.alert_history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.alert_history_path, 'w') as f:
                json.dump({'alerts': []}, f)

    def _load_history(self) -> Dict:
        """Load alert history"""
        try:
            with open(self.alert_history_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load alert history: {e}")
            return {'alerts': []}

    def _save_history(self, history: Dict):
        """Save alert history"""
        try:
            with open(self.alert_history_path, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save alert history: {e}")

    def should_alert_on_video(self, video_id: str, video_title: str) -> bool:
        """
        Check if video has been alerted on before
        Prevents duplicate alerts on same video
        """
        history = self._load_history()
        for alert in history.get('alerts', []):
            if alert.get('video_id') == video_id:
                logger.debug(f"⊗ Already alerted on this video: {video_title}")
                return False
        return True

    def check_channel_memory_coverage(self, topic: str, channel_recent_topics: List[str]) -> bool:
        """
        Check if topic already covered in channel memory
        Prevent alerting on already-covered topics
        """
        if not channel_recent_topics:
            return True  # No memory yet, allow alert

        topic_lower = topic.lower()
        for covered in channel_recent_topics:
            if topic_lower in covered.lower() or covered.lower() in topic_lower:
                logger.debug(f"⊗ Topic already covered: {topic}")
                return False
        return True

    def generate_alert_analysis(self, video_title: str, view_spike: int, trend_category: str) -> str:
        """
        Use Claude to analyze why video is performing well
        Returns: analysis + 3 distinct Chaos Merchant angles
        """

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=400,
                messages=[{
                    'role': 'user',
                    'content': f"""Competitor video is going viral. Analyze and generate angles:

VIDEO TITLE: {video_title}
VIEWS GAINED (6h): {view_spike}
CATEGORY: {trend_category}

Provide:
1. One-sentence analysis of WHY it's performing well
2. Three DISTINCT Chaos Merchant angles to cover the same topic differently

Format:
WHY: [one sentence]
ANGLE 1: [specific gaming/culture moment angle]
ANGLE 2: [different gaming niche angle]
ANGLE 3: [internet culture or speedrun angle]"""
                }]
            )
            log_anthropic_usage('competitor_monitor', response)

            return response.content[0].text
        except Exception as e:
            logger.error(f"Failed to generate analysis: {e}")
            return "Analysis generation failed"

    def create_alert(self, video_id: str, video_title: str, channel_name: str, views_gained: int, trend_category: str, hours_ago: int = 6) -> Dict:
        """
        Create high-quality alert with full context
        """

        analysis = self.generate_alert_analysis(video_title, views_gained, trend_category)

        alert = {
            'video_id': video_id,
            'channel': channel_name,
            'title': video_title,
            'views_gained_6h': views_gained,
            'category': trend_category,
            'hours_tracking': hours_ago,
            'analysis': analysis,
            'urgency': 'POST WITHIN 2 HOURS' if hours_ago <= 3 else 'POST WITHIN 24 HOURS',
            'alert_time': datetime.now().isoformat(),
            'timestamp': datetime.now().isoformat()
        }

        # Save to history
        history = self._load_history()
        history['alerts'].append(alert)
        # Keep only last 100 alerts
        history['alerts'] = history['alerts'][-100:]
        self._save_history(history)

        return alert


class CompetitorMonitor:
    """Monitors competitors every 3 hours for viral spikes"""

    ALERT_THRESHOLD = int(os.getenv('COMPETITOR_ALERT_THRESHOLD', '10000'))  # 10k views in 6h by default

    def __init__(self, quota_tracker=None):
        self.quota_tracker = quota_tracker
        self.alert_generator = CompetitorAlert()
        self.config_path = Path('./config/competitors.json')
        self.youtube_fetcher = YouTubeCompetitorFetcher()
        self._init_config()

    def _init_config(self):
        """Initialize competitors config"""
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            # Empty by default - a placeholder channel_id like 'UC_example1'
            # isn't a real channel, so seeding it just produces "channel not
            # found" warnings and silently drives check_competitors() into
            # its fallback path. Add real competitors with:
            #   python -m agents.competitor_monitor add @SomeChannel
            config = {
                'competitors': [],
                'check_interval_hours': 3,
                'alert_threshold_views_6h': self.ALERT_THRESHOLD
            }
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"✓ Competitor config template created (empty): {self.config_path}")
            logger.info("  Add competitors with: python -m agents.competitor_monitor add @SomeChannel")

    def load_competitors(self) -> List[Dict]:
        """Load competitor list from config"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                return config.get('competitors', [])
        except Exception as e:
            logger.error(f"Failed to load competitors: {e}")
            return []

    def add_competitor(self, handle_or_url: str, category: str = 'gaming') -> Optional[Dict]:
        """
        Resolve a YouTube handle/URL to a real channel_id via the Data API
        and append it to config/competitors.json. Returns the added
        competitor dict, or None if resolution failed (bad handle, API
        unavailable, etc).
        """
        resolved = self.youtube_fetcher.resolve_channel_id(handle_or_url)
        if not resolved:
            return None

        competitors = self.load_competitors()
        if any(c.get('channel_id') == resolved['channel_id'] for c in competitors):
            logger.info(f"ℹ {resolved['channel']} is already in competitors.json")
            return resolved

        competitors.append({
            'channel': resolved['channel'],
            'channel_id': resolved['channel_id'],
            'category': category
        })

        with open(self.config_path, 'r') as f:
            config = json.load(f)
        config['competitors'] = competitors
        with open(self.config_path, 'w') as f:
            json.dump(config, f, indent=2)

        logger.info(f"✓ Added competitor: {resolved['channel']} ({resolved['channel_id']}, category: {category})")
        return resolved

    def check_competitors(self, channel_memory_recent_topics: List[str] = None) -> Dict:
        """
        Monitor all configured competitors
        Returns: alerts + summary
        """

        logger.info("=" * 70)
        logger.info("🔍 COMPETITOR MONITOR - 3-hour check")
        logger.info("=" * 70)

        competitors = self.load_competitors()
        if not competitors:
            logger.warning("⚠ No competitors configured")
            return {'status': 'no_competitors', 'alerts': []}

        alerts = []

        # No fallback mock data - if the API is unavailable, that's a real
        # problem worth surfacing distinctly rather than masking it with
        # fake-looking alerts that could get acted on as if they were real.
        if not self.youtube_fetcher.youtube:
            logger.error("❌ YouTube API not available (missing/invalid YOUTUBE_API_KEY) - cannot check competitors")
            return {
                'status': 'api_unavailable',
                'competitors_checked': len(competitors),
                'alerts_triggered': 0,
                'alerts': [],
                'next_check': (datetime.now() + timedelta(hours=3)).isoformat(),
                'timestamp': datetime.now().isoformat()
            }

        viral_videos = []
        for competitor in competitors:
            channel_id = competitor.get('channel_id', '')
            channel_name = competitor.get('channel', '')

            # Get recent uploads
            recent_videos = self.youtube_fetcher.get_channel_recent_uploads(channel_id, max_results=5)

            for video in recent_videos:
                # Get current view count
                stats = self.youtube_fetcher.get_video_stats(video['video_id'])
                if stats:
                    # Calculate approximate views gained (proxy: view count / time since upload)
                    published_at = datetime.fromisoformat(video['published_at'].replace('Z', '+00:00'))
                    hours_since_upload = (datetime.now(published_at.tzinfo) - published_at).total_seconds() / 3600
                    if hours_since_upload > 0.5:  # Only if video is at least 30 min old
                        views_gained = int(stats['views'] / max(hours_since_upload, 1))
                        viral_videos.append({
                            'channel': channel_name,
                            'title': video['title'],
                            'video_id': video['video_id'],
                            'views_gained': views_gained,
                            'category': competitor.get('category', 'gaming')
                        })

        if viral_videos:
            logger.info(f"✓ Fetched {len(viral_videos)} videos from {len(competitors)} competitors")
        else:
            logger.info("ℹ No videos found for configured competitors - check that channel_id values in "
                        "config/competitors.json are valid (add real ones with: "
                        "python -m agents.competitor_monitor add @SomeChannel)")

        for video in viral_videos:
            views_gained = video['views_gained']

            # Check thresholds
            if views_gained < self.ALERT_THRESHOLD:
                logger.debug(f"⊗ Below alert threshold: {video['title']} ({views_gained} views)")
                continue

            # Check for duplicates
            if not self.alert_generator.should_alert_on_video(video['video_id'], video['title']):
                continue

            # Check channel memory
            if not self.alert_generator.check_channel_memory_coverage(video['title'], channel_memory_recent_topics or []):
                logger.info(f"⊗ Already covered: {video['title']}")
                continue

            # Generate high-quality alert
            alert = self.alert_generator.create_alert(
                video_id=video['video_id'],
                video_title=video['title'],
                channel_name=video['channel'],
                views_gained=views_gained,
                trend_category=video['category']
            )

            alerts.append(alert)
            logger.info(f"✓ ALERT: {video['channel']} - {video['title']} ({views_gained} views)")
            logger.info(f"  Urgency: {alert['urgency']}")

        logger.info(f"\n✓ Competitor check complete: {len(alerts)} alerts triggered")
        logger.info("=" * 70)

        return {
            'status': 'success',
            'competitors_checked': len(competitors),
            'alerts_triggered': len(alerts),
            'alerts': alerts,
            'next_check': (datetime.now() + timedelta(hours=3)).isoformat(),
            'timestamp': datetime.now().isoformat()
        }


def monitor_competitors_3h(channel_memory_recent_topics: List[str] = None, quota_tracker=None) -> Dict:
    """
    Main entry point: run competitor monitor check every 3 hours
    Scheduled by: core/scheduler.py

    Returns: alerts or empty list if no viral videos
    """

    logger.info("\n" + "=" * 70)
    logger.info("🎬 COMPETITOR MONITOR AGENT - Step 13")
    logger.info("=" * 70)

    monitor = CompetitorMonitor(quota_tracker)
    result = monitor.check_competitors(channel_memory_recent_topics)

    # Save alerts to file
    if result['alerts']:
        alerts_path = Path('./data/competitor_alerts_latest.json')
        alerts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(alerts_path, 'w') as f:
            json.dump(result['alerts'], f, indent=2)
        logger.info(f"✓ Alerts saved: {alerts_path}")

    return result


if __name__ == "__main__":
    import sys
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Competitor Monitor CLI")
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Add a competitor by YouTube handle or URL')
    add_parser.add_argument('handle_or_url', help='e.g. @SomeChannel or https://youtube.com/@SomeChannel')
    add_parser.add_argument('--category', default='gaming', help='Competitor category (default: gaming)')

    subparsers.add_parser('list', help='List configured competitors')

    args = parser.parse_args()

    if args.command == 'add':
        monitor = CompetitorMonitor()
        result = monitor.add_competitor(args.handle_or_url, args.category)
        sys.exit(0 if result else 1)
    elif args.command == 'list':
        monitor = CompetitorMonitor()
        competitors = monitor.load_competitors()
        if not competitors:
            print("No competitors configured. Add one with: python -m agents.competitor_monitor add @SomeChannel")
        for c in competitors:
            print(f"  {c.get('channel')} ({c.get('channel_id')}) - {c.get('category')}")
    else:
        parser.print_help()
