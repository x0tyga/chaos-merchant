"""
Clip Sourcing Agent - autonomous discovery and download of source footage
Finds already-viral/trending video clips on Reddit and YouTube, runs them
through a three-signal copyright/quality gate, and downloads accepted
clips directly into INPUT_DIR - the existing agents/watcher.py -> pipeline
flow then picks them up completely unchanged, so this is an automated
hand dropping files into input/ instead of a human operator.

Twitter/X is deliberately NOT sourced here - no existing credentials or
library in this codebase, and X's API for reading/searching tweets now
requires a paid tier. Reddit + YouTube only for this phase.
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import praw
    PRAW_AVAILABLE = True
except ImportError:
    PRAW_AVAILABLE = False
    logger.warning("praw not available - Reddit sourcing will be skipped (pip install praw)")

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not available - YouTube sourcing and all real downloads will be skipped (pip install yt-dlp)")

from core.memory import SourceRegistry
from core.cost_tracker import log_download_usage
from core.notifications import send_notification

# ---- Config files (auto-created with sane defaults on first run - same
# pattern as config/competitors.json / config/gaming_calendar.json) ----
SUBREDDITS_CONFIG_PATH = Path('./config/source_subreddits.json')
CHANNELS_CONFIG_PATH = Path('./config/source_channels.json')
BLOCKLIST_CONFIG_PATH = Path('./config/source_blocklist.json')
SCHEDULE_CONFIG_PATH = Path('./config/source_schedule.json')

DEFAULT_SOURCING_RUN_TIMES = ['07:30', '18:00']

MAX_LOGGED_ALERTS = 200


def _sourcing_alerts_path(data_dir: str = None) -> Path:
    """
    Rolling alert log the dashboard's Schedule tab reads (dashboard/data.py's
    get_sourcing_alerts()) - a real run that downloads nothing is exactly
    the silent failure mode that leaves the posting queue empty with no
    visible cause, so it gets logged here AND desktop-notified, never just
    a log line. Resolved from DATA_DIR (like every other data/ file in
    this codebase - cost_log.json, notification_log.json, chaos_merchant.db)
    rather than a hardcoded './data/...' constant, so a custom DATA_DIR
    (see .env.example) is honored instead of silently writing to the
    wrong place - the exact bug class caught in SourceRegistry() above via
    tests/test_clip_sourcing_integration.py.
    """
    return Path(data_dir or os.getenv('DATA_DIR', './data')) / 'sourcing_alerts.json'

DEFAULT_SUBREDDITS = ['GTA6', 'gaming', 'sports', 'PublicFreakout', 'nextfuckinglevel']

# Video-hosting domains a Reddit-linked URL might point at, beyond native
# v.redd.it - used only to decide whether a submission is worth probing at
# all, not to guarantee it's actually downloadable (yt-dlp itself is the
# real authority on that, checked at probe time).
_VIDEO_HOSTS = ('v.redd.it', 'youtube.com', 'youtu.be', 'streamable.com', 'gfycat.com', 'redgifs.com')


def _load_subreddits() -> List[str]:
    if not SUBREDDITS_CONFIG_PATH.exists():
        SUBREDDITS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        default = {
            '_note': (
                "Subreddits scanned for actual VIDEO submissions to source as pipeline "
                "input - deliberately separate from agents/trend_intelligence.py's "
                "REDDIT_SUBREDDITS, which is for text/title trend signal, not video "
                "sourcing. Edit this list directly to add/remove sources."
            ),
            'subreddits': DEFAULT_SUBREDDITS
        }
        with open(SUBREDDITS_CONFIG_PATH, 'w') as f:
            json.dump(default, f, indent=2)
        logger.info(f"✓ Created default source subreddits config: {SUBREDDITS_CONFIG_PATH}")
        return DEFAULT_SUBREDDITS
    try:
        with open(SUBREDDITS_CONFIG_PATH) as f:
            return json.load(f).get('subreddits', DEFAULT_SUBREDDITS)
    except Exception as e:
        logger.warning(f"⚠ Failed to load source subreddits config, using defaults: {e}")
        return DEFAULT_SUBREDDITS


def _load_channels() -> List[str]:
    if not CHANNELS_CONFIG_PATH.exists():
        CHANNELS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        default = {
            '_note': (
                'STARTS EMPTY ON PURPOSE - this is not a bug. Curated YouTube channel '
                'URLs to pull recent uploads from for sourcing (e.g. '
                '"https://www.youtube.com/@SomeChannel"). Until you add at least one '
                'channel here, YouTube\'s curated-channel sourcing mode produces zero '
                'candidates every run - trending/search-query sourcing (fed from the '
                'daily trend intelligence brief) still runs independently and is not '
                'affected. Add channels here directly, or via the dashboard\'s Sources '
                'tab.'
            ),
            'channels': []
        }
        with open(CHANNELS_CONFIG_PATH, 'w') as f:
            json.dump(default, f, indent=2)
        logger.info(f"✓ Created default source channels config (empty): {CHANNELS_CONFIG_PATH}")
        return []
    try:
        with open(CHANNELS_CONFIG_PATH) as f:
            return json.load(f).get('channels', [])
    except Exception as e:
        logger.warning(f"⚠ Failed to load source channels config: {e}")
        return []


def add_source_channel(channel_url: str) -> bool:
    """
    Appends a curated channel URL to config/source_channels.json - the
    dashboard Sources tab's whitelist population UI, replacing "edit the
    JSON file by hand" as the only way to fill in what starts empty on
    purpose. Returns False (no-op, not an error) if the URL is already
    present or blank.
    """
    channel_url = (channel_url or '').strip()
    if not channel_url:
        return False

    channels = _load_channels()
    if channel_url in channels:
        logger.info(f"ℹ Channel already in source_channels.json: {channel_url}")
        return False

    channels.append(channel_url)
    CHANNELS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if CHANNELS_CONFIG_PATH.exists():
        try:
            with open(CHANNELS_CONFIG_PATH) as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    raw['channels'] = channels
    with open(CHANNELS_CONFIG_PATH, 'w') as f:
        json.dump(raw, f, indent=2)
    logger.info(f"✓ Added curated source channel: {channel_url}")
    return True


def remove_source_channel(channel_url: str) -> bool:
    """Removes a channel URL from config/source_channels.json. Returns False (no-op) if it wasn't present."""
    channels = _load_channels()
    if channel_url not in channels:
        return False

    channels = [c for c in channels if c != channel_url]
    raw = {}
    if CHANNELS_CONFIG_PATH.exists():
        try:
            with open(CHANNELS_CONFIG_PATH) as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    raw['channels'] = channels
    with open(CHANNELS_CONFIG_PATH, 'w') as f:
        json.dump(raw, f, indent=2)
    logger.info(f"✓ Removed curated source channel: {channel_url}")
    return True


def _load_sourcing_schedule() -> List[str]:
    """
    'HH:MM' times the clip_sourcing job runs at, read by BOTH main.py (to
    register the actual scheduled jobs) and ClipSourcingAgent itself (to
    derive how many runs/day for content-calendar volume guidance) - a
    single config file so the two can never drift out of sync the way a
    hardcoded count in one place and a hardcoded schedule in another would.
    """
    if not SCHEDULE_CONFIG_PATH.exists():
        SCHEDULE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        default = {
            '_note': (
                "What time(s) of day agents/clip_sourcing.py's scheduled job runs - "
                "read by both main.py (registers one scheduled job per entry here) "
                "and ClipSourcingAgent itself (derives runs-per-day for content "
                "calendar volume guidance, so the two never drift apart). Edit "
                "directly, or via the dashboard's Sources tab. Requires restarting "
                "main.py to take effect (jobs are registered once at startup)."
            ),
            'run_times': DEFAULT_SOURCING_RUN_TIMES
        }
        with open(SCHEDULE_CONFIG_PATH, 'w') as f:
            json.dump(default, f, indent=2)
        logger.info(f"✓ Created default sourcing schedule config: {SCHEDULE_CONFIG_PATH}")
        return list(DEFAULT_SOURCING_RUN_TIMES)
    try:
        with open(SCHEDULE_CONFIG_PATH) as f:
            times = json.load(f).get('run_times', DEFAULT_SOURCING_RUN_TIMES)
        return times or list(DEFAULT_SOURCING_RUN_TIMES)
    except Exception as e:
        logger.warning(f"⚠ Failed to load sourcing schedule config, using defaults: {e}")
        return list(DEFAULT_SOURCING_RUN_TIMES)


def add_sourcing_run_time(time_str: str) -> bool:
    """Adds an 'HH:MM' run time to config/source_schedule.json. Returns False (no-op) if invalid, blank, or already present."""
    time_str = (time_str or '').strip()
    if not time_str or len(time_str) != 5 or time_str[2] != ':' or not (time_str[:2].isdigit() and time_str[3:].isdigit()):
        logger.warning(f"⚠ Rejected invalid sourcing run time (expected HH:MM): {time_str!r}")
        return False

    times = _load_sourcing_schedule()
    if time_str in times:
        return False
    times.append(time_str)
    times.sort()
    _write_sourcing_schedule(times)
    logger.info(f"✓ Added sourcing run time: {time_str}")
    return True


def remove_sourcing_run_time(time_str: str) -> bool:
    """Removes an 'HH:MM' run time from config/source_schedule.json. Returns False (no-op) if not present."""
    times = _load_sourcing_schedule()
    if time_str not in times:
        return False
    times = [t for t in times if t != time_str]
    _write_sourcing_schedule(times)
    logger.info(f"✓ Removed sourcing run time: {time_str}")
    return True


def _write_sourcing_schedule(times: List[str]) -> None:
    SCHEDULE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = {}
    if SCHEDULE_CONFIG_PATH.exists():
        try:
            with open(SCHEDULE_CONFIG_PATH) as f:
                raw = json.load(f)
        except Exception:
            raw = {}
    raw['run_times'] = times
    with open(SCHEDULE_CONFIG_PATH, 'w') as f:
        json.dump(raw, f, indent=2)


def _load_blocklist() -> List[str]:
    if not BLOCKLIST_CONFIG_PATH.exists():
        BLOCKLIST_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        default = {
            '_note': (
                'Uploader usernames / YouTube channel names known to issue takedowns '
                'aggressively (official publishers, major sports leagues, etc.) - clips '
                'from these are never sourced regardless of popularity. Empty by default - '
                'add entries as you learn which sources are actually risky.'
            ),
            'blocked_uploaders': []
        }
        with open(BLOCKLIST_CONFIG_PATH, 'w') as f:
            json.dump(default, f, indent=2)
        logger.info(f"✓ Created default source blocklist config (empty): {BLOCKLIST_CONFIG_PATH}")
        return []
    try:
        with open(BLOCKLIST_CONFIG_PATH) as f:
            return [u.lower() for u in json.load(f).get('blocked_uploaders', [])]
    except Exception as e:
        logger.warning(f"⚠ Failed to load source blocklist config: {e}")
        return []


def _load_trending_search_queries(limit: int = 3) -> List[str]:
    """
    Feeds YouTube search candidates from the daily trend intelligence brief
    (the same file agents/trend_intelligence.py already writes at 7am)
    rather than a separate hardcoded query list - keeps sourcing acting on
    same-day-fresh trends without inventing a new trend-scoring system.
    """
    brief_path = Path('./data/trend_intelligence_latest.json')
    default_queries = ['gta 6 leak', 'viral gaming moment']
    if not brief_path.exists():
        return default_queries
    try:
        with open(brief_path) as f:
            brief = json.load(f)
        trends = [t['trend'] for t in brief.get('brief', {}).get('top_trends', [])[:limit] if t.get('trend')]
        return trends or default_queries
    except Exception as e:
        logger.warning(f"⚠ Could not load trend intelligence brief for sourcing queries: {e}")
        return default_queries


class RedditClipFetcher:
    """Discovers video submissions from configured subreddits via PRAW - listing/discovery
    only, reusing the same praw.Reddit(...) credential pattern already live in
    agents/trend_intelligence.py's TrendFetcher.fetch_reddit_trends()."""

    def fetch_candidates(self, limit_per_subreddit: int = 15) -> List[Dict]:
        if not PRAW_AVAILABLE:
            return []

        client_id = os.getenv('REDDIT_CLIENT_ID', '')
        client_secret = os.getenv('REDDIT_CLIENT_SECRET', '')
        if not client_id or not client_secret:
            # Without this, an unconfigured Reddit source doesn't fail
            # cleanly - PRAW still constructs a client with empty strings,
            # then every subreddit in the list makes a REAL (failing) OAuth
            # call to Reddit, one at a time, logging a confusing per-
            # subreddit warning each run - noise for a source that was
            # never going to work, on every single sourcing run, forever.
            # One clear info line, checked before any network call, instead.
            logger.info("ℹ Reddit sourcing skipped - REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET not configured (YouTube sourcing runs independently)")
            return []

        try:
            reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=os.getenv('REDDIT_USER_AGENT', 'chaos-merchant/1.0')
            )
        except Exception as e:
            logger.warning(f"⚠ Reddit client init failed: {e}")
            return []

        candidates = []
        for name in _load_subreddits():
            try:
                subreddit = reddit.subreddit(name)
                found_here = 0
                for submission in subreddit.hot(limit=limit_per_subreddit):
                    if not (getattr(submission, 'is_video', False) or self._looks_like_video_url(submission.url)):
                        continue
                    candidates.append({
                        'source_url': f"https://www.reddit.com{submission.permalink}",
                        'platform': 'reddit',
                        'title': submission.title,
                        'author': str(submission.author) if submission.author else 'unknown',
                        'popularity_signal': submission.score,
                    })
                    found_here += 1
                logger.info(f"✓ r/{name}: {found_here} video submission(s) among {limit_per_subreddit} hot posts")
            except Exception as e:
                logger.warning(f"⚠ Could not scan r/{name}: {e}")
                continue

        logger.info(f"✓ Reddit sourcing: {len(candidates)} total candidate(s) across {len(_load_subreddits())} subreddit(s)")
        return candidates

    @staticmethod
    def _looks_like_video_url(url: str) -> bool:
        return any(host in url for host in _VIDEO_HOSTS)


class YouTubeClipFetcher:
    """Discovers candidate videos via yt-dlp - both curated channels and trending/search
    queries, metadata-only (extract_flat/skip_download) - same cheap discovery pattern
    already established in agents/thumbnail_research.py's TrendingThumbnailFetcher."""

    def fetch_search_candidates(self, queries: List[str], limit_per_query: int = 15) -> List[Dict]:
        if not YTDLP_AVAILABLE or not queries:
            return []

        candidates = []
        ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': 'in_playlist'}
        for query in queries:
            search_target = f"ytsearch{limit_per_query}:{query}"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(search_target, download=False)
            except Exception as e:
                logger.warning(f"⚠ yt-dlp search failed for '{query}': {e}")
                continue

            entries = (info or {}).get('entries', []) or []
            for entry in entries:
                if not entry:
                    continue
                candidates.append({
                    'source_url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}",
                    'platform': 'youtube_search',
                    'title': entry.get('title', ''),
                    'author': entry.get('channel') or entry.get('uploader', ''),
                    'popularity_signal': entry.get('view_count') or 0,
                })
            logger.info(f"✓ YouTube search '{query}': {len(entries)} candidate(s)")

        return candidates

    def fetch_channel_candidates(self, channel_urls: List[str], limit_per_channel: int = 10) -> List[Dict]:
        if not YTDLP_AVAILABLE or not channel_urls:
            return []

        candidates = []
        ydl_opts = {
            'quiet': True, 'skip_download': True, 'extract_flat': 'in_playlist',
            'playlistend': limit_per_channel
        }
        for channel_url in channel_urls:
            videos_url = channel_url.rstrip('/') + '/videos'
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(videos_url, download=False)
            except Exception as e:
                logger.warning(f"⚠ Could not list uploads for channel {channel_url}: {e}")
                continue

            entries = (info or {}).get('entries', []) or []
            for entry in entries:
                if not entry:
                    continue
                candidates.append({
                    'source_url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}",
                    'platform': 'youtube_channel',
                    'title': entry.get('title', ''),
                    'author': entry.get('channel') or entry.get('uploader', channel_url),
                    'popularity_signal': entry.get('view_count') or 0,
                })
            logger.info(f"✓ Channel {channel_url}: {len(entries)} recent upload(s)")

        return candidates


class YtdlpProbe:
    """Metadata-only probe (skip_download=True) for a single candidate URL, run BEFORE any
    real download - shared by both Reddit and YouTube candidates so there's one download
    mechanism and one metadata source of truth, regardless of which platform discovered it."""

    @staticmethod
    def probe(source_url: str) -> Optional[Dict]:
        if not YTDLP_AVAILABLE:
            return None
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
                info = ydl.extract_info(source_url, download=False)
        except Exception as e:
            logger.warning(f"⚠ Probe failed for {source_url}: {e}")
            return None

        if not info:
            return None
        return {
            'duration_seconds': info.get('duration'),
            'height': info.get('height'),
            'width': info.get('width'),
            'uploader': info.get('uploader') or info.get('channel'),
            'view_count': info.get('view_count'),
        }


class CopyrightRiskGate:
    """
    The only safeguard against a DMCA takedown/channel strike, since
    sourced batches publish fully automatically with no human review
    (see HANDOFF.md's format-pivot/sourcing plan). All three signals must
    pass, checked from metadata alone, before any real download happens:

    1. Minimum popularity signal - the core of the "already widely
       reshared" fair-use argument; below threshold is rejected regardless
       of content quality.
    2. Max source clip length - keeps downloads closer to a transformative
       excerpt than a full re-upload of someone's complete video.
    3. Known-risk uploader/channel blocklist - checked against both the
       platform listing's author field AND the probe's own uploader field
       (yt-dlp sometimes resolves a canonical uploader name PRAW's listing
       doesn't have), so a blocklisted source can't slip through under a
       display-name mismatch.
    """

    def __init__(self):
        self.min_reddit_score = int(os.getenv('MIN_REDDIT_SCORE', 500))
        self.min_youtube_views = int(os.getenv('MIN_YOUTUBE_VIEWS', 50000))
        self.max_source_clip_seconds = int(os.getenv('MAX_SOURCE_CLIP_SECONDS', 180))
        self.min_source_height = int(os.getenv('MIN_SOURCE_RESOLUTION_HEIGHT', 480))
        self.blocklist = _load_blocklist()

    def evaluate(self, candidate: Dict, probe: Optional[Dict]) -> Tuple[bool, str]:
        """Returns (passes, reason) - reason is '' if it passes, else the specific failure."""
        author = (candidate.get('author') or '').lower()
        if author and author in self.blocklist:
            return False, f"uploader '{candidate.get('author')}' is on the known-risk blocklist"

        popularity = candidate.get('popularity_signal', 0) or 0
        if candidate['platform'] == 'reddit':
            if popularity < self.min_reddit_score:
                return False, f"Reddit score {popularity} below minimum {self.min_reddit_score}"
        else:
            if popularity < self.min_youtube_views:
                return False, f"YouTube view count {popularity} below minimum {self.min_youtube_views}"

        if probe is None:
            return False, "metadata probe failed - could not verify length/resolution before download"

        duration = probe.get('duration_seconds')
        if duration is None:
            return False, "probe returned no duration - cannot verify against max source clip length"
        if duration > self.max_source_clip_seconds:
            return False, f"source duration {duration:.0f}s exceeds max {self.max_source_clip_seconds}s"

        height = probe.get('height')
        if height is not None and height < self.min_source_height:
            return False, f"source resolution {height}p below minimum {self.min_source_height}p"

        probed_uploader = (probe.get('uploader') or '').lower()
        if probed_uploader and probed_uploader in self.blocklist:
            return False, f"probed uploader '{probe.get('uploader')}' is on the known-risk blocklist"

        return True, ""


class YtdlpDownloader:
    """Real video download - only ever called after CopyrightRiskGate passes. Caps
    resolution to keep bandwidth/storage sane; nothing in this codebase downloaded real
    video via yt-dlp before this (agents/thumbnail_research.py only ever used
    skip_download=True metadata scraping)."""

    @staticmethod
    def download(source_url: str, dest_path: Path) -> bool:
        if not YTDLP_AVAILABLE:
            return False

        max_height = int(os.getenv('SOURCING_MAX_DOWNLOAD_HEIGHT', 1080))
        ydl_opts = {
            'quiet': True,
            'format': f'bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best',
            'outtmpl': str(dest_path),
            'merge_output_format': 'mp4',
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([source_url])
            return dest_path.exists() and dest_path.stat().st_size > 0
        except Exception as e:
            logger.error(f"❌ Download failed for {source_url}: {e}")
            return False


class SourcingRateLimiter:
    """
    Per-run caps + a politeness delay between yt-dlp/PRAW calls. Deliberately
    NOT a persistent cross-run daily quota like core/scheduler.py's
    QuotaTracker (which is hardcoded to the YouTube Data API's 10,000/day
    quota model - reusing it as-is here would conflate two unrelated quota
    systems) - just enough to keep a single sourcing run from hammering
    Reddit/YouTube. A persistent daily volume cap belongs with the content
    calendar (a later component), which is about overall daily volume, not
    per-call rate limiting.
    """

    def __init__(self):
        self.max_downloads = int(os.getenv('SOURCING_MAX_DOWNLOADS_PER_RUN', 5))
        self.max_probes = int(os.getenv('SOURCING_MAX_PROBES_PER_RUN', 30))
        self.request_delay = float(os.getenv('SOURCING_REQUEST_DELAY_SECONDS', 2))
        self.downloads_done = 0
        self.probes_done = 0

    def can_probe(self) -> bool:
        return self.probes_done < self.max_probes

    def can_download(self) -> bool:
        return self.downloads_done < self.max_downloads

    def record_probe(self):
        self.probes_done += 1
        time.sleep(self.request_delay)

    def record_download(self):
        self.downloads_done += 1
        time.sleep(self.request_delay)


class ClipSourcingAgent:
    """Main orchestrator: discover candidates -> dedup -> gate -> download into INPUT_DIR."""

    def __init__(self, input_dir: str = None, data_dir: str = None):
        self.input_dir = Path(input_dir or os.getenv('INPUT_DIR', './input'))
        self.input_dir.mkdir(parents=True, exist_ok=True)
        # Honors DATA_DIR the same way every other memory-backed class in
        # this codebase does (ChannelMemory, HookLibrary, PostingQueue) -
        # previously hardcoded to SourceRegistry()'s './data/...' default
        # regardless of DATA_DIR, which on a deployment with a custom
        # DATA_DIR (see .env.example) would silently dedup against the
        # wrong database, defeating the "never download the same clip
        # twice" guarantee. Found via tests/test_clip_sourcing_integration.py.
        self.data_dir = data_dir or os.getenv('DATA_DIR', './data')
        self.registry = SourceRegistry(str(Path(self.data_dir) / 'chaos_merchant.db'))
        self.gate = CopyrightRiskGate()
        self.limiter = SourcingRateLimiter()
        self._apply_calendar_guidance()
        self.reddit_fetcher = RedditClipFetcher()
        self.youtube_fetcher = YouTubeClipFetcher()

    def _apply_calendar_guidance(self):
        """
        content_calendar.json's target_batches_per_day is soft volume
        guidance, layered ON TOP of (never instead of)
        SOURCING_MAX_DOWNLOADS_PER_RUN's hard rate-limiting ceiling from
        Component 2 - whichever cap is LOWER wins, so an aggressive
        calendar target can never bypass the rate limiter, but a
        conservative calendar target can still pull the effective cap
        down below the rate limiter's default.

        Runs-per-day is read from config/source_schedule.json (the same
        file main.py reads to register the actual jobs), NOT a hardcoded
        constant - so changing the sourcing schedule automatically keeps
        this guidance in sync instead of silently drifting apart from it.
        """
        try:
            from core.content_calendar import load_content_calendar
            scheduled_runs_per_day = max(1, len(_load_sourcing_schedule()))
            target_per_day = load_content_calendar().get('target_batches_per_day', 1)
            calendar_derived_cap = max(1, -(-int(target_per_day) // scheduled_runs_per_day))  # ceil division
            if calendar_derived_cap < self.limiter.max_downloads:
                logger.info(
                    f"ℹ Content calendar target ({target_per_day} batches/day over "
                    f"{scheduled_runs_per_day} scheduled runs) caps this run's "
                    f"downloads at {calendar_derived_cap} (below the "
                    f"SOURCING_MAX_DOWNLOADS_PER_RUN ceiling of {self.limiter.max_downloads})"
                )
                self.limiter.max_downloads = calendar_derived_cap
        except Exception as e:
            logger.warning(f"⚠ Could not apply content calendar volume guidance, using rate-limiter default: {e}")

    def run(self, dry_run: bool = False, youtube_search_queries: List[str] = None) -> Dict:
        logger.info("=" * 70)
        logger.info(f"🔎 CLIP SOURCING{' (DRY RUN - nothing will be downloaded)' if dry_run else ''}")
        logger.info("=" * 70)

        channels = _load_channels()
        if not channels:
            logger.warning(
                "⚠ YouTube curated-channel sourcing is configured with ZERO channels - "
                "this starts empty on purpose (not a bug), but it means the curated-channel "
                "mode will contribute 0 candidates every run until you add at least one to "
                f"{CHANNELS_CONFIG_PATH} (or via the dashboard's Sources tab). "
                "Trending/search-query sourcing still runs independently below."
            )

        candidates = []
        candidates.extend(self.reddit_fetcher.fetch_candidates())
        candidates.extend(self.youtube_fetcher.fetch_channel_candidates(channels))
        candidates.extend(self.youtube_fetcher.fetch_search_candidates(youtube_search_queries or _load_trending_search_queries()))

        logger.info(f"✓ {len(candidates)} raw candidate(s) discovered across all sources")

        downloaded, rejected = [], []
        skipped_duplicate = 0

        for candidate in candidates:
            source_url = candidate['source_url']

            # Dedup check happens FIRST, before spending any yt-dlp probe
            # call - this is the actual guarantee against downloading the
            # same clip twice, independent of what's currently in the
            # input folder or whether the process has restarted since.
            if self.registry.is_known(source_url):
                skipped_duplicate += 1
                continue

            if not self.limiter.can_probe():
                logger.info("ℹ Probe cap reached for this run - remaining candidates skipped")
                break

            probe = YtdlpProbe.probe(source_url)
            self.limiter.record_probe()

            passes, reason = self.gate.evaluate(candidate, probe)
            if not passes:
                logger.info(f"⊗ Rejected: {candidate.get('title', source_url)[:60]!r} - {reason}")
                rejected.append({**candidate, 'rejection_reason': reason})
                self.registry.record_rejected(
                    source_url, candidate['platform'], candidate.get('popularity_signal', 0),
                    reason, title=candidate.get('title')
                )
                continue

            if dry_run:
                duration = (probe or {}).get('duration_seconds')
                logger.info(
                    f"✓ Would download: {candidate.get('title', source_url)[:60]!r} "
                    f"(duration {duration}s if known) - NOT downloaded (dry run)"
                )
                downloaded.append({**candidate, 'probe': probe, 'dry_run': True})
                continue

            if not self.limiter.can_download():
                logger.info("ℹ Download cap reached for this run - remaining candidates skipped")
                break

            file_path = self._build_dest_path(candidate)
            success = YtdlpDownloader.download(source_url, file_path)
            self.limiter.record_download()

            if success:
                # Tier 2 of the Quality Gate for Sourced Content: yt-dlp
                # reporting success only means the process exited cleanly -
                # it doesn't mean the file is a real, decodable video. Check
                # the ACTUAL downloaded bytes before this is ever allowed
                # into INPUT_DIR, so a corrupt/truncated download can't waste
                # a full pipeline run before failing somewhere downstream.
                validation = self._validate_downloaded_file(file_path, probe)
                if validation['status'] != 'pass':
                    reason = f"downloaded file failed post-download validation: {'; '.join(validation['errors'])}"
                    logger.error(f"❌ Rejected after download: {candidate.get('title', source_url)[:60]!r} - {reason}")
                    self._write_rejection_file(candidate, validation)
                    try:
                        file_path.unlink(missing_ok=True)
                    except OSError as e:
                        logger.warning(f"⚠ Could not remove invalid downloaded file {file_path}: {e}")
                    self.registry.record_rejected(
                        source_url, candidate['platform'], candidate.get('popularity_signal', 0),
                        reason, title=candidate.get('title')
                    )
                    rejected.append({**candidate, 'rejection_reason': reason})
                    continue

                logger.info(f"✓ Downloaded: {candidate.get('title', source_url)[:60]!r} -> {file_path.name}")
                self.registry.record_downloaded(
                    source_url, candidate['platform'], str(file_path),
                    candidate.get('popularity_signal', 0), (probe or {}).get('duration_seconds'),
                    title=candidate.get('title')
                )
                try:
                    bytes_downloaded = file_path.stat().st_size
                    log_download_usage(source_url, candidate['platform'], bytes_downloaded, data_dir=self.data_dir)
                except Exception as e:
                    logger.debug(f"Download cost logging skipped (non-fatal): {e}")
                downloaded.append({**candidate, 'file_path': str(file_path)})
            else:
                logger.error(f"❌ Download failed: {candidate.get('title', source_url)[:60]!r}")
                rejected.append({**candidate, 'rejection_reason': 'download failed'})
                self.registry.record_rejected(
                    source_url, candidate['platform'], candidate.get('popularity_signal', 0),
                    'download failed', title=candidate.get('title')
                )

        summary = {
            'status': 'success',
            'candidates_discovered': len(candidates),
            'duplicates_skipped': skipped_duplicate,
            'downloaded': len(downloaded),
            'rejected': len(rejected),
            'dry_run': dry_run,
            'timestamp': datetime.now().isoformat()
        }
        logger.info(
            f"✓ Sourcing complete: {summary['downloaded']} downloaded, {summary['rejected']} rejected, "
            f"{summary['duplicates_skipped']} duplicate(s) skipped, {summary['candidates_discovered']} discovered"
        )
        logger.info("=" * 70)

        if not dry_run and summary['downloaded'] == 0:
            self._log_and_notify_empty_run(summary, rejected)

        return summary

    def _log_and_notify_empty_run(self, summary: Dict, rejected: List[Dict]):
        """
        A real (non-dry-run) sourcing run that downloads ZERO clips means
        the input folder gets nothing new, which cascades all the way to
        an empty posting queue with no shorts to publish - and with no
        signal here, that would surface as silent nothing happening rather
        than a diagnosable condition. Never skipped silently: always both
        logged to SOURCING_ALERTS_PATH (dashboard's Schedule tab reads
        this) AND desktop-notified.
        """
        if summary['candidates_discovered'] == 0:
            reason = "no candidates discovered at all from Reddit or YouTube this run - check REDDIT_CLIENT_ID/SECRET, YOUTUBE curated channels/search queries, and network connectivity"
        elif summary['duplicates_skipped'] == summary['candidates_discovered']:
            reason = f"all {summary['candidates_discovered']} candidate(s) discovered were already-sourced duplicates - nothing new available from current sources right now"
        elif summary['rejected'] > 0:
            reason_counts = {}
            for r in rejected:
                key = r.get('rejection_reason', 'unknown')
                reason_counts[key] = reason_counts.get(key, 0) + 1
            top_reasons = sorted(reason_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
            reason = (
                f"{summary['candidates_discovered']} candidate(s) discovered, all {summary['rejected']} rejected by "
                f"the copyright/quality gate. Top reasons: " +
                "; ".join(f"{count}x {msg}" for msg, count in top_reasons)
            )
        else:
            reason = "no clips downloaded this run for an undetermined reason - check logs above"

        message = f"Clip sourcing downloaded 0 new clips this run. {reason}"
        logger.warning(f"⚠ {message}")

        alert_id = datetime.now().isoformat()  # unique per call (microsecond resolution) - doubles as the dismiss key
        alert = {
            'id': alert_id,
            'timestamp': alert_id,
            'candidates_discovered': summary['candidates_discovered'],
            'duplicates_skipped': summary['duplicates_skipped'],
            'rejected': summary['rejected'],
            'reason': reason,
            # Stays visible on the dashboard's Schedule tab until a human
            # dismisses it (dashboard/data.py's dismiss_sourcing_alert) -
            # NOT auto-cleared by time or by a later successful run, since
            # a later run downloading clips doesn't retroactively mean this
            # gap didn't happen.
            'dismissed': False,
        }
        alerts_path = _sourcing_alerts_path(self.data_dir)
        try:
            alerts_path.parent.mkdir(parents=True, exist_ok=True)
            alerts = []
            if alerts_path.exists():
                try:
                    with open(alerts_path) as f:
                        alerts = json.load(f)
                except Exception:
                    alerts = []
            alerts.append(alert)
            alerts = alerts[-MAX_LOGGED_ALERTS:]
            with open(alerts_path, 'w') as f:
                json.dump(alerts, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Failed to log sourcing alert to {alerts_path}: {e}")

        send_notification("⚠ Chaos Merchant: no new clips sourced", message)

    @staticmethod
    def _safe_source_id(candidate: Dict) -> str:
        """Shared by _build_dest_path and the Tier 2 rejection-file naming below,
        so both derive the same id from a source_url instead of two independent
        regexes that could drift apart."""
        safe_id = candidate['source_url'].rstrip('/').split('/')[-1][:40]
        return ''.join(c if c.isalnum() or c in '-_' else '_' for c in safe_id)

    def _build_dest_path(self, candidate: Dict) -> Path:
        """
        Deterministic filename derived from the source URL, checked
        against SourceRegistry before any download - this is how
        double-delivery is prevented at the SOURCE, independent of
        agents/watcher.py's in-memory-only dedup (self.processed_files,
        lost on every restart).
        """
        filename = f"sourced_{candidate['platform']}_{self._safe_source_id(candidate)}.mp4"
        return self.input_dir / filename

    def _validate_downloaded_file(self, file_path: Path, probe: Optional[Dict]) -> Dict:
        """
        Tier 2 of the Quality Gate for Sourced Content (see HANDOFF.md):
        opens the ACTUAL downloaded file and checks it, before it's
        allowed to reach agents/watcher.py -> Step 1 (analyze_video) and
        waste a full pipeline run on unusable input that slipped past the
        metadata-only CopyrightRiskGate above.
        """
        from agents.quality_control import SourcedFileValidator
        expected_duration = (probe or {}).get('duration_seconds')
        return SourcedFileValidator.validate(str(file_path), expected_duration=expected_duration)

    def _write_rejection_file(self, candidate: Dict, validation: Dict):
        """
        data/sourcing/rejected/{platform}_{id}_REJECTED.txt - same
        convention as this session's other rejection-file work (QC's
        per-short *_ERROR.txt/*_QC_ERROR.txt, sourcing alerts): a human
        should be able to open one file and see exactly why a specific
        download got thrown away, not have to grep a log stream for it.
        """
        try:
            rejected_dir = Path(self.data_dir) / 'sourcing' / 'rejected'
            rejected_dir.mkdir(parents=True, exist_ok=True)
            out_path = rejected_dir / f"{candidate['platform']}_{self._safe_source_id(candidate)}_REJECTED.txt"
            lines = [
                f"Source URL: {candidate.get('source_url')}",
                f"Platform: {candidate.get('platform')}",
                f"Title: {candidate.get('title', '(unknown)')}",
                f"Rejected at: {datetime.now().isoformat()}",
                "",
                "Failed checks:",
            ]
            for check in validation.get('checks', []):
                if check['result'] == 'FAIL':
                    lines.append(f"  - {check['check']}: expected {check['expected']}, found {check['found']}")
            if validation.get('errors'):
                lines.append("")
                lines.append("Errors:")
                lines.extend(f"  - {e}" for e in validation['errors'])
            out_path.write_text('\n'.join(lines))
            logger.info(f"📝 Wrote rejection file: {out_path}")
        except Exception as e:
            logger.warning(f"⚠ Could not write rejection file for {candidate.get('source_url')}: {e}")


def run_clip_sourcing(dry_run: bool = False) -> Dict:
    """Main entry point - scheduled in main.py alongside the other agent jobs."""
    try:
        agent = ClipSourcingAgent()
        return agent.run(dry_run=dry_run)
    except Exception as e:
        logger.error(f"❌ Clip sourcing failed: {e}")
        return {'status': 'error', 'error': str(e), 'timestamp': datetime.now().isoformat()}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    dry = '--dry-run' in sys.argv
    result = run_clip_sourcing(dry_run=dry)
    print(json.dumps(result, indent=2, default=str))
