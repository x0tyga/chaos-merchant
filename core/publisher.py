"""
Publisher Module - Step 18
Auto-posts a packaged batch (output/batch_<id>/, written by
agents/output_packaging.py) to YouTube, TikTok, and Instagram.

Each platform is independently gated by an env flag - AUTO_POST_YOUTUBE,
AUTO_POST_TIKTOK, AUTO_POST_INSTAGRAM - and ALL DEFAULT OFF. Nothing in
this module posts anywhere unless the corresponding flag is explicitly
set to 'true' in .env; publish_batch() on an all-flags-off system (the
default) logs that publishing is disabled and returns cleanly.

Setup requirements per platform (none of this is performed by this
module - it consumes credentials obtained elsewhere):
- YouTube: an OAuth app in Google Cloud Console with the YouTube Data
  API v3 enabled and a consent screen configured, client secrets JSON
  downloaded. Run `python -m core.publisher setup-youtube` once to
  authorize (opens a local browser consent flow, same pattern as
  agents/analytics_feedback.py's `setup` command).
- TikTok: a Content Posting API app registered with TikTok, and (for
  public, non-SELF_ONLY posting) audited/approved by TikTok. TikTok's
  OAuth requires a real HTTPS redirect URI - there is no localhost
  installed-app flow like Google's - so this module does not perform
  that initial web consent itself. Obtain an access token externally and
  set TIKTOK_ACCESS_TOKEN (+ TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET for
  your own refresh handling) in .env.
- Instagram: a Meta Business app with Instagram Graph API access, an
  Instagram Professional (Business/Creator) account linked to a Facebook
  Page, and a long-lived access token. Set INSTAGRAM_ACCESS_TOKEN and
  INSTAGRAM_BUSINESS_ACCOUNT_ID in .env. The Graph API's media container
  step fetches the video FROM a public URL - it does not accept direct
  file bytes - so PUBLIC_VIDEO_BASE_URL must point at wherever finished
  shorts are actually reachable over HTTPS (e.g. an S3 bucket or your own
  web server); this module does not host video files itself.

Verification note: YouTube's upload API is unchanged, stable, and follows
the same pattern already used and tested in this codebase for read-only
Data/Analytics API calls. TikTok's and Instagram's implementations below
follow each platform's documented Content Posting / Graph API request
shapes, but neither has been exercised against a live endpoint in this
session (no approved TikTok app, no live Instagram Business token
available) - review both against current platform docs before flipping
their AUTO_POST_* flag on for the first time.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    GOOGLEAPICLIENT_AVAILABLE = True
except ImportError:
    GOOGLEAPICLIENT_AVAILABLE = False
    logger.warning("googleapiclient not available - YouTube publishing will be unavailable (pip install google-api-python-client)")

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False
    logger.warning("google-auth-oauthlib not available - YouTube publishing will be unavailable (pip install google-auth-oauthlib)")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests not available - TikTok/Instagram publishing will be unavailable")

from core.memory import ChannelMemory

UPLOAD_SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
TIKTOK_API_BASE = 'https://open.tiktokapis.com/v2'
INSTAGRAM_API_BASE = 'https://graph.facebook.com/v21.0'


def _flag_enabled(env_var: str) -> bool:
    return os.getenv(env_var, 'false').strip().lower() in ('true', '1', 'yes')


class YouTubePublisher:
    """Resumable upload via YouTube Data API v3. Requires prior OAuth (see module docstring)."""

    def __init__(self):
        self.youtube = None
        if not (GOOGLEAPICLIENT_AVAILABLE and OAUTH_AVAILABLE):
            logger.info("ℹ YouTube publisher unavailable - required packages not installed")
            return
        creds = self._load_credentials()
        if creds:
            try:
                self.youtube = build('youtube', 'v3', credentials=creds)
            except Exception as e:
                logger.warning(f"⚠ YouTube upload API initialization failed: {e}")

    def _load_credentials(self):
        token_path = os.getenv('YOUTUBE_UPLOAD_TOKEN_PATH', './data/youtube_upload_token.json')
        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, UPLOAD_SCOPES)
            except Exception as e:
                logger.warning(f"⚠ Could not load YouTube upload token: {e}")

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, 'w') as f:
                    f.write(creds.to_json())
            except Exception as e:
                logger.warning(f"⚠ Could not refresh YouTube upload token: {e}")
                return None

        if not creds or not creds.valid:
            logger.info(
                "ℹ YouTube upload not authorized yet - run once interactively: "
                "python -m core.publisher setup-youtube"
            )
            return None
        return creds

    @property
    def available(self) -> bool:
        return self.youtube is not None

    def upload(self, video_path: str, title: str, description: str, tags: List[str],
               thumbnail_path: Optional[str] = None, privacy_status: str = 'public',
               category_id: str = '20') -> Dict:
        """category_id 20 = Gaming (YouTube's standard category ID)."""
        if not self.available:
            return {'status': 'unavailable', 'error': 'YouTube publisher not authorized/available'}

        if not os.path.exists(video_path):
            return {'status': 'error', 'error': f'Video file not found: {video_path}'}

        body = {
            'snippet': {
                'title': title[:100],
                'description': description[:5000],
                'tags': tags[:500],
                'categoryId': category_id
            },
            'status': {
                'privacyStatus': privacy_status,
                'selfDeclaredMadeForKids': False
            }
        }

        try:
            media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype='video/mp4')
            request = self.youtube.videos().insert(part='snippet,status', body=body, media_body=media)

            response = None
            while response is None:
                status, response = request.next_chunk()

            video_id = response['id']
            logger.info(f"✓ YouTube upload complete: {video_id}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    self.youtube.thumbnails().set(
                        videoId=video_id, media_body=MediaFileUpload(thumbnail_path)
                    ).execute()
                    logger.info(f"✓ Thumbnail set for {video_id}")
                except HttpError as e:
                    logger.warning(f"⚠ Thumbnail upload failed for {video_id} (video itself succeeded): {e}")

            return {
                'status': 'success',
                'platform': 'youtube',
                'video_id': video_id,
                'url': f'https://youtube.com/shorts/{video_id}'
            }
        except HttpError as e:
            logger.error(f"❌ YouTube upload failed: {e}")
            return {'status': 'error', 'error': str(e)}
        except Exception as e:
            logger.error(f"❌ YouTube upload failed: {e}")
            return {'status': 'error', 'error': str(e)}


class TikTokPublisher:
    """
    TikTok Content Posting API - direct post via FILE_UPLOAD source.
    Requires a pre-obtained access token (see module docstring). Unaudited
    apps can only post as SELF_ONLY (private, visible only to the poster)
    - a TikTok platform restriction, not a bug here.
    """

    UPLOAD_CHUNK_SIZE = 10 * 1024 * 1024  # 10MB

    def __init__(self):
        self.access_token = os.getenv('TIKTOK_ACCESS_TOKEN', '')

    @property
    def available(self) -> bool:
        return REQUESTS_AVAILABLE and bool(self.access_token)

    def _headers(self) -> Dict:
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json; charset=UTF-8'
        }

    def upload(self, video_path: str, title: str, privacy_level: str = 'SELF_ONLY',
               max_retries: int = 3) -> Dict:
        if not self.available:
            return {'status': 'unavailable', 'error': 'TikTok publisher not configured (TIKTOK_ACCESS_TOKEN missing)'}

        if not os.path.exists(video_path):
            return {'status': 'error', 'error': f'Video file not found: {video_path}'}

        video_size = os.path.getsize(video_path)
        chunk_size = min(self.UPLOAD_CHUNK_SIZE, video_size)
        total_chunks = max(1, (video_size + chunk_size - 1) // chunk_size)

        init_body = {
            'post_info': {
                'title': title[:150],
                'privacy_level': privacy_level,
                'disable_duet': False,
                'disable_comment': False,
                'disable_stitch': False
            },
            'source_info': {
                'source': 'FILE_UPLOAD',
                'video_size': video_size,
                'chunk_size': chunk_size,
                'total_chunk_count': total_chunks
            }
        }

        try:
            init_resp = self._request_with_backoff(
                'POST', f'{TIKTOK_API_BASE}/post/publish/video/init/',
                headers=self._headers(), json=init_body, max_retries=max_retries
            )
            init_data = init_resp.json().get('data', {})
            publish_id = init_data.get('publish_id')
            upload_url = init_data.get('upload_url')
            if not publish_id or not upload_url:
                return {'status': 'error', 'error': f'TikTok init failed: {init_resp.text[:300]}'}

            with open(video_path, 'rb') as f:
                offset = 0
                while offset < video_size:
                    chunk = f.read(chunk_size)
                    chunk_end = offset + len(chunk) - 1
                    self._request_with_backoff(
                        'PUT', upload_url,
                        headers={
                            'Content-Range': f'bytes {offset}-{chunk_end}/{video_size}',
                            'Content-Type': 'video/mp4'
                        },
                        data=chunk, max_retries=max_retries
                    )
                    offset += len(chunk)

            logger.info(f"✓ TikTok upload submitted: {publish_id} (status: PROCESSING)")
            return {
                'status': 'success', 'platform': 'tiktok', 'publish_id': publish_id,
                'note': 'processing on TikTok - check_status() separately for final result'
            }
        except Exception as e:
            logger.error(f"❌ TikTok upload failed: {e}")
            return {'status': 'error', 'error': str(e)}

    def check_status(self, publish_id: str) -> Dict:
        if not self.available:
            return {'status': 'unavailable'}
        try:
            resp = self._request_with_backoff(
                'POST', f'{TIKTOK_API_BASE}/post/publish/status/fetch/',
                headers=self._headers(), json={'publish_id': publish_id}, max_retries=2
            )
            return resp.json().get('data', {})
        except Exception as e:
            logger.warning(f"⚠ TikTok status check failed: {e}")
            return {'status': 'unknown', 'error': str(e)}

    def _request_with_backoff(self, method: str, url: str, max_retries: int = 3, **kwargs):
        """Exponential backoff (1s, 2s, 4s...) on 429/5xx - TikTok's API is rate-limited per app."""
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = requests.request(method, url, timeout=60, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning(f"⚠ TikTok API {resp.status_code}, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning(f"⚠ TikTok request error, retrying in {wait}s: {e}")
                time.sleep(wait)
        raise last_exc or Exception("TikTok request failed after retries")


class InstagramPublisher:
    """
    Instagram Graph API - two-step Reels publish (create a media container
    from a public video URL, poll until processed, then publish). Requires
    INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ACCOUNT_ID, and
    PUBLIC_VIDEO_BASE_URL (see module docstring - the Graph API fetches
    the video FROM a URL you host, it does not accept direct file bytes).
    """

    def __init__(self):
        self.access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN', '')
        self.ig_user_id = os.getenv('INSTAGRAM_BUSINESS_ACCOUNT_ID', '')
        self.public_base_url = os.getenv('PUBLIC_VIDEO_BASE_URL', '')

    @property
    def available(self) -> bool:
        return REQUESTS_AVAILABLE and bool(self.access_token and self.ig_user_id)

    def upload(self, video_filename: str, caption: str, poll_interval: int = 10,
               max_poll_attempts: int = 30) -> Dict:
        if not self.available:
            return {'status': 'unavailable', 'error': 'Instagram publisher not configured'}
        if not self.public_base_url:
            return {'status': 'error', 'error': 'PUBLIC_VIDEO_BASE_URL not set - Instagram requires a publicly reachable video URL'}

        video_url = f"{self.public_base_url.rstrip('/')}/{video_filename}"

        try:
            container_resp = requests.post(
                f'{INSTAGRAM_API_BASE}/{self.ig_user_id}/media',
                data={
                    'media_type': 'REELS',
                    'video_url': video_url,
                    'caption': caption[:2200],
                    'access_token': self.access_token
                },
                timeout=30
            )
            container_resp.raise_for_status()
            container_id = container_resp.json().get('id')
            if not container_id:
                return {'status': 'error', 'error': f'Container creation failed: {container_resp.text[:300]}'}

            for _ in range(max_poll_attempts):
                status_resp = requests.get(
                    f'{INSTAGRAM_API_BASE}/{container_id}',
                    params={'fields': 'status_code', 'access_token': self.access_token},
                    timeout=30
                )
                status_code = status_resp.json().get('status_code')
                if status_code == 'FINISHED':
                    break
                if status_code == 'ERROR':
                    return {'status': 'error', 'error': 'Instagram container processing failed'}
                time.sleep(poll_interval)
            else:
                return {'status': 'error', 'error': 'Instagram container processing timed out'}

            publish_resp = requests.post(
                f'{INSTAGRAM_API_BASE}/{self.ig_user_id}/media_publish',
                data={'creation_id': container_id, 'access_token': self.access_token},
                timeout=30
            )
            publish_resp.raise_for_status()
            media_id = publish_resp.json().get('id')

            logger.info(f"✓ Instagram Reel published: {media_id}")
            return {'status': 'success', 'platform': 'instagram', 'media_id': media_id}
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Instagram upload failed: {e}")
            return {'status': 'error', 'error': str(e)}


class Publisher:
    """Orchestrates publishing a packaged batch folder to every AUTO_POST_*-enabled platform."""

    def __init__(self, data_dir: str = './data'):
        self.data_dir = data_dir
        self.youtube = YouTubePublisher()
        self.tiktok = TikTokPublisher()
        self.instagram = InstagramPublisher()
        self.channel_memory = ChannelMemory(str(Path(data_dir) / 'chaos_merchant.db'))

    def publish_batch(self, batch_folder: str) -> Dict:
        batch_path = Path(batch_folder)
        manifest_path = batch_path / 'manifests' / 'BATCH_MANIFEST.json'
        if not manifest_path.exists():
            return {'status': 'error', 'error': f'No BATCH_MANIFEST.json found in {batch_folder}'}

        with open(manifest_path, 'r') as f:
            batch_manifest = json.load(f)

        if not batch_manifest.get('ready_for_upload'):
            logger.warning(
                f"⚠ Batch {batch_manifest.get('batch_id')} not marked ready_for_upload "
                f"(QC routing != pass) - skipping"
            )
            return {'status': 'skipped', 'reason': 'qc_not_pass', 'batch_id': batch_manifest.get('batch_id')}

        enabled = {
            'youtube': _flag_enabled('AUTO_POST_YOUTUBE'),
            'tiktok': _flag_enabled('AUTO_POST_TIKTOK'),
            'instagram': _flag_enabled('AUTO_POST_INSTAGRAM')
        }

        if not any(enabled.values()):
            logger.info("ℹ Publisher: all AUTO_POST_* flags are off - nothing to do (this is the default, safe state)")
            return {'status': 'disabled', 'enabled': enabled, 'batch_id': batch_manifest.get('batch_id')}

        results = []
        metadata_dir = batch_path / 'upload_metadata'
        shorts_dir = batch_path / 'shorts'
        thumbnails_dir = batch_path / 'thumbnails'

        for metadata_file in sorted(metadata_dir.glob('*.json')):
            with open(metadata_file, 'r') as f:
                meta = json.load(f)

            video_path = shorts_dir / meta['file']
            thumbnail_path = thumbnails_dir / meta['thumbnail']
            short_result = {'short_index': meta.get('short_index'), 'title': meta.get('title'), 'platforms': {}}

            if enabled['youtube']:
                yt_result = self.youtube.upload(
                    str(video_path), meta['title'], meta.get('description', ''),
                    meta.get('tags', []) + meta.get('hashtags', []),
                    thumbnail_path=str(thumbnail_path) if thumbnail_path.exists() else None
                )
                short_result['platforms']['youtube'] = yt_result
                if yt_result.get('status') == 'success':
                    self.channel_memory.mark_published(meta['title'], yt_result['video_id'])

            if enabled['tiktok']:
                short_result['platforms']['tiktok'] = self.tiktok.upload(str(video_path), meta['title'])

            if enabled['instagram']:
                caption = f"{meta['title']}\n\n{' '.join('#' + h.lstrip('#') for h in meta.get('hashtags', []))}"
                short_result['platforms']['instagram'] = self.instagram.upload(meta['file'], caption)

            results.append(short_result)

        logger.info(f"✓ Publisher batch complete: {len(results)} short(s) processed for {batch_manifest.get('batch_id')}")
        return {'status': 'success', 'batch_id': batch_manifest.get('batch_id'), 'enabled': enabled, 'results': results}


def publish_batch(batch_folder: str, data_dir: str = './data') -> Dict:
    """Main entry point."""
    try:
        publisher = Publisher(data_dir=data_dir)
        return publisher.publish_batch(batch_folder)
    except Exception as e:
        logger.error(f"❌ Publisher failed: {e}")
        return {'status': 'error', 'error': str(e)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == 'setup-youtube':
        if not OAUTH_AVAILABLE:
            print("google-auth-oauthlib not installed: pip install google-auth-oauthlib")
            sys.exit(1)
        client_secrets_path = os.getenv('YOUTUBE_OAUTH_CLIENT_SECRETS', './config/youtube_client_secrets.json')
        if not os.path.exists(client_secrets_path):
            print(f"Missing OAuth client secrets file: {client_secrets_path}")
            print("Download it from Google Cloud Console (APIs & Services > Credentials) and set")
            print("YOUTUBE_OAUTH_CLIENT_SECRETS in .env, or place it at the default path above.")
            sys.exit(1)

        flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, UPLOAD_SCOPES)
        creds = flow.run_local_server(port=0)
        token_path = os.getenv('YOUTUBE_UPLOAD_TOKEN_PATH', './data/youtube_upload_token.json')
        Path(token_path).parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())
        print(f"✓ YouTube upload authorized. Token saved: {token_path}")

    elif len(sys.argv) > 2 and sys.argv[1] == 'publish':
        result = publish_batch(sys.argv[2])
        print(json.dumps(result, indent=2, default=str))

    else:
        print("Usage:")
        print("  python -m core.publisher setup-youtube          # one-time YouTube OAuth")
        print("  python -m core.publisher publish <batch_dir>     # publish one batch folder")
