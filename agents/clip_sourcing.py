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

# ---- Config files (auto-created with sane defaults on first run - same
# pattern as config/competitors.json / config/gaming_calendar.json) ----
SUBREDDITS_CONFIG_PATH = Path('./config/source_subreddits.json')
CHANNELS_CONFIG_PATH = Path('./config/source_channels.json')
BLOCKLIST_CONFIG_PATH = Path('./config/source_blocklist.json')

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

        try:
            reddit = praw.Reddit(
                client_id=os.getenv('REDDIT_CLIENT_ID', ''),
                client_secret=os.getenv('REDDIT_CLIENT_SECRET', ''),
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

    def __init__(self, input_dir: str = None):
        self.input_dir = Path(input_dir or os.getenv('INPUT_DIR', './input'))
        self.input_dir.mkdir(parents=True, exist_ok=True)
        self.registry = SourceRegistry()
        self.gate = CopyrightRiskGate()
        self.limiter = SourcingRateLimiter()
        self.reddit_fetcher = RedditClipFetcher()
        self.youtube_fetcher = YouTubeClipFetcher()

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
                logger.info(f"✓ Downloaded: {candidate.get('title', source_url)[:60]!r} -> {file_path.name}")
                self.registry.record_downloaded(
                    source_url, candidate['platform'], str(file_path),
                    candidate.get('popularity_signal', 0), (probe or {}).get('duration_seconds'),
                    title=candidate.get('title')
                )
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
        return summary

    def _build_dest_path(self, candidate: Dict) -> Path:
        """
        Deterministic filename derived from the source URL, checked
        against SourceRegistry before any download - this is how
        double-delivery is prevented at the SOURCE, independent of
        agents/watcher.py's in-memory-only dedup (self.processed_files,
        lost on every restart).
        """
        safe_id = candidate['source_url'].rstrip('/').split('/')[-1][:40]
        safe_id = ''.join(c if c.isalnum() or c in '-_' else '_' for c in safe_id)
        filename = f"sourced_{candidate['platform']}_{safe_id}.mp4"
        return self.input_dir / filename


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
