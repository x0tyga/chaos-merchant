"""
Core Pipeline - Main orchestration engine for Chaos Merchant
Sequences agents 1-9 in order with checkpoint/recovery system
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class PipelineStep(Enum):
    """Pipeline execution steps"""
    CLIP_INTELLIGENCE = 1
    SCRIPT_VOICEOVER = 2
    SEO_OPTIMIZER = 3
    VIDEO_PRODUCTION = 4
    THUMBNAIL = 5
    QUALITY_CONTROL = 6
    OUTPUT_PACKAGING = 7
    PIPELINE_AUDIT = 8


class PipelineCheckpoint:
    """Manages checkpoint and recovery data"""
    
    def __init__(self, video_path, checkpoint_dir='./data/checkpoints'):
        self.video_path = Path(video_path)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = self.checkpoint_dir / f"{self.video_path.stem}_checkpoint.json"

    def save(self, step, data):
        """Save checkpoint data"""
        checkpoint = {
            'timestamp': datetime.now().isoformat(),
            'video_path': str(self.video_path),
            'last_completed_step': step.value,
            'step_name': step.name,
            'data': data
        }
        with open(self.checkpoint_file, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        logger.info(f"💾 Checkpoint saved: {step.name}")

    def load(self):
        """Load checkpoint data"""
        if not self.checkpoint_file.exists():
            return None
        
        with open(self.checkpoint_file, 'r') as f:
            checkpoint = json.load(f)
        logger.info(f"📂 Checkpoint loaded: {checkpoint['step_name']}")
        return checkpoint

    def clear(self):
        """Clear checkpoint (video processing complete)"""
        if self.checkpoint_file.exists():
            self.checkpoint_file.unlink()
            logger.info("🧹 Checkpoint cleared")


class Pipeline:
    """Main pipeline orchestrator"""

    def __init__(self, video_path, data_dir='./data', output_dir='./output'):
        self.video_path = Path(video_path)
        self.data_dir = Path(data_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint = PipelineCheckpoint(video_path, checkpoint_dir=str(self.data_dir / 'checkpoints'))
        # Generated once per run, shared by hook library logging and the
        # Step 7 batch folder name, so both refer to the same batch.
        self.batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.processing_log = {
            'video_path': str(video_path),
            'started_at': datetime.now().isoformat(),
            'steps': {}
        }
        self.step_outputs = {}

    def log_step(self, step, status, details=None):
        """Log step execution"""
        self.processing_log['steps'][step.name] = {
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'details': details or {}
        }
        logger.info(f"📊 Step {step.name}: {status}")

    def _save_step_timing(self, batch_folder: str):
        """
        Persists self.processing_log's per-step timing to the packaged
        batch folder as manifests/pipeline_timing.json - this data
        previously only ever existed in-memory (returned by run_pipeline()
        but never written to disk), so nothing that runs after the
        process exits - like the Pipeline Auditor, which reads an
        already-packaged batch folder rather than in-process state, same
        design as core/publisher.py - could see per-step processing times.
        """
        try:
            started_at = self.processing_log.get('started_at')
            total_wall_clock_seconds = None
            if started_at:
                total_wall_clock_seconds = (datetime.now() - datetime.fromisoformat(started_at)).total_seconds()

            timing_data = {
                'batch_id': self.batch_id,
                'video_path': str(self.video_path),
                'started_at': started_at,
                'total_wall_clock_seconds': total_wall_clock_seconds,
                'steps': self.processing_log.get('steps', {})
            }
            timing_path = Path(batch_folder) / 'manifests' / 'pipeline_timing.json'
            timing_path.parent.mkdir(parents=True, exist_ok=True)
            with open(timing_path, 'w') as f:
                json.dump(timing_data, f, indent=2, default=str)
            logger.info(f"✓ Step timing saved: {timing_path}")
        except Exception as e:
            logger.warning(f"⚠ Could not save step timing (non-fatal): {e}")

    def should_recover(self):
        """Check if recovery is needed"""
        checkpoint = self.checkpoint.load()
        return checkpoint is not None

    def get_recovery_step(self):
        """Get the step to resume from"""
        checkpoint = self.checkpoint.load()
        if checkpoint:
            return PipelineStep(checkpoint['last_completed_step'] + 1)
        return PipelineStep.CLIP_INTELLIGENCE

    def _load_trending_topics(self):
        """
        Load real trending topics written by the Trend Intelligence scheduler job
        (agents/trend_intelligence.py -> ./data/trend_intelligence_latest.json).
        Returns [] if no brief has been generated yet (e.g. scheduler hasn't run).
        """
        brief_path = self.data_dir / 'trend_intelligence_latest.json'
        if not brief_path.exists():
            logger.info("ℹ No trend intelligence brief found yet (scheduler may not have run) - proceeding with no trending topics")
            return []

        try:
            with open(brief_path, 'r') as f:
                brief_data = json.load(f)
            top_trends = brief_data.get('brief', {}).get('top_trends', [])
            topics = [t['trend'] for t in top_trends if t.get('trend')]
            logger.info(f"✓ Loaded {len(topics)} real trending topics from trend intelligence")
            return topics
        except Exception as e:
            logger.warning(f"⚠ Failed to load trend intelligence brief: {e}")
            return []

    def _log_hook_usage(self, clip_manifest, voiceover_results, production_result):
        """
        Log every hook that actually made it into a produced short to the
        Hook Library - placeholder logging so the future Analytics agent
        has real usage data (hook text, style, batch, pre-publish viral
        score) to work with once real YouTube performance numbers exist.
        Only logs hooks for shorts CONFIRMED produced
        (production_result['short_results']), not ones that were scripted
        but then failed during video production - a hook that never
        shipped shouldn't be logged as used.
        """
        try:
            from core.memory import HookLibrary
            hook_library = HookLibrary(str(self.data_dir / 'chaos_merchant.db'))
        except Exception as e:
            logger.warning(f"⚠ Hook library unavailable, skipping hook usage logging: {e}")
            return

        clips = clip_manifest.get('clips', [])
        logged = 0
        for short_result in production_result.get('short_results', []):
            short_number = short_result.get('short_number')
            clip_idx = short_result.get('clip_idx')
            if short_number is None or short_number >= len(voiceover_results):
                continue

            clip_voiceover = voiceover_results[short_number]
            if clip_voiceover.get('status') != 'success':
                continue

            hook_text = clip_voiceover.get('script', {}).get('hook', '')
            if not hook_text:
                continue

            clip_data = clips[clip_idx] if clip_idx is not None and clip_idx < len(clips) else {}
            viral_score = clip_data.get('viral_score', 0.0)

            hook_id = hook_library.get_or_create_hook(hook_text, style='opening')
            if hook_id is not None:
                hook_library.log_hook_production(
                    hook_id, batch_id=self.batch_id, viral_score=viral_score,
                    short_id=f"{self.batch_id}_short{short_number}"
                )
                logged += 1

        logger.info(f"✓ Logged {logged} hook(s) to Hook Library for batch {self.batch_id}")

    def _log_channel_memory(self, seo_manifest, voiceover_results, production_result, thumbnail_result):
        """
        Add a channel_shorts row for every short CONFIRMED produced, so
        ChannelMemory.mark_published() (called later by the Publisher module
        once a short is actually uploaded) has a real row to match against
        by title - without this, mark_published()'s title lookup always
        misses and youtube_id/publish_date never get linked. Only logs
        shorts in production_result['short_results'] (confirmed produced),
        same scoping rule as _log_hook_usage.
        """
        try:
            from core.memory import ChannelMemory
            channel_memory = ChannelMemory(str(self.data_dir / 'chaos_merchant.db'))
        except Exception as e:
            logger.warning(f"⚠ Channel memory unavailable, skipping channel memory logging: {e}")
            return

        per_clip_seo = (seo_manifest or {}).get('per_clip', [])
        thumbnails = (thumbnail_result or {}).get('thumbnails', [])
        features_any = production_result.get('metadata', {}).get('features_applied_in_any_short', [])
        caption_style = 'burned_in' if 'captions' in features_any else 'none'

        logged = 0
        for short_result in production_result.get('short_results', []):
            short_number = short_result.get('short_number')
            if short_number is None or short_number >= len(voiceover_results):
                continue

            clip_voiceover = voiceover_results[short_number]
            if clip_voiceover.get('status') != 'success':
                continue

            seo_for_short = per_clip_seo[short_number] if short_number < len(per_clip_seo) else {}
            title = seo_for_short.get('best_title') or clip_voiceover.get('script', {}).get('hook', 'Untitled Short')
            keywords = seo_for_short.get('metadata', {}).get('keywords', [])
            topic = keywords[0] if keywords else 'general'
            script_summary = clip_voiceover.get('script', {}).get('main_content', '')[:300]
            hook_text = clip_voiceover.get('script', {}).get('hook', '')

            thumb_for_short = thumbnails[short_number] if short_number < len(thumbnails) else {}
            thumbnail_style = thumb_for_short.get('status', 'unknown')

            # format_used (the model's own echo of which format it actually
            # wrote in - see script_voiceover.py's generate_script_for_clip())
            # is preferred over format_type (what was requested), since a
            # mismatch there is exactly the signal this session's format
            # pivot needs to catch; falls back to format_type if the model
            # didn't echo one back (e.g. an older/legacy-prompt run).
            format_used = clip_voiceover.get('format_used') or clip_voiceover.get('format_type')

            if channel_memory.add_short(
                title=title, topic=topic, source_video=str(self.video_path),
                script_summary=script_summary, hook_text=hook_text,
                thumbnail_style=thumbnail_style, caption_style=caption_style,
                format_used=format_used
            ):
                logged += 1

        logger.info(f"✓ Logged {logged} short(s) to Channel Memory for batch {self.batch_id}")

    def _load_channel_history(self):
        """
        Load real recently-published topics from Channel Memory (SQLite) to avoid
        repeating content and give the script generator real context.
        Returns [] on a fresh channel (no history yet) or on DB error.
        """
        try:
            from core.memory import ChannelMemory
            channel_memory = ChannelMemory(str(self.data_dir / 'chaos_merchant.db'))
            recent_topics = channel_memory.prevent_topic_repeat(days=14)
            logger.info(f"✓ Loaded {len(recent_topics)} recent topics from channel memory (14-day window)")
            return recent_topics
        except Exception as e:
            logger.warning(f"⚠ Failed to load channel history: {e}")
            return []

    def _write_qc_failure_files(self, qc_inner: dict):
        """
        Writes one plain-text error file per clip that failed QC (video
        validation or caption detection) into the output folder, mirroring
        video_production.py's per-clip production error files - so "why
        didn't Short 2 make it" has the same answer whether Short 2 failed
        during PRODUCTION or during QC: a file sitting right next to where
        its video would have been, not just a line buried in the run's logs.
        Videos/captions in qc_inner are keyed by 'short_number' (see
        quality_control.py's _real_short_number mapping), which is what
        video_production.py's error files are also named after.
        """
        by_short = {}
        for v in qc_inner.get('videos', []):
            if v.get('validation', {}).get('status') == 'error':
                num = v.get('short_number', v.get('index'))
                by_short.setdefault(num, []).append(
                    f"Video validation FAILED: {'; '.join(v['validation'].get('errors', []))}"
                )
        for c in qc_inner.get('captions', []):
            if c.get('details', {}).get('result') == 'FAIL':
                num = c.get('short_number', c.get('index'))
                conf = c.get('details', {}).get('confidence', 0)
                by_short.setdefault(num, []).append(
                    f"Caption presence check FAILED: only {conf:.0%} of sampled frames showed "
                    f"caption-like content (need >=60%)"
                )
        for s in qc_inner.get('content_similarity', []):
            if s.get('result') == 'FAIL':
                num = s.get('short_number')
                if num is not None:
                    by_short.setdefault(num, []).append(
                        f"Content similarity FAILED: {s.get('highest_similarity', 0):.0%} similar to "
                        f"recently published short '{(s.get('similar_short') or {}).get('title', '?')}'"
                    )

        for short_number, reasons in by_short.items():
            try:
                error_path = self.output_dir / f"video_{self.video_path.stem}_{short_number:03d}_QC_ERROR.txt"
                error_path.write_text(
                    f"SHORT FAILED QUALITY CONTROL\n"
                    f"=============================\n"
                    f"Short number: {short_number + 1}\n"
                    f"Source video: {self.video_path}\n"
                    f"Checked at: {datetime.now().isoformat()}\n\n"
                    f"Reason(s):\n" + "\n".join(f"- {r}" for r in reasons) + "\n\n"
                    f"The video file itself was still produced and packaged - this Short "
                    f"needs manual review before publishing rather than being silently "
                    f"dropped. See the QC manifest for full detail on every check run.\n"
                )
                logger.info(f"📄 Wrote QC failure explanation: {error_path.name}")
            except Exception:
                logger.exception(f"⚠ Could not write QC failure file for short {short_number}")

    def run(self):
        """
        Execute the complete pipeline
        
        Returns:
            dict: Processing results
        """
        logger.info(f"🎬 Starting pipeline for: {self.video_path.name}")
        
        # Check for recovery
        if self.should_recover():
            recovery_step = self.get_recovery_step()
            logger.warning(f"⚠️  Recovering from checkpoint. Resuming at: {recovery_step.name}")
        
        try:
            # Step 1: Clip Intelligence
            logger.info("Step 1/7: Clip Intelligence Analysis")
            self.log_step(PipelineStep.CLIP_INTELLIGENCE, 'in_progress')
            
            from agents.clip_intelligence import analyze_video
            clip_manifest = analyze_video(str(self.video_path), num_clips=7)
            self.step_outputs['clip_intelligence'] = clip_manifest
            
            # Save clip manifest
            manifest_path = self.output_dir / f"{self.video_path.stem}_clip_manifest.json"
            with open(manifest_path, 'w') as f:
                json.dump(clip_manifest, f, indent=2)
            
            self.checkpoint.save(PipelineStep.CLIP_INTELLIGENCE, {'manifest_path': str(manifest_path)})
            self.log_step(PipelineStep.CLIP_INTELLIGENCE, 'complete', {'clips_found': len(clip_manifest['clips']), 'top_clips': len(clip_manifest['top_clip_indices'])})
            
            # Step 2: Script + Voiceover (per-clip)
            # Each of the 7 shorts gets its OWN script and voice recording
            # matching that specific clip's content, instead of one shared
            # script/audio file muxed onto all 7 regardless of what's
            # actually on screen for each one.
            logger.info("Step 2/7: Script Generation + Voiceover (per-clip)")
            self.log_step(PipelineStep.SCRIPT_VOICEOVER, 'in_progress')

            from agents.script_voiceover import generate_voiceover_for_clip, get_clip_description
            from agents.format_selector import select_format_for_clip

            trending_topics = self._load_trending_topics()
            channel_history = self._load_channel_history()

            top_clip_indices = clip_manifest.get('top_clip_indices', [])
            clips = clip_manifest.get('clips', [])

            # Lightweight (metadata-only, no vision call) summary of every
            # selected clip in this batch - passed as 'other_clips_context'
            # to whichever clips end up scripted as Ranking/Comparison, so
            # those formats can reference the rest of the batch ("beating
            # out #4...") without needing a full vision description of
            # clips this iteration hasn't reached yet.
            batch_clip_summaries = [
                {
                    'clip_index': i,
                    'duration': round(clips[clip_idx].get('duration', 0), 1) if clip_idx < len(clips) else 0,
                    'engagement_score': round(clips[clip_idx].get('engagement_score', 0), 2) if clip_idx < len(clips) else 0,
                }
                for i, clip_idx in enumerate(top_clip_indices)
            ]

            voiceover_results = []
            for i, clip_idx in enumerate(top_clip_indices):
                clip_data = clips[clip_idx] if clip_idx < len(clips) else {}
                try:
                    # Content description is needed BEFORE format selection
                    # (the selector judges partly on what's actually on
                    # screen) - computed once here and passed through so
                    # generate_voiceover_for_clip() doesn't re-run the same
                    # vision call a second time.
                    clip_description = get_clip_description(clip_data, i, str(self.video_path))

                    format_type, format_rationale = select_format_for_clip(
                        clip_data, clip_description=clip_description, trending_topics=trending_topics
                    )
                    logger.info(f"✓ Clip {i + 1}/{len(top_clip_indices)}: format '{format_type}' ({format_rationale})")

                    other_clips_context = None
                    if format_type in ('ranking', 'comparison'):
                        other_clips_context = [s for s in batch_clip_summaries if s['clip_index'] != i]

                    vr = generate_voiceover_for_clip(
                        clip_data, i,
                        trending_topics=trending_topics,
                        channel_history=channel_history,
                        # Lets the script generator extract keyframes from
                        # this clip's actual segment and react to what is
                        # literally on screen, instead of generating blind
                        # from engagement scores.
                        source_video_path=str(self.video_path),
                        clip_description=clip_description,
                        format_type=format_type,
                        other_clips_context=other_clips_context
                    )
                    voiceover_results.append(vr)
                except Exception as e:
                    logger.error(f"❌ Voiceover generation failed for clip {i + 1}/{len(top_clip_indices)}: {e}")
                    voiceover_results.append({'status': 'error', 'clip_index': i, 'error': str(e)})

            self.step_outputs['script_voiceover'] = voiceover_results

            # Save voiceover metadata (now a list, one entry per clip)
            voiceover_path = self.output_dir / f"{self.video_path.stem}_voiceover_metadata.json"
            with open(voiceover_path, 'w') as f:
                json.dump(voiceover_results, f, indent=2)

            voiceover_succeeded = len([v for v in voiceover_results if v.get('status') == 'success'])
            self.checkpoint.save(PipelineStep.SCRIPT_VOICEOVER, {'voiceover_path': str(voiceover_path)})
            self.log_step(PipelineStep.SCRIPT_VOICEOVER, 'complete', {
                'clips_processed': len(voiceover_results),
                'succeeded': voiceover_succeeded
            })

            if voiceover_succeeded == 0:
                raise Exception("Script + Voiceover generation failed for every clip - cannot produce any shorts")

            # Step 3: SEO Optimizer (per-clip)
            # Each short's keywords/description/hashtags are generated from
            # its OWN clip content and script, not one shared set copied
            # across all 7. optimize_seo() itself didn't need to change -
            # it already accepted single-clip data; only this caller did.
            logger.info("Step 3/7: SEO Optimization (per-clip)")
            self.log_step(PipelineStep.SEO_OPTIMIZER, 'in_progress')

            from agents.seo_optimizer import optimize_seo

            seo_results = []
            for i, clip_idx in enumerate(top_clip_indices):
                clip_data = clips[clip_idx] if clip_idx < len(clips) else {}
                clip_voiceover = voiceover_results[i] if i < len(voiceover_results) else {}
                try:
                    sr = optimize_seo(clip_data, clip_voiceover, trending_topics=trending_topics)
                    seo_results.append(sr)
                except Exception as e:
                    logger.error(f"❌ SEO optimization failed for clip {i + 1}/{len(top_clip_indices)}: {e}")
                    seo_results.append({'status': 'error', 'clip_index': i, 'error': str(e)})

            # Backward-compatible top-level shape (best_title/metadata),
            # taken from the first successful clip, for consumers that
            # expect a single SEO result (e.g. QC's REQUIRED_FIELDS_SEO
            # presence check). 'per_clip' is the real, authoritative
            # per-short data that output_packaging/thumbnail generation use.
            first_success = next((r for r in seo_results if r.get('status') == 'success'), {})
            seo_result = {
                'status': 'success' if first_success else 'error',
                'best_title': first_success.get('best_title', ''),
                'metadata': first_success.get('metadata', {}),
                'per_clip': seo_results,
                'timestamp': datetime.now().isoformat()
            }
            self.step_outputs['seo_optimizer'] = seo_result

            # Save SEO metadata
            seo_path = self.output_dir / f"{self.video_path.stem}_seo_metadata.json"
            with open(seo_path, 'w') as f:
                json.dump(seo_result, f, indent=2)

            seo_succeeded = len([r for r in seo_results if r.get('status') == 'success'])
            self.checkpoint.save(PipelineStep.SEO_OPTIMIZER, {'seo_path': str(seo_path)})
            self.log_step(PipelineStep.SEO_OPTIMIZER, 'complete', {
                'clips_processed': len(seo_results),
                'succeeded': seo_succeeded,
                'best_title': seo_result.get('best_title')
            })

            # Step 4: Video Production
            logger.info("Step 4/7: Video Production")
            self.log_step(PipelineStep.VIDEO_PRODUCTION, 'in_progress')

            from agents.video_production import produce_shorts

            production_result = produce_shorts(
                source_video_path=str(self.video_path),
                clip_manifest=self.step_outputs['clip_intelligence'],
                voiceover_results=self.step_outputs['script_voiceover'],
                output_dir=str(self.output_dir),
                temp_dir=str(self.output_dir / 'temp')
            )
            self.step_outputs['video_production'] = production_result

            # Save video manifest
            video_manifest_path = self.output_dir / f"{self.video_path.stem}_video_manifest.json"
            with open(video_manifest_path, 'w') as f:
                json.dump(production_result, f, indent=2)

            self.checkpoint.save(PipelineStep.VIDEO_PRODUCTION, {
                'manifest_path': str(video_manifest_path),
                'video_count': len(production_result.get('video_paths', []))
            })
            self.log_step(PipelineStep.VIDEO_PRODUCTION, 'complete', {
                'videos_produced': len(production_result.get('video_paths', [])),
                'total_time': production_result.get('processing_times', {}).get('export_total', 0)
            })

            self._log_hook_usage(clip_manifest, self.step_outputs['script_voiceover'], production_result)

            # Step 5: Thumbnail Generation
            logger.info("Step 5/7: Thumbnail Generation")
            self.log_step(PipelineStep.THUMBNAIL, 'in_progress')

            from agents.thumbnail import generate_thumbnails

            thumbnail_result = generate_thumbnails(
                clip_manifest=self.step_outputs['clip_intelligence'],
                seo_manifest=self.step_outputs['seo_optimizer'],
                voiceover_results=self.step_outputs['script_voiceover'],
                output_dir=str(self.output_dir)
            )
            self.step_outputs['thumbnail'] = thumbnail_result

            # Save thumbnail manifest
            thumbnail_manifest_path = self.output_dir / f"{self.video_path.stem}_thumbnail_manifest.json"
            with open(thumbnail_manifest_path, 'w') as f:
                json.dump(thumbnail_result, f, indent=2)

            self.checkpoint.save(PipelineStep.THUMBNAIL, {
                'manifest_path': str(thumbnail_manifest_path),
                'generated_count': thumbnail_result.get('generated_count', 0),
                'brief_only_count': thumbnail_result.get('brief_only_count', 0)
            })
            self.log_step(PipelineStep.THUMBNAIL, 'complete', {
                'generated': thumbnail_result.get('generated_count', 0),
                'brief_only': thumbnail_result.get('brief_only_count', 0)
            })

            self._log_channel_memory(
                self.step_outputs['seo_optimizer'], self.step_outputs['script_voiceover'],
                production_result, thumbnail_result
            )

            # Step 6: Quality Control
            logger.info("Step 6/7: Quality Control")
            self.log_step(PipelineStep.QUALITY_CONTROL, 'in_progress')

            from agents.quality_control import perform_quality_control

            qc_result = perform_quality_control(
                clip_manifest=self.step_outputs['clip_intelligence'],
                seo_manifest=self.step_outputs['seo_optimizer'],
                video_manifest=self.step_outputs['video_production'],
                thumbnail_manifest=self.step_outputs['thumbnail'],
                output_dir=str(self.output_dir),
                video_base_name=self.video_path.stem
            )
            self.step_outputs['quality_control'] = qc_result

            # Save QC manifest
            qc_manifest_path = self.output_dir / f"{self.video_path.stem}_qc_manifest.json"
            with open(qc_manifest_path, 'w') as f:
                json.dump(qc_result, f, indent=2)

            self.checkpoint.save(PipelineStep.QUALITY_CONTROL, {
                'manifest_path': str(qc_manifest_path),
                'status': qc_result.get('status'),
                'routing': qc_result.get('routing')
            })

            # NOTE: this used to `raise Exception(...)` here whenever ANY
            # single clip in the batch failed QC, which aborted the entire
            # pipeline run before Step 7 ever executed - meaning if 1 of 3
            # clips had a QC issue (e.g. a caption-detection false positive,
            # or a content-similarity collision on just that clip's title),
            # the OTHER 2 good clips never got packaged either. That's
            # backwards from the documented "route bad content to manual
            # review" design (see CLAUDE.md's QC section) - manual review
            # should happen on packaged output, not replace packaging
            # entirely. QC failures are now logged loudly (with the actual
            # nested errors, not the wrong top-level key this used to read)
            # and per-clip QC failure files are written, but the batch
            # still proceeds to packaging so a bad clip can't take the good
            # ones down with it.
            qc_inner = qc_result.get('qc_result', {}) or {}
            real_errors = qc_inner.get('issues', {}).get('errors', [])
            self._write_qc_failure_files(qc_inner)

            if qc_result.get('status') == 'error':
                logger.error(f"❌ QC validation found {len(real_errors)} error(s) - routing to manual review:")
                for err in real_errors:
                    logger.error(f"   - {err}")
                self.log_step(PipelineStep.QUALITY_CONTROL, 'failed', {
                    'errors': real_errors,
                    'routing': 'manual_review'
                })
            else:
                self.log_step(PipelineStep.QUALITY_CONTROL, 'complete', {
                    'status': qc_result.get('status'),
                    'warnings': len(qc_inner.get('issues', {}).get('warnings', [])),
                    'routing': qc_result.get('routing')
                })

            # Step 7: Output Packaging
            logger.info("Step 7/7: Output Packaging")
            self.log_step(PipelineStep.OUTPUT_PACKAGING, 'in_progress')

            from agents.output_packaging import package_outputs

            packaging_result = package_outputs(
                clip_manifest=self.step_outputs['clip_intelligence'],
                seo_manifest=self.step_outputs['seo_optimizer'],
                video_manifest=self.step_outputs['video_production'],
                thumbnail_manifest=self.step_outputs['thumbnail'],
                qc_result=self.step_outputs['quality_control'],
                output_dir=str(self.output_dir),
                video_base_name=self.video_path.stem,
                batch_id=self.batch_id
            )
            self.step_outputs['output_packaging'] = packaging_result

            # Save packaging manifest
            packaging_manifest_path = self.output_dir / f"{self.video_path.stem}_packaging_manifest.json"
            with open(packaging_manifest_path, 'w') as f:
                json.dump(packaging_result, f, indent=2)

            self.checkpoint.save(PipelineStep.OUTPUT_PACKAGING, {
                'manifest_path': str(packaging_manifest_path),
                'batch_folder': packaging_result.get('batch_folder'),
                'batch_id': packaging_result.get('batch_id')
            })

            self.log_step(PipelineStep.OUTPUT_PACKAGING, 'complete', {
                'batch_id': packaging_result.get('batch_id'),
                'videos_organized': packaging_result.get('packaging_result', {}).get('videos_organized'),
                'ready_for_upload': packaging_result.get('ready_for_upload')
            })

            # Step 8: Pipeline Audit - analyzes the just-packaged batch and
            # writes audit_report.md/audit_log.json into the batch folder.
            # Runs automatically, no manual trigger. A failure here (Claude
            # unavailable, unexpected manifest shape, etc.) must never fail
            # the overall pipeline run - the batch is already fully
            # produced and packaged by this point, the audit is a QA layer
            # on top of a result that already succeeded.
            logger.info("Step 8/8: Pipeline Audit")
            self.log_step(PipelineStep.PIPELINE_AUDIT, 'in_progress')
            try:
                batch_folder = packaging_result.get('batch_folder')
                if batch_folder:
                    self._save_step_timing(batch_folder)

                    from agents.pipeline_auditor import audit_batch
                    audit_result = audit_batch(batch_folder)
                    self.step_outputs['pipeline_audit'] = audit_result

                    if audit_result.get('status') == 'success':
                        self.log_step(PipelineStep.PIPELINE_AUDIT, 'complete', {
                            'overall_score': audit_result.get('overall_score'),
                            'overall_status': audit_result.get('overall_status')
                        })
                    else:
                        self.log_step(PipelineStep.PIPELINE_AUDIT, 'failed', {
                            'error': audit_result.get('error')
                        })
                else:
                    logger.warning("⚠ No batch_folder from packaging result, skipping audit")
                    self.log_step(PipelineStep.PIPELINE_AUDIT, 'skipped', {'reason': 'no batch_folder'})
            except Exception as e:
                logger.exception("❌ Pipeline audit failed (non-fatal, batch was already produced successfully)")
                self.log_step(PipelineStep.PIPELINE_AUDIT, 'failed', {'error': str(e)})

            # Pipeline complete
            logger.info("✅ Pipeline complete!")
            self.checkpoint.clear()
            self.processing_log['completed_at'] = datetime.now().isoformat()
            self.processing_log['status'] = 'success'
            
            return {
                'status': 'success',
                'video_path': str(self.video_path),
                'processing_log': self.processing_log,
                'step_outputs': self.step_outputs
            }
            
        except Exception as e:
            # Full traceback, not just str(e) - this is the top-level catch
            # for the whole pipeline run, including Video Production (Step
            # 4), where a corrupt/interrupted ffmpeg export previously
            # surfaced here as a bare one-line message with no indication
            # of which step or which underlying call actually failed.
            logger.exception("❌ Pipeline failed")
            self.processing_log['status'] = 'failed'
            self.processing_log['error'] = str(e)
            raise


def run_pipeline(video_path):
    """
    Convenience function to run the pipeline.
    Reads DATA_DIR / OUTPUT_DIR from the environment (set in .env) so
    configured paths actually take effect, falling back to ./data and
    ./output if unset.

    Args:
        video_path: Path to video file

    Returns:
        dict: Pipeline results
    """
    import os
    data_dir = os.getenv('DATA_DIR', './data')
    output_dir = os.getenv('OUTPUT_DIR', './output')
    pipeline = Pipeline(video_path, data_dir=data_dir, output_dir=output_dir)
    return pipeline.run()
