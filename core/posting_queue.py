"""
Posting Queue - the layer between "a batch passed QC and was packaged"
and "a Short actually gets uploaded to YouTube". Turns core/publisher.py's
old immediate-fire-every-short-at-once behavior into a spaced-out,
deduplicated, scheduled autonomous posting system.

Two entry points, called from two different places:
- enqueue_batch_for_posting(): called once per pipeline run, from
  core/pipeline.py right after Step 8 (Pipeline Audit), IF the batch's QC
  routing is 'pass'. Computes a content hash per Short, skips anything
  already seen, and schedules the rest at spaced-out optimal times
  (core/posting_schedule.py) respecting posts_per_day
  (core/content_calendar.py). Does NOT post anything itself.
- drain_due_posts(): called on a recurring schedule from main.py (see
  POSTING_QUEUE_DRAIN_MINUTES in .env). Actually uploads whatever is due,
  ONLY if AUTO_POST_YOUTUBE=true - otherwise logs that it's disabled and
  returns cleanly, the exact same safety-switch contract
  core/publisher.py's AUTO_POST_* flags already use.

AUTO_POST_YOUTUBE is genuinely just a switch, not a review gate: when
true, this drains and posts on every scheduled tick with no human
touchpoint, forever, until switched back to false. There is no queued
"pending approval" state - "queued" here only ever means "scheduled for
a specific future time", never "waiting for a human to approve it".
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from core.memory import PostingQueue, ChannelMemory, SourceRegistry
from core.content_calendar import load_content_calendar
from core.posting_schedule import PostingScheduleOptimizer
from core.publisher import YouTubePublisher, _flag_enabled

logger = logging.getLogger(__name__)

HASH_CHUNK_SIZE = 1024 * 1024  # 1MB


def _hash_file(path: Path) -> str:
    """SHA-256 of the actual video bytes - the content-hash dedup key."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _next_available_slots(queue: PostingQueue, optimizer: PostingScheduleOptimizer,
                           count: int, posts_per_day: int) -> List[datetime]:
    """
    Chronologically-ordered future datetimes to schedule `count` posts at,
    never exceeding posts_per_day on any single date and never scheduling
    a slot that has already passed. Fills out today's remaining optimal
    hours first, then spills into subsequent days at full posts_per_day
    each - this is what actually spaces a big batch out across several
    days instead of posting all 7 shorts on day one.
    """
    hours = sorted(optimizer.get_optimal_hours(count=max(posts_per_day, 1)))
    if not hours:
        hours = [12, 17, 20]

    slots = []
    now = datetime.now()
    day_offset = 0
    while len(slots) < count and day_offset < 90:  # 90-day safety valve
        day = (now + timedelta(days=day_offset)).date()
        already_scheduled = queue.count_scheduled_on_date(day.isoformat())
        available_today = max(0, posts_per_day - already_scheduled)
        for hour in hours[:available_today]:
            candidate = datetime.combine(day, datetime.min.time()).replace(hour=hour)
            if candidate > now:
                slots.append(candidate)
                if len(slots) >= count:
                    break
        day_offset += 1
    return slots


def _format_used_for_short(voiceover_results: List[Dict], short_number: Optional[int]) -> Optional[str]:
    if short_number is None or short_number >= len(voiceover_results):
        return None
    cv = voiceover_results[short_number]
    return cv.get('format_used') or cv.get('format_type')


def enqueue_batch_for_posting(batch_folder: str, voiceover_results: List[Dict],
                               production_result: Dict, video_path: str,
                               batch_cost_total: float = 0.0, data_dir: str = './data') -> Dict:
    """
    Called once per pipeline run after packaging + QC. Reads the just-
    packaged batch folder directly (same BATCH_MANIFEST.json /
    upload_metadata/*.json / shorts/*.mp4 shape core/publisher.py already
    consumes) and enqueues every Short that isn't a content-hash duplicate,
    at spaced-out scheduled times. batch_cost_total (real Anthropic spend
    for this pipeline run, from core.cost_tracker.get_cost_between()) is
    divided evenly across the shorts actually enqueued, for the "cost per
    Short" dashboard requirement - an approximation (per-call cost isn't
    tagged per-short at the source), stated as such rather than presented
    as exact.
    """
    batch_path = Path(batch_folder)
    manifest_path = batch_path / 'manifests' / 'BATCH_MANIFEST.json'
    if not manifest_path.exists():
        logger.warning(f"⚠ No BATCH_MANIFEST.json found in {batch_folder} - cannot enqueue for posting")
        return {'status': 'error', 'error': 'missing BATCH_MANIFEST.json'}

    with open(manifest_path, 'r') as f:
        batch_manifest = json.load(f)

    if not batch_manifest.get('ready_for_upload'):
        logger.info(
            f"ℹ Batch {batch_manifest.get('batch_id')} not ready_for_upload (QC routing != pass) - "
            f"not queueing for autonomous posting"
        )
        return {'status': 'skipped', 'reason': 'qc_not_pass', 'batch_id': batch_manifest.get('batch_id')}

    db_path = str(Path(data_dir) / 'chaos_merchant.db')
    queue = PostingQueue(db_path)
    source_registry = SourceRegistry(db_path)
    optimizer = PostingScheduleOptimizer(data_dir=data_dir)
    calendar = load_content_calendar()
    posts_per_day = max(1, int(calendar.get('posts_per_day', 3)))

    source_info = source_registry.get_by_file_path(str(video_path)) or {}

    metadata_dir = batch_path / 'upload_metadata'
    shorts_dir = batch_path / 'shorts'
    thumbnails_dir = batch_path / 'thumbnails'

    candidates = []
    seen_hashes_this_batch = set()
    for meta_file in sorted(metadata_dir.glob('*.json')):
        with open(meta_file, 'r') as f:
            meta = json.load(f)

        video_file = shorts_dir / meta['file']
        if not video_file.exists():
            logger.warning(f"⚠ Queued-post source video missing on disk, skipping: {video_file}")
            continue

        content_hash = _hash_file(video_file)
        # Checked against BOTH the DB (a duplicate from a previous batch)
        # AND every hash already accepted earlier in this same loop (a
        # duplicate within this very batch) - content_hash_exists() alone
        # can't see the latter since nothing in this batch is inserted
        # into the DB until after this whole loop finishes.
        if content_hash in seen_hashes_this_batch or queue.content_hash_exists(content_hash):
            logger.warning(f"⚠ Duplicate content detected (hash match) - will NOT enqueue: {meta.get('title', '')[:60]!r}")
            continue
        seen_hashes_this_batch.add(content_hash)

        # short_index is 1-based positional (see output_packaging.py) -
        # short_results is keyed by short_number (0-based, into
        # voiceover_results) in the SAME positional order for successfully
        # produced shorts, so position i in short_results corresponds to
        # position i among packaged shorts.
        position = meta.get('short_index', 1) - 1
        short_results = (production_result or {}).get('short_results', [])
        short_number = short_results[position]['short_number'] if position < len(short_results) else None
        format_used = _format_used_for_short(voiceover_results, short_number)

        thumb_path = thumbnails_dir / meta['thumbnail']
        candidates.append({
            'meta': meta,
            'video_path': video_file,
            'thumbnail_path': str(thumb_path) if thumb_path.exists() else None,
            'content_hash': content_hash,
            'format_used': format_used,
        })

    skipped_duplicates = len(list(metadata_dir.glob('*.json'))) - len(candidates)

    if not candidates:
        logger.info(f"ℹ Batch {batch_manifest.get('batch_id')}: nothing new to enqueue ({skipped_duplicates} duplicate(s) skipped)")
        return {'status': 'no_op', 'enqueued': 0, 'skipped_duplicates': skipped_duplicates}

    slots = _next_available_slots(queue, optimizer, len(candidates), posts_per_day)
    cost_per_short = round(batch_cost_total / len(candidates), 6) if candidates else 0.0

    enqueued = []
    for item, scheduled_time in zip(candidates, slots):
        meta = item['meta']
        row_id = queue.enqueue(
            batch_id=batch_manifest.get('batch_id'),
            short_index=meta.get('short_index'),
            video_path=str(item['video_path']),
            thumbnail_path=item['thumbnail_path'],
            title=meta.get('title', 'Untitled Short'),
            description=meta.get('description', ''),
            hashtags=meta.get('hashtags', []),
            tags=meta.get('tags', []),
            format_used=item['format_used'],
            source_url=source_info.get('source_url'),
            source_platform=source_info.get('platform'),
            content_hash=item['content_hash'],
            scheduled_time=scheduled_time.isoformat(),
            estimated_cost_usd=cost_per_short,
        )
        if row_id:
            enqueued.append({'id': row_id, 'title': meta.get('title'), 'scheduled_time': scheduled_time.isoformat()})

    logger.info(
        f"✓ Queued {len(enqueued)} short(s) for autonomous posting from batch {batch_manifest.get('batch_id')} "
        f"({skipped_duplicates} duplicate(s) skipped). Next scheduled: "
        f"{enqueued[0]['scheduled_time'] if enqueued else 'n/a'}"
    )
    return {
        'status': 'success',
        'batch_id': batch_manifest.get('batch_id'),
        'enqueued': len(enqueued),
        'skipped_duplicates': skipped_duplicates,
        'items': enqueued,
    }


def drain_due_posts(data_dir: str = './data') -> Dict:
    """
    Posts every queue item whose scheduled_time has arrived. Only does
    anything if AUTO_POST_YOUTUBE=true - checked fresh on every call (not
    cached), so flipping the .env value takes effect on the very next
    scheduled drain tick, no restart required. This is the ONLY gate: once
    true, every due item posts automatically, forever, with no human
    approval step - "queued" means "scheduled for a specific time", not
    "pending review".

    A duplicate content-hash is re-checked here too (not just at enqueue
    time) in case the same hash entered the queue from two different
    batches before either was drained - if found, the item is skipped
    (marked skipped_duplicate) and the next due item is posted instead,
    exactly per the "skip it and pull the next queued item" requirement.
    """
    if not _flag_enabled('AUTO_POST_YOUTUBE'):
        logger.info("ℹ Posting queue drain skipped - AUTO_POST_YOUTUBE is false (this is the default, safe state)")
        return {'status': 'disabled'}

    db_path = str(Path(data_dir) / 'chaos_merchant.db')
    queue = PostingQueue(db_path)
    channel_memory = ChannelMemory(db_path)
    youtube = YouTubePublisher()

    due = queue.get_due()
    if not due:
        logger.info("ℹ Posting queue drain: nothing due right now")
        return {'status': 'no_op', 'posted': 0}

    posted, skipped, failed = [], [], []
    for item in due:
        # Re-check duplicate status: another due item earlier in this same
        # loop, or a previous drain run, may have posted an identical hash
        # from a different batch since this row was originally enqueued.
        seen_elsewhere = any(p['content_hash'] == item['content_hash'] for p in posted)
        if seen_elsewhere:
            queue.mark_skipped_duplicate(item['id'], 'duplicate content hash posted earlier in this same drain run')
            skipped.append(item['title'])
            continue

        if not youtube.available:
            logger.warning("⚠ AUTO_POST_YOUTUBE is true but YouTube publisher isn't authorized - run: python -m core.publisher setup-youtube")
            failed.append(item['title'])
            queue.mark_failed(item['id'], 'YouTube publisher not authorized')
            continue

        hashtags = json.loads(item.get('hashtags') or '[]')
        tags = json.loads(item.get('tags') or '[]')
        result = youtube.upload(
            item['video_path'], item['title'], item.get('description', ''),
            tags + hashtags, thumbnail_path=item.get('thumbnail_path')
        )

        if result.get('status') == 'success':
            queue.mark_posted(item['id'], result['video_id'], result['url'])
            channel_memory.mark_published(item['title'], result['video_id'])
            posted.append({'title': item['title'], 'url': result['url'], 'content_hash': item['content_hash']})
            logger.info(f"✓ Autonomously posted: {item['title'][:60]!r} -> {result['url']}")
        else:
            queue.mark_failed(item['id'], result.get('error', 'unknown upload error'))
            failed.append(item['title'])
            logger.error(f"❌ Autonomous post failed for {item['title'][:60]!r}: {result.get('error')}")

    logger.info(f"✓ Posting queue drain complete: {len(posted)} posted, {len(skipped)} skipped (duplicate), {len(failed)} failed")
    return {'status': 'success', 'posted': len(posted), 'skipped': len(skipped), 'failed': len(failed)}
