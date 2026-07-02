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

try:
    from anthropic import Anthropic
except ImportError:
    raise ImportError("anthropic SDK required: pip install anthropic")

logger = logging.getLogger(__name__)


class CompetitorAlert:
    """Generates high-quality competitor alerts with analysis"""

    def __init__(self):
        self.client = Anthropic()
        self.model = "claude-3-5-haiku-20241022"
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
        self._init_config()

    def _init_config(self):
        """Initialize competitors config"""
        if not self.config_path.exists():
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            config = {
                'competitors': [
                    {'channel': 'ExampleGaming1', 'channel_id': 'UC_example1', 'category': 'gaming'},
                    {'channel': 'ExampleGaming2', 'channel_id': 'UC_example2', 'category': 'gaming'},
                ],
                'check_interval_hours': 3,
                'alert_threshold_views_6h': self.ALERT_THRESHOLD
            }
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"✓ Competitor config template created: {self.config_path}")

    def load_competitors(self) -> List[Dict]:
        """Load competitor list from config"""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                return config.get('competitors', [])
        except Exception as e:
            logger.error(f"Failed to load competitors: {e}")
            return []

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

        # Mock check: in production would use YouTube API
        mock_viral_videos = [
            {
                'channel': 'ExampleGaming1',
                'title': 'GTA6 NEW EXPLOIT BREAKS EVERYTHING',
                'video_id': 'mock_viral_001',
                'views_gained': 25000,
                'category': 'glitch'
            },
            {
                'channel': 'ExampleGaming2',
                'title': 'Speedrunner finds impossible skip',
                'video_id': 'mock_viral_002',
                'views_gained': 8000,
                'category': 'speedrun'
            }
        ]

        for video in mock_viral_videos:
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
