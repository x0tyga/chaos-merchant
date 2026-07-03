"""
Pipeline Auditor - Step 8 (post-packaging QA layer)

Runs automatically right after Output Packaging completes - no manual
trigger needed. Reads the already-packaged batch folder's real manifests
(the same way core/publisher.py reads a batch to upload it), computes a
deterministic red/yellow/green status and 0-100 score per Short from real
technical checks (duration, audio level, caption presence, effects
applied, file size, processing time), then makes ONE Claude Haiku call
across the WHOLE batch (not per-short) to turn those metrics into a
plain-English audit_report.md a non-technical person can read - plus a
machine-readable audit_log.json for the dashboard's Audit tab.

Scoring is always computed in code from real checks, never left to the
LLM to invent - so scores stay comparable across batches on the
dashboard's historical chart. Claude's only job is writing the plain-
English narrative and specific suggestions from those already-computed
numbers.

Degrades gracefully: if Claude is unavailable, audit_report.md still gets
written from a code-generated fallback built from the same real metrics
(less polished prose, same real numbers) - a batch is never left without
an audit report just because the API call failed. If pydub or a specific
manifest is missing, that one signal is reported as 'unknown' rather than
crashing the whole audit.

Can be re-run standalone: python -m agents.pipeline_auditor <batch_folder>
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("pydub not available - audio level checks will be skipped (pip install pydub)")

from anthropic import Anthropic

from core.cost_tracker import log_anthropic_usage

# Deterministic thresholds - same rubric every batch, so scores stay
# comparable over time on the dashboard's historical chart rather than
# drifting with LLM phrasing/mood.
AUDIO_LEVEL_MIN_DBFS = -30.0   # below this: too quiet to hear comfortably
AUDIO_LEVEL_MAX_DBFS = -6.0    # above this: clipping/too loud risk
AUDIO_LEVEL_IDEAL_MIN = -20.0
AUDIO_LEVEL_IDEAL_MAX = -12.0
SLOW_PROCESSING_MULTIPLIER = 1.5  # >1.5x the batch's own average = flagged slow

STATUS_WEIGHTS = {'pass': 1.0, 'warn': 0.5, 'fail': 0.0}
EXPECTED_FEATURES = ['captions', 'audio_ducking', 'color_grading', 'branding']

STATUS_EMOJI = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}


class MetricsGatherer:
    """Reads a packaged batch folder's real manifests and computes deterministic per-short metrics."""

    def __init__(self, batch_folder: str):
        self.batch_folder = Path(batch_folder)
        self.manifests_dir = self.batch_folder / 'manifests'
        self.shorts_dir = self.batch_folder / 'shorts'
        self.upload_metadata_dir = self.batch_folder / 'upload_metadata'

    @staticmethod
    def _read_json(path: Path, default=None):
        if not path.exists():
            return default
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠ Could not read {path}: {e}")
            return default

    def gather(self) -> Dict:
        batch_manifest = self._read_json(self.manifests_dir / 'BATCH_MANIFEST.json', {}) or {}
        qc_manifest = self._read_json(self.manifests_dir / 'qc_manifest.json', {}) or {}
        video_manifest = self._read_json(self.manifests_dir / 'video_manifest.json', {}) or {}
        timing_manifest = self._read_json(self.manifests_dir / 'pipeline_timing.json', {}) or {}

        qc_videos = qc_manifest.get('videos', [])
        qc_captions = qc_manifest.get('captions', [])
        per_short_processing = video_manifest.get('processing_times', {}).get('per_short', {})
        short_features = video_manifest.get('short_features', {})
        short_results = video_manifest.get('short_results', [])
        # per_short_processing is keyed by clip_idx (string), not
        # short_number - build the mapping so a short's own timing can be
        # found regardless of which clips succeeded/failed elsewhere.
        clip_idx_to_short_number = {
            str(r['clip_idx']): r['short_number'] for r in short_results
            if r.get('clip_idx') is not None and r.get('short_number') is not None
        }
        short_number_to_clip_idx = {v: k for k, v in clip_idx_to_short_number.items()}

        avg_processing_time = (
            sum(per_short_processing.values()) / len(per_short_processing)
            if per_short_processing else 0
        )

        shorts = []
        metadata_files = sorted(self.upload_metadata_dir.glob('*.json')) if self.upload_metadata_dir.exists() else []
        for i, filename in enumerate(metadata_files):
            meta = self._read_json(filename, {}) or {}
            short_index = meta.get('short_index', i + 1)
            short_number = short_index - 1  # upload_metadata is 1-indexed, short_number is 0-indexed

            video_path = self.shorts_dir / meta.get('file', f'short_{short_index:03d}.mp4')
            qc_video = qc_videos[i] if i < len(qc_videos) else {}
            qc_caption = qc_captions[i] if i < len(qc_captions) else {}
            vmeta = (qc_video.get('validation') or {}).get('metadata', {})
            vchecks = {c['check']: c for c in (qc_video.get('validation') or {}).get('checks', [])}
            caption_details = qc_caption.get('details', {}) or {}

            audio_level = self._measure_audio_level(video_path)

            clip_idx_key = short_number_to_clip_idx.get(short_number)
            processing_time = per_short_processing.get(clip_idx_key) if clip_idx_key else None

            effects_applied = short_features.get(str(short_number), [])

            shorts.append({
                'short_number': short_number,
                'title': meta.get('title', f'Short {short_index}'),
                'file': meta.get('file'),
                'duration_seconds': vmeta.get('duration'),
                'duration_status': vchecks.get('duration', {}).get('result', 'UNKNOWN').lower(),
                'file_size_mb': vmeta.get('file_size_mb'),
                'file_size_status': vchecks.get('file_size', {}).get('result', 'UNKNOWN').lower(),
                'resolution': f"{vmeta.get('width')}x{vmeta.get('height')}" if vmeta.get('width') else None,
                'resolution_status': vchecks.get('resolution', {}).get('result', 'UNKNOWN').lower(),
                'audio_sync_status': vchecks.get('audio_sync', {}).get('result', 'UNKNOWN').lower(),
                'audio_level_dbfs': audio_level,
                'audio_level_status': self._audio_level_status(audio_level),
                'captions_detected': caption_details.get('result') == 'PASS',
                'captions_confidence': caption_details.get('confidence'),
                'captions_status': caption_details.get('result', 'UNKNOWN').lower(),
                'effects_applied': effects_applied,
                'effects_status': 'pass' if len(effects_applied) == len(EXPECTED_FEATURES)
                                   else ('warn' if effects_applied else 'fail'),
                'processing_time_seconds': processing_time,
                'processing_time_status': self._processing_time_status(processing_time, avg_processing_time),
            })

        return {
            'batch_id': batch_manifest.get('batch_id', self.batch_folder.name),
            'video_count': batch_manifest.get('video_count', len(shorts)),
            'qc_status': batch_manifest.get('status', 'unknown'),
            'shorts': shorts,
            'step_timings': timing_manifest.get('steps', {}),
            'total_wall_clock_seconds': timing_manifest.get('total_wall_clock_seconds'),
        }

    @staticmethod
    def _measure_audio_level(video_path: Path) -> Optional[float]:
        if not PYDUB_AVAILABLE or not video_path.exists():
            return None
        try:
            audio = AudioSegment.from_file(str(video_path))
            return round(audio.dBFS, 1)
        except Exception as e:
            logger.warning(f"⚠ Could not measure audio level for {video_path.name}: {e}")
            return None

    @staticmethod
    def _audio_level_status(dbfs: Optional[float]) -> str:
        if dbfs is None:
            return 'unknown'
        if dbfs < AUDIO_LEVEL_MIN_DBFS or dbfs > AUDIO_LEVEL_MAX_DBFS:
            return 'fail'
        if dbfs < AUDIO_LEVEL_IDEAL_MIN or dbfs > AUDIO_LEVEL_IDEAL_MAX:
            return 'warn'
        return 'pass'

    @staticmethod
    def _processing_time_status(seconds: Optional[float], batch_average: float) -> str:
        if seconds is None or not batch_average:
            return 'unknown'
        if seconds > batch_average * SLOW_PROCESSING_MULTIPLIER:
            return 'warn'
        return 'pass'


def _score_short(short: Dict) -> Dict:
    """
    Deterministic 0-100 score + red/yellow/green status from the real
    checks gathered above - never left to the LLM, so scores stay
    comparable across batches over time on the dashboard's chart.
    'unknown' checks (a signal that couldn't be measured, e.g. pydub
    missing) are excluded from the score rather than counted against it.
    """
    checks = [
        short['duration_status'], short['file_size_status'], short['resolution_status'],
        short['audio_sync_status'], short['audio_level_status'], short['captions_status'],
        short['effects_status'], short['processing_time_status']
    ]
    weights = [STATUS_WEIGHTS[c] for c in checks if c in STATUS_WEIGHTS]
    score = round((sum(weights) / len(weights)) * 100) if weights else 0
    has_fail = any(c == 'fail' for c in checks)

    issues = []
    if short['duration_status'] == 'fail':
        issues.append(f"Duration was off ({short['duration_seconds']}s)")
    if short['file_size_status'] == 'fail':
        issues.append(f"File size was unusual ({short['file_size_mb']}MB)")
    if short['resolution_status'] == 'fail':
        issues.append(f"Wrong video size ({short['resolution']})")
    if short['audio_sync_status'] == 'fail':
        issues.append("Audio didn't line up with the video")
    if short['audio_level_status'] == 'fail':
        issues.append("Audio volume was too quiet or too loud")
    elif short['audio_level_status'] == 'warn':
        issues.append("Audio volume was outside the ideal range")
    if short['captions_status'] == 'fail':
        issues.append("Captions did not appear to show up on screen")
    elif short['captions_status'] == 'warn':
        issues.append("Captions may be inconsistent")
    if short['effects_status'] == 'fail':
        issues.append("None of the visual effects (captions, ducking, color grading, branding) applied")
    elif short['effects_status'] == 'warn':
        missing = [f for f in EXPECTED_FEATURES if f not in short['effects_applied']]
        issues.append(f"Some visual effects didn't apply: {', '.join(missing)}")
    if short['processing_time_status'] == 'warn':
        issues.append(f"Took longer than usual to process ({short['processing_time_seconds']}s)")

    if has_fail or score < 60:
        status = 'red'
    elif score < 85:
        status = 'yellow'
    else:
        status = 'green'

    return {'score': score, 'status': status, 'issues': issues}


class AuditReportGenerator:
    """Turns deterministic per-short metrics into a plain-English report via ONE Claude Haiku call for the whole batch."""

    def __init__(self):
        self.client = Anthropic()

    def generate(self, batch_metrics: Dict) -> Dict:
        prompt = f"""You are writing a quality report for a non-technical person who runs
an automated video production pipeline. They do not know technical terms
like "codec," "dBFS," "resolution," or "sync tolerance" - explain
everything in plain English, like you're texting a friend a summary.

Here is the automated technical analysis of a batch of {len(batch_metrics['shorts'])} YouTube Shorts that were just produced:

{json.dumps(batch_metrics, indent=2, default=str)[:6000]}

Write a plain-English audit report in Markdown with these sections:

## Overall Summary
One short paragraph: what worked, what didn't, in plain language.

## Each Short
A short subsection per Short (use its title as the heading) - one or two
plain-English sentences about how it turned out. Call out anything that
looked wrong or was slow. If everything looks good, say so briefly and
move on - don't pad a good result with filler.

## What To Do Next
Specific, actionable suggestions (e.g. "the audio on Short 3 was too
quiet - check the source video's audio levels before the next run" not
"audio_level_status was warn"). If everything looks good, say there's
nothing to fix right now.

Rules:
- NO jargon: never say "dBFS," "codec," "resolution check," "sync" -
  describe what a normal person would actually notice instead (e.g. "the
  video plays at the right size" not "resolution check passed")
- Be direct and honest - if something looks wrong, say so clearly, don't
  soften it into meaninglessness
- Keep it skimmable - short paragraphs and bullet points, not walls of text
- Translate the numbers into what they MEAN, don't just repeat them

Output ONLY the Markdown for these three sections, no preamble, no title
(a title/status table is added separately)."""

        try:
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            log_anthropic_usage('pipeline_auditor', response)
            markdown = response.content[0].text.strip()
            return {'status': 'success', 'markdown': markdown}
        except Exception as e:
            logger.warning(f"⚠ Audit report AI writer unavailable, using plain fallback: {e}")
            return {'status': 'error', 'markdown': self._fallback_markdown(batch_metrics), 'error': str(e)}

    @staticmethod
    def _fallback_markdown(batch_metrics: Dict) -> str:
        """Plain but real fallback built from the same computed metrics, used only if Claude is unavailable."""
        lines = ['## Overall Summary', '', '_AI writer was unavailable for this batch - showing the raw automated checks instead._', '']
        for s in batch_metrics['shorts']:
            lines.append(f"## {s['title']}")
            lines.append(f"Status: {s['status'].upper()} (score {s['score']}/100)")
            if s['issues']:
                for issue in s['issues']:
                    lines.append(f"- {issue}")
            else:
                lines.append("- No issues found.")
            lines.append('')
        lines.append('## What To Do Next')
        all_issues = [issue for s in batch_metrics['shorts'] for issue in s['issues']]
        if all_issues:
            lines.extend(f"- {issue}" for issue in all_issues)
        else:
            lines.append("- Nothing to fix right now.")
        return '\n'.join(lines)


class PipelineAuditor:
    """Main orchestrator - gathers metrics, scores them, writes audit_report.md + audit_log.json."""

    def __init__(self, batch_folder: str):
        self.batch_folder = Path(batch_folder)
        self.gatherer = MetricsGatherer(batch_folder)
        self.report_generator = AuditReportGenerator()

    def run(self) -> Dict:
        logger.info("=" * 70)
        logger.info("🔍 PIPELINE AUDITOR - Analyzing batch output")
        logger.info("=" * 70)

        raw = self.gatherer.gather()

        scored_shorts = []
        for s in raw['shorts']:
            scoring = _score_short(s)
            s.update(scoring)
            scored_shorts.append(s)
            logger.info(f"  {STATUS_EMOJI[s['status']]} {s['title']}: {s['score']}/100 ({s['status'].upper()})")

        overall_score = round(sum(s['score'] for s in scored_shorts) / len(scored_shorts)) if scored_shorts else 0
        overall_status = 'green' if overall_score >= 85 and not any(s['status'] == 'red' for s in scored_shorts) \
            else ('red' if overall_score < 60 or any(s['status'] == 'red' for s in scored_shorts) else 'yellow')

        batch_metrics = {
            'batch_id': raw['batch_id'],
            'generated_at': datetime.now().isoformat(),
            'overall_score': overall_score,
            'overall_status': overall_status,
            'shorts': scored_shorts,
            'step_timings': raw['step_timings'],
            'total_wall_clock_seconds': raw['total_wall_clock_seconds'],
        }

        report = self.report_generator.generate(batch_metrics)
        batch_metrics['claude_status'] = report['status']

        full_markdown = self._build_full_report(batch_metrics, report['markdown'])
        report_path = self.batch_folder / 'audit_report.md'
        report_path.write_text(full_markdown)

        log_path = self.batch_folder / 'audit_log.json'
        with open(log_path, 'w') as f:
            json.dump(batch_metrics, f, indent=2, default=str)

        logger.info(f"✓ Audit complete: batch score {overall_score}/100 ({overall_status.upper()})")
        logger.info(f"✓ audit_report.md and audit_log.json written to {self.batch_folder}")
        logger.info("=" * 70)

        return {
            'status': 'success',
            'batch_id': raw['batch_id'],
            'overall_score': overall_score,
            'overall_status': overall_status,
            'report_path': str(report_path),
            'log_path': str(log_path)
        }

    @staticmethod
    def _build_full_report(batch_metrics: Dict, narrative_markdown: str) -> str:
        """
        Prepends a code-generated (never wrong, no extra API cost) status
        table to Claude's narrative, so the raw .md file is self-sufficient
        even without the dashboard - a non-technical person opening it
        directly still sees a clear at-a-glance status per Short.
        """
        lines = [
            f"# Batch Audit Report - {batch_metrics['batch_id']}",
            '',
            f"Generated: {batch_metrics['generated_at']}",
            f"Overall: {STATUS_EMOJI[batch_metrics['overall_status']]} {batch_metrics['overall_status'].upper()} ({batch_metrics['overall_score']}/100)",
            '',
            '## At a Glance',
            '',
            '| Short | Status | Score |',
            '|---|---|---|'
        ]
        for s in batch_metrics['shorts']:
            lines.append(f"| {s['title']} | {STATUS_EMOJI[s['status']]} {s['status'].upper()} | {s['score']}/100 |")
        lines.append('')
        lines.append(narrative_markdown)
        return '\n'.join(lines)


def audit_batch(batch_folder: str) -> Dict:
    """Main entry point - called by core/pipeline.py right after Output Packaging, or standalone."""
    try:
        auditor = PipelineAuditor(batch_folder)
        return auditor.run()
    except Exception as e:
        logger.error(f"❌ Pipeline audit failed: {e}")
        return {'status': 'error', 'error': str(e)}


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python -m agents.pipeline_auditor <batch_folder>")
        sys.exit(1)
    result = audit_batch(sys.argv[1])
    print(json.dumps(result, indent=2, default=str))
