#!/usr/bin/env python3
"""
Clip Sourcing Agent - Full Integration Test (Component 4)

Exercises agents/clip_sourcing.py's ENTIRE flow end-to-end - discovery
(Reddit + YouTube curated-channel + YouTube search), the copyright/quality
gate, deduplication, real download, cost tracking, the empty-run alert +
notification, and the dashboard-facing config helpers (curated channel
whitelist, sourcing run schedule) - without needing live Reddit/YouTube
credentials, so this is runnable in CI or an offline sandbox, not just on
a machine with real API access.

praw and yt_dlp are replaced with deterministic fakes injected into
sys.modules BEFORE agents.clip_sourcing is imported (its module-level
try/except checks PRAW_AVAILABLE/YTDLP_AVAILABLE at import time, so the
fakes must exist first) - the same fake-object methodology used
throughout this codebase's development to verify logic without real API
calls or real media processing.

Usage:
  python tests/test_clip_sourcing_integration.py
"""

import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Fake praw - deterministic Reddit video submissions
# ---------------------------------------------------------------------------

class _FakeSubmission:
    def __init__(self, permalink, title, author, score, is_video=True, url=''):
        self.permalink = permalink
        self.title = title
        self.author = author
        self.score = score
        self.is_video = is_video
        self.url = url


class _FakeSubreddit:
    def __init__(self, name):
        self.name = name
        self.display_name = name

    def hot(self, limit=15):
        if self.name == 'GTA6':
            return [_FakeSubmission('/r/GTA6/comments/abc/big_leak/', 'Massive GTA6 leak clip', 'gta_leaker', 900)]
        if self.name == 'lowpop':
            return [_FakeSubmission('/r/lowpop/comments/xyz/meh/', 'Barely-seen clip', 'nobody', 10)]
        if self.name == 'tier2test':
            return [_FakeSubmission('/r/tier2test/comments/def/corrupt_one/', 'A clip that will fail post-download validation', 'someone', 900)]
        return []


class _FakeReddit:
    def __init__(self, **kwargs):
        pass

    def subreddit(self, name):
        return _FakeSubreddit(name)


def _install_fake_praw():
    mod = types.ModuleType('praw')
    mod.Reddit = _FakeReddit
    sys.modules['praw'] = mod


# ---------------------------------------------------------------------------
# Fake yt_dlp - deterministic search/channel discovery + probe + download
# ---------------------------------------------------------------------------

class _FakeYoutubeDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, target, download=False):
        if target.startswith('ytsearch'):
            return {'entries': [{
                'id': 'search1', 'url': 'https://youtube.com/watch?v=search1',
                'title': 'Trending gaming moment', 'channel': 'SearchChannel', 'view_count': 100000
            }]}
        if target.rstrip('/').endswith('/videos'):
            return {'entries': [{
                'id': 'chan1', 'url': 'https://youtube.com/watch?v=chan1',
                'title': 'Curated channel upload', 'channel': 'CuratedChannel', 'view_count': 200000
            }]}
        # Single-URL probe (YtdlpProbe.probe) - a real video's metadata
        if 'lowres' in target:
            return {'duration': 60, 'height': 240, 'width': 426, 'uploader': 'LowResUploader', 'view_count': 100000}
        return {'duration': 60, 'height': 1080, 'width': 1920, 'uploader': 'FakeUploader', 'view_count': 100000}

    def download(self, urls):
        dest = Path(self.opts['outtmpl'])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b'FAKE_MP4_BYTES' * 200)


def _install_fake_ytdlp():
    mod = types.ModuleType('yt_dlp')
    mod.YoutubeDL = _FakeYoutubeDL
    sys.modules['yt_dlp'] = mod


# ---------------------------------------------------------------------------
# Fake agents.quality_control - agents/clip_sourcing.py's
# _validate_downloaded_file() lazily imports SourcedFileValidator from the
# REAL quality_control.py, which itself imports real moviepy/numpy at module
# level - neither installable in this offline sandbox. This fake is injected
# into sys.modules the same way praw/yt_dlp are, controllable per scenario
# via NEXT_RESULT, so Tier 2 (post-download validation) can be exercised
# deterministically without a real decodable video file.
# ---------------------------------------------------------------------------

class _FakeSourcedFileValidator:
    NEXT_RESULT = {'status': 'pass', 'errors': [], 'warnings': [], 'metadata': {}, 'checks': []}

    @staticmethod
    def validate(file_path, expected_duration=None):
        return _FakeSourcedFileValidator.NEXT_RESULT


def _install_fake_quality_control():
    mod = types.ModuleType('agents.quality_control')
    mod.SourcedFileValidator = _FakeSourcedFileValidator
    sys.modules['agents.quality_control'] = mod


_install_fake_praw()
_install_fake_ytdlp()
_install_fake_quality_control()

# Isolated environment - own INPUT_DIR/DATA_DIR/config dir, never touches the real repo state.
TEST_DIR = Path(tempfile.mkdtemp(prefix='chaos_merchant_sourcing_test_'))
INPUT_DIR = TEST_DIR / 'input'
DATA_DIR = TEST_DIR / 'data'
CONFIG_DIR = TEST_DIR / 'config'
INPUT_DIR.mkdir()
DATA_DIR.mkdir()
CONFIG_DIR.mkdir()

os.environ['INPUT_DIR'] = str(INPUT_DIR)
os.environ['DATA_DIR'] = str(DATA_DIR)
os.environ['ENABLE_NOTIFICATIONS'] = 'false'  # verify logging still happens even with delivery disabled
os.environ['REDDIT_CLIENT_ID'] = 'fake_client_id'  # praw itself is faked below - content is never
os.environ['REDDIT_CLIENT_SECRET'] = 'fake_client_secret'  # checked, but RedditClipFetcher now skips
os.environ['REDDIT_USER_AGENT'] = 'chaos-merchant-test/1.0'  # Reddit entirely if these are unset
os.environ['MIN_REDDIT_SCORE'] = '500'
os.environ['MIN_YOUTUBE_VIEWS'] = '50000'
os.environ['MAX_SOURCE_CLIP_SECONDS'] = '180'
os.environ['MIN_SOURCE_RESOLUTION_HEIGHT'] = '480'
os.environ['SOURCING_MAX_DOWNLOADS_PER_RUN'] = '10'
os.environ['SOURCING_MAX_PROBES_PER_RUN'] = '30'
os.environ['SOURCING_REQUEST_DELAY_SECONDS'] = '0'

import agents.clip_sourcing as cs  # noqa: E402  (must import after fakes/env are set up)

cs.SUBREDDITS_CONFIG_PATH = CONFIG_DIR / 'source_subreddits.json'
cs.CHANNELS_CONFIG_PATH = CONFIG_DIR / 'source_channels.json'
cs.BLOCKLIST_CONFIG_PATH = CONFIG_DIR / 'source_blocklist.json'
cs.SCHEDULE_CONFIG_PATH = CONFIG_DIR / 'source_schedule.json'
SOURCING_ALERTS_PATH = DATA_DIR / 'sourcing_alerts.json'  # agent derives this from DATA_DIR (see ClipSourcingAgent.data_dir)

results = []


def check(name, condition, detail=''):
    status = 'PASS' if condition else 'FAIL'
    results.append((name, status, detail))
    icon = '✓' if condition else '❌'
    print(f"{icon} {status}  {name}" + (f"  ({detail})" if detail else ''))


def main():
    print("=" * 70)
    print("CLIP SOURCING AGENT - FULL INTEGRATION TEST")
    print("=" * 70)

    # Only one subreddit configured (GTA6) to keep candidate counts deterministic.
    cs.SUBREDDITS_CONFIG_PATH.write_text(json.dumps({'subreddits': ['GTA6']}))

    # content_calendar.json's target_batches_per_day (default 1) caps this
    # run's downloads at ceil(1/2 scheduled runs) = 1 by design (see
    # ClipSourcingAgent._apply_calendar_guidance) - raised here so this
    # test can actually exercise more than one real download per run,
    # not a bug being worked around.
    import core.content_calendar as cc
    cc.CONTENT_CALENDAR_PATH = CONFIG_DIR / 'content_calendar.json'
    cc.load_content_calendar()
    cc.CONTENT_CALENDAR_PATH.write_text(json.dumps({'target_batches_per_day': 10, 'posts_per_day': 3, 'format_mix': cc.DEFAULT_FORMAT_MIX}))

    from core.notifications import send_notification
    cs.send_notification = send_notification  # rebind after DATA_DIR env var was set, for the notification log path

    # --- Scenario A: happy path - discovery -> gate pass -> real download ---
    agent = cs.ClipSourcingAgent(input_dir=str(INPUT_DIR))
    summary_a = agent.run()

    # 1 reddit candidate + 2 YouTube search candidates (default trend brief
    # has 2 fallback queries, and the fake yt-dlp returns the SAME video id
    # for every query - a deliberately unrealistic worst case that verifies
    # the dedup check catches an in-run duplicate, not just a cross-run one).
    check('A1: candidates discovered (reddit + 2 search queries, channels empty)',
          summary_a['candidates_discovered'] == 3, f"got {summary_a['candidates_discovered']}")
    check('A2: unique candidates downloaded, the in-run duplicate skipped',
          summary_a['downloaded'] == 2 and summary_a['duplicates_skipped'] == 1,
          f"downloaded={summary_a['downloaded']} rejected={summary_a['rejected']} dup={summary_a['duplicates_skipped']}")
    downloaded_files = list(INPUT_DIR.glob('sourced_*.mp4'))
    check('A3: real files written to INPUT_DIR', len(downloaded_files) == 2, f"found {len(downloaded_files)}")

    from core.memory import SourceRegistry
    registry = SourceRegistry(str(DATA_DIR / 'chaos_merchant.db'))
    recent = registry.get_recent(limit=10)
    check('A4: SourceRegistry recorded both downloads', sum(1 for r in recent if r['status'] == 'downloaded') == 2)

    cost_log = DATA_DIR / 'cost_log.json'
    check('A5: download cost tracked (log_download_usage fired)', cost_log.exists() and
          any(e.get('kind') == 'download_bandwidth' for e in json.loads(cost_log.read_text())))

    # --- Scenario B: re-run - everything is now a known duplicate -> 0 downloaded -> alert fires ---
    summary_b = agent.run()
    check('B1: second run downloads nothing (dedup via SourceRegistry)', summary_b['downloaded'] == 0)
    check('B2: second run correctly attributes it to duplicates, not the gate',
          summary_b['duplicates_skipped'] == summary_b['candidates_discovered'])

    alerts = json.loads(SOURCING_ALERTS_PATH.read_text()) if SOURCING_ALERTS_PATH.exists() else []
    check('B3: empty-run alert logged to disk', len(alerts) == 1)
    check('B4: alert reason correctly identifies duplicates as the cause',
          bool(alerts) and 'duplicate' in alerts[0]['reason'])
    check('B5: alert has an id + starts undismissed (dashboard dismiss flow)',
          bool(alerts) and alerts[0].get('id') and alerts[0].get('dismissed') is False)

    notif_log = DATA_DIR / 'notification_log.json'
    check('B6: notification logged even with ENABLE_NOTIFICATIONS=false', notif_log.exists() and
          any('downloaded 0 new clips' in e['message'] for e in json.loads(notif_log.read_text())))

    # --- Scenario C: a candidate that fails the copyright gate (low popularity) ---
    cs.SUBREDDITS_CONFIG_PATH.write_text(json.dumps({'subreddits': ['lowpop']}))
    registry2 = cs.SourceRegistry(str(DATA_DIR / 'chaos_merchant.db'))
    agent_c = cs.ClipSourcingAgent(input_dir=str(INPUT_DIR))
    # Isolate scenario C from scenario A/B's search-query candidates by clearing trend brief lookups
    agent_c.youtube_fetcher.fetch_search_candidates = lambda *a, **kw: []
    agent_c.youtube_fetcher.fetch_channel_candidates = lambda *a, **kw: []
    summary_c = agent_c.run()
    check('C1: low-popularity candidate rejected by the gate, not downloaded',
          summary_c['downloaded'] == 0 and summary_c['rejected'] == 1)
    rejected_rows = [r for r in registry2.get_recent(limit=20) if r['status'] == 'rejected']
    check('C2: rejection reason mentions the popularity threshold',
          any('below minimum' in (r.get('rejection_reason') or '') for r in rejected_rows))

    # --- Scenario D: dashboard-facing config helpers (channel whitelist + run schedule) ---
    added = cs.add_source_channel('https://www.youtube.com/@TestChannel')
    dup_add = cs.add_source_channel('https://www.youtube.com/@TestChannel')
    check('D1: add_source_channel adds a new channel', added is True and dup_add is False)
    check('D2: channel now present in config', 'https://www.youtube.com/@TestChannel' in cs._load_channels())

    removed = cs.remove_source_channel('https://www.youtube.com/@TestChannel')
    check('D3: remove_source_channel removes it, no-ops on missing',
          removed is True and cs.remove_source_channel('https://www.youtube.com/@TestChannel') is False)

    default_times = cs._load_sourcing_schedule()
    check('D4: sourcing schedule auto-creates with sane defaults', default_times == ['07:30', '18:00'])

    cs.add_sourcing_run_time('12:00')
    check('D5: run time added and kept sorted', cs._load_sourcing_schedule() == ['07:30', '12:00', '18:00'])

    bad = cs.add_sourcing_run_time('not-a-time')
    check('D6: invalid run time rejected', bad is False)

    cs.remove_sourcing_run_time('12:00')
    check('D7: run time removed', cs._load_sourcing_schedule() == ['07:30', '18:00'])

    # Config-derived runs-per-day used by _apply_calendar_guidance - confirm it reads the SAME file main.py reads.
    agent_d = cs.ClipSourcingAgent(input_dir=str(INPUT_DIR))
    check('D8: agent initializes cleanly with the schedule-derived runs-per-day guidance', agent_d is not None)

    # --- Scenario E: Tier 2 gate rejects a download that yt-dlp reported as
    # successful but that fails post-download validation (corrupt/truncated/
    # no real video stream) - HANDOFF.md's "Quality Gate for Sourced Content" ---
    cs.SUBREDDITS_CONFIG_PATH.write_text(json.dumps({'subreddits': ['tier2test']}))
    registry_e = cs.SourceRegistry(str(DATA_DIR / 'chaos_merchant.db'))
    agent_e = cs.ClipSourcingAgent(input_dir=str(INPUT_DIR))
    agent_e.youtube_fetcher.fetch_search_candidates = lambda *a, **kw: []
    agent_e.youtube_fetcher.fetch_channel_candidates = lambda *a, **kw: []

    _FakeSourcedFileValidator.NEXT_RESULT = {
        'status': 'error',
        'errors': ['File could not be opened/decoded as video: simulated corrupt download'],
        'warnings': [], 'metadata': {},
        'checks': [{'check': 'decodable', 'result': 'FAIL', 'expected': 'opens and reads via moviepy',
                    'found': 'simulated corrupt download'}]
    }
    try:
        summary_e = agent_e.run()
        check('E1: post-download validation failure is NOT counted as downloaded',
              summary_e['downloaded'] == 0 and summary_e['rejected'] == 1,
              f"downloaded={summary_e['downloaded']} rejected={summary_e['rejected']}")

        leftover = list(INPUT_DIR.glob('sourced_reddit_corrupt_one*.mp4'))
        check('E2: the invalid downloaded file is removed from INPUT_DIR, not left for the watcher',
              len(leftover) == 0, f"found {[p.name for p in leftover]}")

        rejected_files = list((DATA_DIR / 'sourcing' / 'rejected').glob('*_REJECTED.txt'))
        check('E3: a REJECTED.txt file was written with the failure reason',
              len(rejected_files) == 1 and 'simulated corrupt download' in rejected_files[0].read_text(),
              f"found {[p.name for p in rejected_files]}")

        rejected_rows_e = [r for r in registry_e.get_recent(limit=20) if r['status'] == 'rejected']
        check('E4: SourceRegistry records it as rejected (never retried) with the validation reason',
              any('post-download validation' in (r.get('rejection_reason') or '') for r in rejected_rows_e))
    finally:
        # Restore for anything running after this scenario in a future edit.
        _FakeSourcedFileValidator.NEXT_RESULT = {'status': 'pass', 'errors': [], 'warnings': [], 'metadata': {}, 'checks': []}

    print("=" * 70)
    passed = sum(1 for _, status, _ in results if status == 'PASS')
    total = len(results)
    print(f"{passed}/{total} checks passed")
    print("=" * 70)

    shutil.rmtree(TEST_DIR, ignore_errors=True)
    return passed == total


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
