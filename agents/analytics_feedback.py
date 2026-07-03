"""
Analytics & Feedback Agent - Step 10
Runs daily at 9am. Pulls real YouTube performance data at the 48h and
7-day marks for published shorts, updates the Hook Library with real
scores, detects viral spikes, tracks subscriber milestones, estimates
revenue once YPP thresholds are met, and self-updates prompts when
confidence is high.

Degrades gracefully on a fresh channel with zero published shorts: every
step below simply finds nothing to check and returns cleanly instead of
crashing on empty aggregates - there is no special-cased "empty channel"
branch, the normal data-driven logic just naturally has nothing to do.
"""

import csv
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLEAPICLIENT_AVAILABLE = True
except ImportError:
    GOOGLEAPICLIENT_AVAILABLE = False
    logger.warning("googleapiclient not available - YouTube API will be unavailable (pip install google-api-python-client)")

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False
    logger.warning("google-auth-oauthlib not available - YouTube Analytics (impressions/AVD/retention) will be unavailable")

from core.memory import HookLibrary, ChannelMemory
from core.notifications import send_notification

# YouTube Analytics API requires OAuth (private, owner-only metrics) -
# separate from the public Data API v3 used elsewhere in this codebase
# (competitor_monitor.py) which only needs an API key.
ANALYTICS_SCOPES = ['https://www.googleapis.com/auth/yt-analytics.readonly']

CHECK_MARKS = {'48h': 2, '7d': 7}  # mark label -> days_ago
SPIKE_MULTIPLIER = 3.0
SPIKE_WINDOW_HOURS = 6

# Prompt auto-update confidence thresholds
MIN_DATA_POINTS = 3
MIN_PERFORMANCE_MARGIN = 0.10  # 10%


class YouTubeStatsFetcher:
    """Public Data API v3 - views/likes/comments/subscriber count. No OAuth needed."""

    def __init__(self):
        self.api_key = os.getenv('YOUTUBE_API_KEY', '')
        self.youtube = None
        if not GOOGLEAPICLIENT_AVAILABLE:
            logger.warning("⚠ googleapiclient not installed - public YouTube stats unavailable")
        elif self.api_key:
            try:
                self.youtube = build('youtube', 'v3', developerKey=self.api_key)
            except Exception as e:
                logger.warning(f"⚠ YouTube API initialization failed: {e}")

    def get_video_stats(self, video_id: str) -> Optional[Dict]:
        """Views/likes/comments for one video - public data, works even for a brand new channel."""
        if not self.youtube:
            return None
        try:
            response = self.youtube.videos().list(part='statistics', id=video_id).execute()
            items = response.get('items', [])
            if not items:
                logger.warning(f"⚠ Video not found: {video_id}")
                return None
            stats = items[0]['statistics']
            return {
                'views': int(stats.get('viewCount', 0)),
                'likes': int(stats.get('likeCount', 0)),
                'comments': int(stats.get('commentCount', 0))
            }
        except HttpError as e:
            logger.warning(f"⚠ Could not fetch stats for {video_id}: {e}")
            return None

    def get_channel_stats(self, channel_id: str = None) -> Optional[Dict]:
        """Subscriber/view/video counts for a channel - public data, works even at 0 subscribers."""
        channel_id = channel_id or os.getenv('YOUTUBE_CHANNEL_ID')
        if not self.youtube or not channel_id:
            return None
        try:
            response = self.youtube.channels().list(part='statistics', id=channel_id).execute()
            items = response.get('items', [])
            if not items:
                return None
            stats = items[0]['statistics']
            return {
                'subscriber_count': int(stats.get('subscriberCount', 0)),
                'view_count': int(stats.get('viewCount', 0)),
                'video_count': int(stats.get('videoCount', 0))
            }
        except HttpError as e:
            logger.warning(f"⚠ Could not fetch channel stats: {e}")
            return None


class YouTubeAnalyticsFetcher:
    """
    OAuth-based YouTube Analytics API v2 - impressions, average view
    duration, retention curve. These are private-to-owner metrics, never
    available via a public API key no matter what the key can access.

    Requires a one-time interactive OAuth authorization (see the
    `python -m agents.analytics_feedback setup` CLI at the bottom of this
    file) before this can pull real data. Gracefully reports unavailable
    if that hasn't happened yet - callers skip impressions/AVD/retention
    rather than crashing, exactly like the "no data yet" empty-channel case.
    """

    def __init__(self):
        self.analytics = None
        if not OAUTH_AVAILABLE:
            logger.info("ℹ google-auth-oauthlib not installed - impressions/AVD/retention unavailable")
            return

        creds = self._load_credentials()
        if creds:
            try:
                self.analytics = build('youtubeAnalytics', 'v2', credentials=creds)
            except Exception as e:
                logger.warning(f"⚠ YouTube Analytics API initialization failed: {e}")

    def _load_credentials(self):
        token_path = os.getenv('YOUTUBE_ANALYTICS_TOKEN_PATH', './data/youtube_analytics_token.json')
        creds = None

        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, ANALYTICS_SCOPES)
            except Exception as e:
                logger.warning(f"⚠ Could not load YouTube Analytics token: {e}")

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                logger.warning(f"⚠ Could not refresh YouTube Analytics token: {e}")
                return None

        if not creds or not creds.valid:
            logger.info(
                "ℹ YouTube Analytics not authorized yet - impressions/AVD/retention will be "
                "skipped. Run once interactively: python -m agents.analytics_feedback setup"
            )
            return None

        return creds

    @property
    def available(self) -> bool:
        return self.analytics is not None

    def get_video_analytics(self, video_id: str, start_date: str, end_date: str) -> Optional[Dict]:
        """
        views/estimatedMinutesWatched/averageViewDuration/averageViewPercentage/
        subscribersGained/likes/comments/shares/videoThumbnailImpressions/
        videoThumbnailImpressionsClickRate for one video over [start_date, end_date].
        (videoThumbnailImpressions* are the current metric names as of the
        Jan 2026 Analytics API update - confirmed via docs, not guessed.)
        """
        if not self.available:
            return None
        try:
            response = self.analytics.reports().query(
                ids='channel==MINE',
                startDate=start_date,
                endDate=end_date,
                metrics='views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,'
                        'subscribersGained,likes,comments,shares,videoThumbnailImpressions,'
                        'videoThumbnailImpressionsClickRate',
                dimensions='video',
                filters=f'video=={video_id}'
            ).execute()

            rows = response.get('rows', [])
            if not rows:
                return None

            headers = [h['name'] for h in response.get('columnHeaders', [])]
            return dict(zip(headers, rows[0]))
        except Exception as e:
            logger.warning(f"⚠ Could not fetch analytics for {video_id}: {e}")
            return None

    def get_retention_curve(self, video_id: str, start_date: str, end_date: str) -> Optional[Dict]:
        """Retention at 25/50/75% marks, sampled from the 100-point elapsedVideoTimeRatio curve."""
        if not self.available:
            return None
        try:
            response = self.analytics.reports().query(
                ids='channel==MINE',
                startDate=start_date,
                endDate=end_date,
                metrics='audienceWatchRatio',
                dimensions='elapsedVideoTimeRatio',
                filters=f'video=={video_id}',
                maxResults=200
            ).execute()

            rows = response.get('rows', [])
            if not rows:
                return None

            curve = {round(r[0], 2): r[1] for r in rows}

            def closest(target):
                nearest = min(curve.keys(), key=lambda k: abs(k - target))
                return curve[nearest]

            return {
                'retention_25pct': closest(0.25),
                'retention_50pct': closest(0.50),
                'retention_75pct': closest(0.75)
            }
        except Exception as e:
            logger.warning(f"⚠ Could not fetch retention curve for {video_id}: {e}")
            return None


class PerformanceLogger:
    """Writes analytics/performance_log.csv - one row per (short, check mark)."""

    FIELDS = [
        'logged_at', 'youtube_id', 'title', 'topic', 'mark', 'views', 'likes',
        'comments', 'shares', 'subscribers_gained', 'estimated_minutes_watched',
        'average_view_duration_sec', 'average_view_percentage',
        'thumbnail_impressions', 'thumbnail_ctr', 'retention_25pct',
        'retention_50pct', 'retention_75pct', 'viral_score'
    ]

    def __init__(self, log_path: str = './analytics/performance_log.csv'):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_entry(self, entry: Dict) -> bool:
        try:
            file_exists = self.log_path.exists()
            with open(self.log_path, 'a', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDS, extrasaction='ignore')
                if not file_exists:
                    writer.writeheader()
                row = {k: entry.get(k, '') for k in self.FIELDS}
                row['logged_at'] = datetime.now().isoformat()
                writer.writerow(row)
            return True
        except Exception as e:
            logger.error(f"❌ Failed to write performance log entry: {e}")
            return False

    def load_history(self, youtube_id: str) -> List[Dict]:
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, 'r', newline='') as f:
                reader = csv.DictReader(f)
                return [row for row in reader if row.get('youtube_id') == youtube_id]
        except Exception as e:
            logger.warning(f"⚠ Could not read performance history: {e}")
            return []


class SpikeDetector:
    """
    Flags a short as spiking if its view velocity since the last check is
    >= SPIKE_MULTIPLIER times its own average velocity since publish.
    Needs at least one PRIOR logged entry for the same short to have
    anything to compare against - correctly inert (returns None, no crash)
    on a short's very first check.
    """

    def __init__(self, perf_logger: PerformanceLogger = None):
        self.perf_logger = perf_logger or PerformanceLogger()

    def check_spike(self, youtube_id: str, current_views: int, published_at: datetime) -> Optional[Dict]:
        history = self.perf_logger.load_history(youtube_id)
        if not history:
            return None

        try:
            prev = history[-1]
            prev_views = int(prev.get('views') or 0)
            prev_time = datetime.fromisoformat(prev['logged_at'])
        except (ValueError, TypeError, KeyError):
            return None

        hours_since_prev = max((datetime.now() - prev_time).total_seconds() / 3600, 0.01)
        recent_velocity = (current_views - prev_views) / hours_since_prev

        hours_since_publish = max((datetime.now() - published_at).total_seconds() / 3600, 0.01)
        overall_velocity = current_views / hours_since_publish

        if overall_velocity <= 0 or recent_velocity <= 0:
            return None

        if recent_velocity >= SPIKE_MULTIPLIER * overall_velocity:
            return {
                'youtube_id': youtube_id,
                'recent_velocity_per_hour': round(recent_velocity, 1),
                'overall_velocity_per_hour': round(overall_velocity, 1),
                'multiplier': round(recent_velocity / overall_velocity, 1)
            }
        return None


class PromptAutoUpdater:
    """
    Self-updates prompt files when there's high confidence a pattern is
    real: a hook with 3+ data points, a proven-winner performance margin,
    and hook-style diversity maintained (3+ active styles, so acting on
    one early signal doesn't collapse the library into repeating a single
    style). Every update is its own git commit for rollback capability.
    """

    def __init__(self, repo_dir: str = '.'):
        self.repo_dir = repo_dir

    def check_confidence(self, hook_library: HookLibrary) -> Dict:
        top_performers = hook_library.get_top_performers()
        diversity = hook_library.ensure_diversity()

        qualifying = [h for h in top_performers if h.get('usage_count', 0) >= MIN_DATA_POINTS]

        if not qualifying:
            return {'confident': False, 'reason': 'no hook has enough usage data yet (need 3+ uses)'}
        if not diversity.get('diversity_ok'):
            return {'confident': False, 'reason': f"only {diversity.get('active_styles', 0)} active hook style(s), need 3+"}

        best = qualifying[0]
        margin = (best.get('ctr', 0) - HookLibrary.PROVEN_WINNER_CTR) / max(HookLibrary.PROVEN_WINNER_CTR, 0.001)
        if margin < MIN_PERFORMANCE_MARGIN:
            return {'confident': False, 'reason': f'margin {margin:.1%} below {MIN_PERFORMANCE_MARGIN:.0%} threshold'}

        return {'confident': True, 'hook': best}

    def update_prompt_with_hook(self, prompt_path: str, hook_text: str, style: str) -> bool:
        """Append a proven-winner example to a prompt file and commit it."""
        try:
            path = Path(prompt_path)
            if not path.exists():
                logger.warning(f"⚠ Prompt file not found: {prompt_path}")
                return False

            addition = (
                f"\n\n# Auto-added proven winner ({datetime.now().strftime('%Y-%m-%d')}, style={style}):\n"
                f"# \"{hook_text}\"\n"
            )
            with open(path, 'a') as f:
                f.write(addition)

            subprocess.run(['git', 'add', str(path)], cwd=self.repo_dir, check=True, capture_output=True)
            subprocess.run(
                ['git', 'commit', '-m',
                 f"Auto-update {path.name}: add proven-winner hook example\n\n"
                 f"Style: {style}\nAuto-committed by Analytics & Feedback agent for rollback capability."],
                cwd=self.repo_dir, check=True, capture_output=True
            )
            logger.info(f"✓ Prompt auto-updated and committed: {path.name}")
            return True
        except subprocess.CalledProcessError as e:
            logger.warning(f"⚠ Prompt auto-update git commit failed (maybe nothing new to commit): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Prompt auto-update failed: {e}")
            return False


class AnalyticsFeedbackAgent:
    """Main orchestrator - one daily pass over every short due for a check."""

    def __init__(self, data_dir: str = './data'):
        self.data_dir = data_dir
        db_path = os.path.join(data_dir, 'chaos_merchant.db')
        self.hook_library = HookLibrary(db_path)
        self.channel_memory = ChannelMemory(db_path)
        self.stats_fetcher = YouTubeStatsFetcher()
        self.analytics_fetcher = YouTubeAnalyticsFetcher()
        self.perf_logger = PerformanceLogger()
        self.spike_detector = SpikeDetector(self.perf_logger)
        self.prompt_updater = PromptAutoUpdater()

    def run_daily_check(self) -> Dict:
        logger.info("=" * 70)
        logger.info("📊 ANALYTICS & FEEDBACK - Daily Check")
        logger.info("=" * 70)

        checked = []
        spikes = []

        for mark, days_ago in CHECK_MARKS.items():
            due = self.channel_memory.get_shorts_due_for_check(days_ago, mark=mark)
            if not due:
                logger.info(f"ℹ No shorts due for {mark} check yet")
                continue

            for short in due:
                result = self._check_one_short(short, mark)
                if result:
                    checked.append(result)
                    if result.get('spike'):
                        spikes.append(result['spike'])

        if not checked:
            logger.info("ℹ No shorts had data to check this run (fresh channel, or nothing newly due)")
            return {'status': 'no_data', 'checked': [], 'spikes': [], 'timestamp': datetime.now().isoformat()}

        confidence = self.prompt_updater.check_confidence(self.hook_library)
        prompt_updated = False
        if confidence.get('confident'):
            hook = confidence['hook']
            prompt_updated = self.prompt_updater.update_prompt_with_hook(
                './prompts/script_generation.txt', hook['text'], hook['style']
            )
        else:
            logger.info(f"ℹ Prompt auto-update skipped: {confidence.get('reason')}")

        milestone_info = self._check_subscriber_milestones()

        logger.info(f"\n✓ Analytics check complete: {len(checked)} shorts checked, {len(spikes)} spike(s) detected")
        logger.info("=" * 70)

        return {
            'status': 'success',
            'checked': checked,
            'spikes': spikes,
            'prompt_updated': prompt_updated,
            'milestone_info': milestone_info,
            'timestamp': datetime.now().isoformat()
        }

    def _check_one_short(self, short: Dict, mark: str) -> Optional[Dict]:
        youtube_id = short['youtube_id']
        stats = self.stats_fetcher.get_video_stats(youtube_id)
        if not stats:
            logger.warning(f"⚠ Could not fetch stats for {youtube_id}, skipping this check")
            return None

        try:
            published_at = datetime.strptime(str(short['publish_date']), '%Y-%m-%d')
        except (ValueError, TypeError):
            published_at = datetime.now()

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = str(short['publish_date'])
        analytics_data = self.analytics_fetcher.get_video_analytics(youtube_id, start_date, end_date)
        retention_data = self.analytics_fetcher.get_retention_curve(youtube_id, start_date, end_date)

        views = stats['views']
        ctr = float(analytics_data.get('videoThumbnailImpressionsClickRate', 0) or 0) if analytics_data else 0.0
        avg_pct = float(analytics_data.get('averageViewPercentage', 0) or 0) / 100 if analytics_data else 0.0
        retention = avg_pct or ((retention_data or {}).get('retention_50pct') or 0.0)

        self.channel_memory.update_performance(youtube_id, views, ctr, retention)
        self.channel_memory.mark_checked(short['id'], mark)

        # Real performance data into the Hook Library - distinct from the
        # placeholder log_hook_production() call already made at
        # production time (core/pipeline.py), which never touches ctr/
        # retention/status. This is the real update those placeholder rows
        # were waiting for.
        if short.get('hook_text'):
            hook_id = self.hook_library.get_or_create_hook(short['hook_text'], style='opening')
            if hook_id:
                self.hook_library.record_usage(hook_id, youtube_id, short['title'], ctr, retention)

        entry = {
            'youtube_id': youtube_id, 'title': short['title'], 'topic': short.get('topic', ''),
            'mark': mark, 'views': views, 'likes': stats['likes'], 'comments': stats['comments'],
            'viral_score': round(views * max(ctr, 0.01) * max(retention, 0.01), 2)
        }
        if analytics_data:
            entry.update({
                'shares': analytics_data.get('shares', ''),
                'subscribers_gained': analytics_data.get('subscribersGained', ''),
                'estimated_minutes_watched': analytics_data.get('estimatedMinutesWatched', ''),
                'average_view_duration_sec': analytics_data.get('averageViewDuration', ''),
                'average_view_percentage': analytics_data.get('averageViewPercentage', ''),
                'thumbnail_impressions': analytics_data.get('videoThumbnailImpressions', ''),
                'thumbnail_ctr': analytics_data.get('videoThumbnailImpressionsClickRate', '')
            })
        if retention_data:
            entry.update(retention_data)

        self.perf_logger.log_entry(entry)

        spike = self.spike_detector.check_spike(youtube_id, views, published_at)
        if spike:
            send_notification(
                "🚀 Short is spiking!",
                f"{short['title'][:60]} is getting {spike['multiplier']}x normal views"
            )
            logger.warning(f"🚀 SPIKE DETECTED: {short['title']} ({spike['multiplier']}x normal velocity)")

        return {'youtube_id': youtube_id, 'title': short['title'], 'mark': mark, 'views': views, 'spike': spike}

    def _check_subscriber_milestones(self) -> Optional[Dict]:
        stats = self.stats_fetcher.get_channel_stats()
        if not stats:
            return None

        subs = stats['subscriber_count']
        milestones = [100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000]
        next_milestone = next((m for m in milestones if m > subs), None)

        # YouTube Partner Program: 1,000 subscribers + (10M Shorts views in
        # 90 days OR 4,000 long-form watch hours in 12 months). This checks
        # only the subscriber half as a cheap proxy from a public snapshot -
        # the real 90-day Shorts view velocity requires the Analytics API's
        # date-ranged queries, not implemented here.
        ypp_subscriber_threshold_met = subs >= 1000
        estimated_monthly_revenue = None
        revenue_note = None
        if ypp_subscriber_threshold_met:
            # Extremely rough placeholder: commonly-cited public Shorts RPM
            # range is roughly $0.01-$0.07 per 1000 views; using $0.04 as a
            # rough midpoint. This is NOT real revenue data.
            estimated_monthly_revenue = round(stats['view_count'] / 1000 * 0.04, 2)
            revenue_note = 'Rough placeholder estimate ($0.04/1000 total views) - not real AdSense/YPP revenue data'

        return {
            'subscriber_count': subs,
            'next_milestone': next_milestone,
            'ypp_subscriber_threshold_met': ypp_subscriber_threshold_met,
            'estimated_monthly_revenue_usd': estimated_monthly_revenue,
            'revenue_estimate_note': revenue_note
        }


def run_analytics_feedback() -> Dict:
    """Main entry point, scheduled daily 9am."""
    try:
        agent = AnalyticsFeedbackAgent()
        return agent.run_daily_check()
    except Exception as e:
        logger.error(f"❌ Analytics & Feedback check failed: {e}")
        return {'status': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        if not OAUTH_AVAILABLE:
            print("google-auth-oauthlib not installed: pip install google-auth-oauthlib")
            sys.exit(1)
        client_secrets_path = os.getenv('YOUTUBE_OAUTH_CLIENT_SECRETS', './config/youtube_client_secrets.json')
        if not os.path.exists(client_secrets_path):
            print(f"Missing OAuth client secrets file: {client_secrets_path}")
            print("Download it from Google Cloud Console (APIs & Services > Credentials) and set")
            print("YOUTUBE_OAUTH_CLIENT_SECRETS in .env, or place it at the default path above.")
            sys.exit(1)

        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, ANALYTICS_SCOPES)
        creds = flow.run_local_server(port=0)
        token_path = os.getenv('YOUTUBE_ANALYTICS_TOKEN_PATH', './data/youtube_analytics_token.json')
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())
        print(f"✓ YouTube Analytics authorized. Token saved: {token_path}")
    else:
        result = run_analytics_feedback()
        print(json.dumps(result, indent=2, default=str))
