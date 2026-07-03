"""
Output Packaging Agent - Step 9
Creates clean, organized upload-ready folder with zero confusion
Batch summary readable in 30 seconds; exact upload order specified
"""

import json
import logging
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger(__name__)


class BatchSummaryGenerator:
    """Generates 30-second-readable batch summary"""

    @staticmethod
    def _aggregate_video_check(qc_inner: Dict, check_name: str) -> str:
        """Aggregate a per-video check (e.g. 'resolution', 'duration', 'audio_sync') across all videos"""
        videos = qc_inner.get('videos', [])
        results = []
        for v in videos:
            for check in v.get('validation', {}).get('checks', []):
                if check.get('check') == check_name:
                    results.append(check.get('result', 'UNKNOWN'))

        if not results:
            return "⊗ NOT CHECKED"
        if any(r == 'FAIL' for r in results):
            failed = sum(1 for r in results if r == 'FAIL')
            return f"❌ FAIL ({failed}/{len(results)} videos)"
        if any(r == 'WARN' for r in results):
            warned = sum(1 for r in results if r == 'WARN')
            return f"⚠️ WARN ({warned}/{len(results)} videos)"
        return f"✅ PASS ({len(results)}/{len(results)} videos)"

    @staticmethod
    def _aggregate_codec_check(qc_inner: Dict) -> str:
        """Codec/audio_codec are validated as part of the video_production metadata check"""
        for meta_val in qc_inner.get('metadata', []):
            if meta_val.get('manifest_type') == 'video_production':
                codec_errors = [e for e in meta_val.get('errors', []) if 'codec' in e.lower()]
                if codec_errors:
                    return f"❌ FAIL ({'; '.join(codec_errors)})"
                return "✅ PASS"
        return "⊗ NOT CHECKED"

    @staticmethod
    def _aggregate_caption_check(qc_inner: Dict) -> str:
        captions = qc_inner.get('captions', [])
        if not captions:
            return "⊗ NOT CHECKED"
        results = [c.get('details', {}).get('result', 'UNKNOWN') for c in captions]
        if any(r == 'FAIL' for r in results):
            failed = sum(1 for r in results if r == 'FAIL')
            return f"❌ FAIL ({failed}/{len(results)} videos missing captions)"
        return f"✅ PASS ({len(results)}/{len(results)} videos)"

    @staticmethod
    def _aggregate_similarity_check(qc_inner: Dict) -> str:
        similarity = qc_inner.get('content_similarity', [])
        if not similarity:
            return "⊗ NOT CHECKED"
        result = similarity[0].get('result', 'UNKNOWN')
        similarity_pct = similarity[0].get('highest_similarity', 0)
        if result == 'FAIL':
            return f"❌ FAIL ({similarity_pct:.0%} similar to recent short)"
        if result == 'WARN':
            return f"⚠️ WARN ({similarity_pct:.0%} similar to recent short)"
        if result == 'SKIP':
            return "⊗ SKIPPED (no channel history yet)"
        return "✅ PASS"

    @staticmethod
    def _aggregate_metadata_check(qc_inner: Dict) -> str:
        metas = qc_inner.get('metadata', [])
        if not metas:
            return "⊗ NOT CHECKED"
        statuses = [m.get('status', 'unknown') for m in metas]
        if any(s == 'error' for s in statuses):
            failed = [m['manifest_type'] for m in metas if m.get('status') == 'error']
            return f"❌ FAIL ({', '.join(failed)})"
        if any(s == 'warning' for s in statuses):
            warned = [m['manifest_type'] for m in metas if m.get('status') == 'warning']
            return f"⚠️ WARN ({', '.join(warned)})"
        return "✅ PASS (all 4 manifests)"

    @staticmethod
    def build_quality_report_table(qc_result: Dict) -> str:
        """Build the Quality Report table from REAL qc_result data (not hardcoded)"""
        qc_inner = qc_result.get('qc_result', {}) or {}

        rows = [
            ("Video Codec (h264/aac)", BatchSummaryGenerator._aggregate_codec_check(qc_inner)),
            ("Resolution (1080x1920)", BatchSummaryGenerator._aggregate_video_check(qc_inner, 'resolution')),
            ("Duration (15-45s)", BatchSummaryGenerator._aggregate_video_check(qc_inner, 'duration')),
            ("Audio Sync (±0.3s)", BatchSummaryGenerator._aggregate_video_check(qc_inner, 'audio_sync')),
            ("Captions Burned-In", BatchSummaryGenerator._aggregate_caption_check(qc_inner)),
            ("Content Uniqueness", BatchSummaryGenerator._aggregate_similarity_check(qc_inner)),
            ("Metadata Complete", BatchSummaryGenerator._aggregate_metadata_check(qc_inner)),
        ]

        lines = ["| Check | Result |", "|-------|--------|"]
        for name, result in rows:
            lines.append(f"| {name} | {result} |")

        overall_status = qc_result.get('status', 'unknown')
        routing = qc_result.get('routing', 'unknown')
        if routing == 'pass':
            footer = "All validations passed. Ready for upload."
        else:
            footer = f"⚠️ QC status: {overall_status.upper()} — routed to **{routing}**. Review errors above before uploading."

        return "\n".join(lines) + f"\n\n{footer}"

    @staticmethod
    def create_readme(
        clip_manifest: Dict,
        seo_manifest: Dict,
        video_manifest: Dict,
        thumbnail_manifest: Dict,
        qc_result: Dict,
        output_dir: str
    ) -> str:
        """
        Generate README.md with:
        - Quick stats (videos, duration, quality)
        - Upload order (exact sequence)
        - Key metadata per short
        - Next steps

        Readable in 30 seconds
        """

        video_paths = video_manifest.get('video_paths', [])
        seo_data = seo_manifest.get('best_title', '')

        # Calculate total duration
        total_duration = 0
        video_info = {}

        for i, path in enumerate(video_paths):
            if Path(path).exists():
                try:
                    from moviepy.editor import VideoFileClip
                    clip = VideoFileClip(path)
                    duration = clip.duration
                    clip.close()
                    total_duration += duration
                    video_info[i] = duration
                except Exception as e:
                    logger.warning(f"Could not read duration for video {i}: {e}")
                    video_info[i] = 0

        # Convert total duration to min:sec
        total_mins = int(total_duration // 60)
        total_secs = int(total_duration % 60)
        duration_str = f"{total_mins} min {total_secs} sec"

        # QC status
        qc_status = qc_result.get('qc_result', {}).get('summary', {}).get('overall_status', 'UNKNOWN')
        status_emoji = "✅" if qc_status in ['pass', 'warning'] else "⚠️"

        # Thumbnail status
        thumb_manifest = thumbnail_manifest
        generated_count = thumb_manifest.get('generated_count', 0)
        brief_only_count = thumb_manifest.get('brief_only_count', 0)
        thumb_status = f"{generated_count} generated, {brief_only_count} brief-only" if brief_only_count > 0 else f"{generated_count} generated"

        # Build upload order section
        upload_order_lines = []
        top_clip_indices = clip_manifest.get('top_clip_indices', list(range(7)))

        for idx, clip_idx in enumerate(top_clip_indices):
            # Try to get title from SEO manifest or generate placeholder
            video_idx = idx
            if video_idx < len(video_paths):
                duration = video_info.get(video_idx, 0)
                duration_formatted = f"{int(duration)}s"

                # Build title - should come from SEO results
                # For now, use clip number
                title_placeholder = f"Clip {video_idx + 1}"

                upload_order_lines.append(f"{idx + 1}. short_{video_idx + 1:03d}.mp4 - \"{title_placeholder}\" - {duration_formatted}")

        upload_order_section = "\n".join(upload_order_lines)

        # Build metadata section
        metadata_lines = []
        for idx in range(min(len(video_paths), 7)):
            duration = video_info.get(idx, 0)
            metadata_lines.append(f"\n📹 **Short {idx + 1}** ({int(duration)}s)")
            metadata_lines.append(f"  - **File:** short_{idx + 1:03d}.mp4")
            metadata_lines.append(f"  - **Thumbnail:** thumbnail_{idx + 1:03d}")

        metadata_section = "\n".join(metadata_lines)

        # Timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        quality_report_table = BatchSummaryGenerator.build_quality_report_table(qc_result)
        routing = qc_result.get('routing', 'unknown')
        ready_line = "Ready to publish. No manual intervention needed." if routing == 'pass' \
            else f"NOT auto-cleared for publish (routing: {routing}). Review the Quality Report above before uploading."

        readme_content = f"""# Batch Upload Ready: {len(video_paths)} Shorts

**Status:** {status_emoji} {qc_status.upper()}
**Generated:** {timestamp}
**Batch ID:** batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}

---

## ⚡ Quick Summary (30 seconds)

| Metric | Value |
|--------|-------|
| **Total Videos** | {len(video_paths)} |
| **Total Duration** | {duration_str} |
| **Quality Check** | {qc_status.upper()} |
| **Thumbnails** | {thumb_status} |

---

## 📤 Upload Order (Do in this exact sequence)

```
{upload_order_section}
```

---

## 📋 Quick Metadata Reference

{metadata_section}

---

## ✅ Upload Checklist

- [ ] Open YouTube Studio (youtube.com/studio)
- [ ] Create new Shorts playlist or select series
- [ ] Upload videos **in order above** (1 → 2 → 3 → ... → 7)
- [ ] For each video:
  - Use metadata from `upload_metadata/[N].json`
  - Apply custom thumbnail from `thumbnails/[N]`
  - Add title, description, hashtags, tags as specified
  - Schedule or publish immediately
- [ ] Verify all 7 published in correct order
- [ ] Check description links and hashtags

---

## 📁 Folder Structure

```
batch_{timestamp}/
├── README.md                    ← You are here
├── UPLOAD_ORDER.txt            ← Copy/paste for quick reference
├── VIDEO_CHECKLIST.md          ← Step-by-step upload guide
├── shorts/                     ← 7 MP4 files (ready to upload)
│   ├── short_001.mp4
│   ├── short_002.mp4
│   └── ...short_007.mp4
├── thumbnails/                 ← Thumbnail images or briefs
│   ├── thumbnail_001.jpg
│   ├── thumbnail_002.jpg (or _BRIEF.txt)
│   └── ...thumbnail_007.jpg
├── upload_metadata/            ← JSON metadata per video
│   ├── 001.json                ← Title, description, hashtags
│   ├── 002.json
│   └── ...007.json
├── manifests/                  ← Full pipeline manifests
│   ├── BATCH_MANIFEST.json
│   ├── clip_manifest.json
│   ├── seo_manifest.json
│   ├── video_manifest.json
│   ├── thumbnail_manifest.json
│   └── qc_manifest.json
└── VALIDATION.log              ← Full QC validation results
```

---

## 🎯 Next Steps

### Immediate (Upload Today)
1. Copy video files from `shorts/` → YouTube Studio
2. Apply metadata from `upload_metadata/` → each video
3. Apply thumbnails from `thumbnails/` → each video
4. Publish in order (1 through 7)

### Before Publishing
- ✅ Verify all 7 videos uploaded
- ✅ All titles, descriptions, hashtags applied
- ✅ Custom thumbnails set for each
- ✅ Schedule or publish (don't hold back)

### After Publishing
- Track views/retention/CTR for first 48 hours
- Note which thumbnails perform best
- Collect top comments for next batch insights

---

## 📊 Quality Report

{quality_report_table}

---

**Generated by Chaos Merchant Output Packaging Agent**
**{ready_line}**
"""

        return readme_content


class UploadChecklistGenerator:
    """Generates YouTube upload checklist"""

    @staticmethod
    def create_upload_checklist(seo_manifest: Dict, video_count: int) -> str:
        """Generate step-by-step upload guide"""

        checklist_content = f"""# YouTube Studio Upload Checklist

**Batch:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Videos to Upload:** {video_count}

---

## Pre-Upload

- [ ] Log into YouTube Studio (youtube.com/studio)
- [ ] Open "Create" → "Upload video"
- [ ] Verify you have 7 video files ready in `shorts/` folder
- [ ] Open `upload_metadata/` folder in another window for quick reference

---

## For Each Video (1 through {video_count})

### 1. Upload File
- [ ] Select `shorts/short_00X.mp4` from folder
- [ ] Wait for upload to complete

### 2. Add Details
- [ ] Open `upload_metadata/00X.json` in text editor
- [ ] Copy **Title** → YouTube "Title" field
- [ ] Copy **Description** → YouTube "Description" field
- [ ] Copy **Tags** → YouTube "Tags" field (comma-separated)
- [ ] Copy **Hashtags** → paste into Description (top line)

### 3. Set Thumbnail
- [ ] Click "Upload Thumbnail"
- [ ] Select `thumbnails/thumbnail_00X.jpg`
- [ ] If file not found, manually create from `thumbnail_00X_BRIEF.txt` instructions on Canva
- [ ] Confirm thumbnail shows on preview

### 4. Set Visibility & Schedule
- [ ] Select **Visibility**: Public (or Scheduled for specific time)
- [ ] If scheduling: space uploads 1 hour apart
- [ ] Click "Save Draft" (do NOT publish yet)

### 5. Playlist/Series (Optional)
- [ ] Add to Playlist: "Chaos Merchant - Latest Batch"
- [ ] Or add to Series if batch is themed

### 6. Review & Publish
- [ ] Verify title, description, tags are correct
- [ ] Verify thumbnail loaded
- [ ] Click "Publish" or "Schedule"

---

## After All 7 Videos Published

- [ ] Check YouTube Studio: all 7 shorts visible
- [ ] Verify publish order matches upload sequence
- [ ] Check each short has correct thumbnail
- [ ] Take screenshot of Shorts shelf for records
- [ ] Update channel_memory with published video URLs (for analytics)

---

## Video Metadata Template

Each video folder (`upload_metadata/00X.json`) contains:

```json
{{
  "title": "GAME NAME - SPECIFIC MOMENT",
  "description": "Hook restatement + CTA + Subscribe\nWatch full stream: [link]",
  "hashtags": ["#Gaming", "#Glitch", ...],
  "tags": ["Gaming", "Glitch", ...],
  "keywords": ["keyword phrase 1", "keyword phrase 2", ...],
  "duration": 32.45,
  "publish_time": "2026-07-02T14:00:00Z"
}}
```

Copy these exact values into YouTube Studio without editing.

---

## Troubleshooting

**Q: Thumbnail not showing in YouTube upload**
A: Use `thumbnail_00X.jpg` file from `thumbnails/` folder. If missing, follow instructions in `thumbnail_00X_BRIEF.txt` to create on Canva manually.

**Q: Video rejected (codec, format)**
A: Should not happen — QC validated all videos. Check file size > 500KB and < 100MB.

**Q: Unsure about upload order**
A: Follow exactly: short_001.mp4 → short_002.mp4 → ... → short_007.mp4. Order matters for algorithm.

---

**Estimated Upload Time:** 15-20 minutes for all 7 videos
**No manual editing required.** Copy-paste metadata and go.
"""

        return checklist_content


class OutputPackager:
    """Main orchestrator for output packaging"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_batch_folder(
        self,
        clip_manifest: Dict,
        seo_manifest: Dict,
        video_manifest: Dict,
        thumbnail_manifest: Dict,
        qc_result: Dict,
        video_base_name: str = ''
    ) -> Dict:
        """
        Create complete output package:
        - Batch folder with timestamp
        - README (30-second summary)
        - Upload checklist
        - Organized subdirectories
        - All manifests and metadata
        - Validation report

        Returns: packaging result with batch path
        """

        logger.info("=" * 70)
        logger.info("📦 OUTPUT PACKAGING - Creating upload-ready batch")
        logger.info("=" * 70)

        # Create timestamped batch folder
        batch_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        batch_folder = self.output_dir / f"batch_{batch_timestamp}"
        batch_folder.mkdir(parents=True, exist_ok=True)

        logger.info(f"📁 Batch folder created: {batch_folder}")

        # Create subdirectories
        shorts_dir = batch_folder / "shorts"
        thumbnails_dir = batch_folder / "thumbnails"
        manifests_dir = batch_folder / "manifests"
        metadata_dir = batch_folder / "upload_metadata"

        for d in [shorts_dir, thumbnails_dir, manifests_dir, metadata_dir]:
            d.mkdir(parents=True, exist_ok=True)

        logger.info(f"✓ Subdirectories created: shorts, thumbnails, manifests, upload_metadata")

        # ============================================================
        # 1. COPY VIDEO FILES
        # ============================================================
        logger.info("\n📹 Organizing video files...")
        video_paths = video_manifest.get('video_paths', [])
        copied_videos = []

        for i, video_path in enumerate(video_paths):
            video_path = Path(video_path)
            if video_path.exists():
                dest_name = f"short_{i + 1:03d}.mp4"
                dest_path = shorts_dir / dest_name

                try:
                    shutil.copy2(video_path, dest_path)
                    copied_videos.append(dest_name)
                    logger.info(f"  ✓ {dest_name}")
                except Exception as e:
                    logger.error(f"  ❌ Failed to copy {video_path}: {e}")
            else:
                logger.warning(f"  ⚠ Video not found: {video_path}")

        logger.info(f"✓ Videos organized: {len(copied_videos)}/{len(video_paths)} copied")

        # ============================================================
        # 2. COPY/ORGANIZE THUMBNAILS
        # ============================================================
        logger.info("\n🖼️  Organizing thumbnails...")
        thumb_manifest = thumbnail_manifest
        thumbnails_list = thumb_manifest.get('thumbnails', [])
        copied_thumbnails = []

        for i, thumb_data in enumerate(thumbnails_list):
            if thumb_data.get('status') == 'success' or thumb_data.get('status') == 'generated':
                # Actual image file
                image_path = thumb_data.get('image_path') or thumb_data.get('image_url')
                if image_path and Path(image_path).exists():
                    src = Path(image_path)
                    dest = thumbnails_dir / f"thumbnail_{i + 1:03d}.jpg"
                    try:
                        shutil.copy2(src, dest)
                        copied_thumbnails.append(dest.name)
                        logger.info(f"  ✓ {dest.name} (generated)")
                    except Exception as e:
                        logger.warning(f"  ⚠ Failed to copy thumbnail {i}: {e}")

            elif thumb_data.get('status') == 'brief_only':
                # Brief for manual creation
                brief_text = thumb_data.get('brief', '')
                canva_prompt = thumb_data.get('canva_prompt', '')
                instructions = thumb_data.get('instructions', 'Create on Canva.com')

                brief_file = thumbnails_dir / f"thumbnail_{i + 1:03d}_BRIEF.txt"
                brief_content = f"""THUMBNAIL BRIEF - Short {i + 1}

{brief_text}

CANVA PROMPT:
{canva_prompt}

INSTRUCTIONS:
{instructions}

Steps:
1. Go to Canva.com
2. Create new YouTube Thumbnail (1280x720)
3. Use the prompt above to guide design
4. Export as JPG
5. Download and rename to: thumbnail_{i + 1:03d}.jpg
6. Upload to YouTube with video
"""
                try:
                    with open(brief_file, 'w') as f:
                        f.write(brief_content)
                    copied_thumbnails.append(brief_file.name)
                    logger.info(f"  ✓ {brief_file.name} (brief-only, manual creation needed)")
                except Exception as e:
                    logger.warning(f"  ⚠ Failed to write brief {i}: {e}")

        logger.info(f"✓ Thumbnails organized: {len(copied_thumbnails)} items")

        # ============================================================
        # 3. CREATE UPLOAD METADATA JSON
        # ============================================================
        logger.info("\n📝 Creating upload metadata (from real SEO results)...")

        seo_meta = seo_manifest.get('metadata', {}) or {}
        candidate_titles = seo_meta.get('titles', []) or []
        best_title = seo_manifest.get('best_title', '')
        description = seo_meta.get('description', '')
        hashtags = seo_meta.get('hashtags', []) or []
        tags = seo_meta.get('tags', []) or []
        keywords = seo_meta.get('keywords', []) or []

        if not candidate_titles and not best_title:
            logger.warning("  ⚠ No SEO titles found in seo_manifest — upload metadata will have empty titles, verify Step 5 ran successfully")

        for i in range(len(video_paths)):
            # NOTE: The pipeline currently generates one script + one SEO pass per
            # source video, not per individual clip, so all 7 shorts share the same
            # description/hashtags/tags/keywords. We distribute the SEO agent's 5
            # candidate titles across the 7 shorts (cycling) so titles aren't
            # identical, but this is real Claude-generated data, not per-clip metadata.
            if candidate_titles:
                title = candidate_titles[i % len(candidate_titles)]
            else:
                title = best_title or f"Untitled Short {i + 1}"

            metadata = {
                "short_index": i + 1,
                "file": f"short_{i + 1:03d}.mp4",
                "thumbnail": f"thumbnail_{i + 1:03d}.jpg",
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "tags": tags,
                "keywords": keywords,
                "publish_immediately": True,
                "visibility": "Public"
            }

            metadata_file = metadata_dir / f"{i + 1:03d}.json"
            try:
                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)
                logger.info(f"  ✓ {i + 1:03d}.json (title: \"{title[:40]}\")")
            except Exception as e:
                logger.error(f"  ❌ Failed to write metadata {i}: {e}")

        logger.info(f"✓ Upload metadata created: {len(video_paths)} files (real SEO data)")

        # ============================================================
        # 4. COPY MANIFESTS
        # ============================================================
        logger.info("\n📋 Organizing manifests...")

        # Save all manifests to manifests directory
        manifest_files = {
            'clip_manifest.json': clip_manifest,
            'seo_manifest.json': seo_manifest,
            'video_manifest.json': video_manifest,
            'thumbnail_manifest.json': thumbnail_manifest,
            'qc_manifest.json': qc_result
        }

        for filename, manifest_data in manifest_files.items():
            manifest_file = manifests_dir / filename
            try:
                with open(manifest_file, 'w') as f:
                    json.dump(manifest_data, f, indent=2)
                logger.info(f"  ✓ {filename}")
            except Exception as e:
                logger.error(f"  ❌ Failed to save {filename}: {e}")

        logger.info(f"✓ Manifests organized: {len(manifest_files)} files")

        # ============================================================
        # 5. CREATE BATCH MANIFEST
        # ============================================================
        logger.info("\n📊 Creating batch manifest...")

        batch_manifest = {
            "batch_id": f"batch_{batch_timestamp}",
            "created_at": datetime.now().isoformat(),
            "status": qc_result.get('status', 'unknown'),
            "qc_routing": qc_result.get('routing', 'unknown'),
            "video_count": len(video_paths),
            "videos": [f"short_{i + 1:03d}.mp4" for i in range(len(video_paths))],
            "thumbnails": [f"thumbnail_{i + 1:03d}" for i in range(len(video_paths))],
            "all_validated": qc_result.get('status') in ['pass', 'warning'],
            "ready_for_upload": qc_result.get('routing') == 'pass'
        }

        batch_manifest_file = manifests_dir / "BATCH_MANIFEST.json"
        try:
            with open(batch_manifest_file, 'w') as f:
                json.dump(batch_manifest, f, indent=2)
            logger.info(f"✓ Batch manifest: {batch_manifest_file.name}")
        except Exception as e:
            logger.error(f"❌ Failed to save batch manifest: {e}")

        # ============================================================
        # 6. CREATE README
        # ============================================================
        logger.info("\n📄 Creating README (30-second summary)...")

        readme_content = BatchSummaryGenerator.create_readme(
            clip_manifest, seo_manifest, video_manifest,
            thumbnail_manifest, qc_result, str(self.output_dir)
        )

        readme_file = batch_folder / "README.md"
        try:
            with open(readme_file, 'w') as f:
                f.write(readme_content)
            logger.info(f"✓ README created: {readme_file.name} (readable in 30 seconds)")
        except Exception as e:
            logger.error(f"❌ Failed to save README: {e}")

        # ============================================================
        # 7. CREATE UPLOAD CHECKLIST
        # ============================================================
        logger.info("\n✅ Creating upload checklist...")

        checklist_content = UploadChecklistGenerator.create_upload_checklist(
            seo_manifest, len(video_paths)
        )

        checklist_file = batch_folder / "VIDEO_CHECKLIST.md"
        try:
            with open(checklist_file, 'w') as f:
                f.write(checklist_content)
            logger.info(f"✓ Checklist created: {checklist_file.name}")
        except Exception as e:
            logger.error(f"❌ Failed to save checklist: {e}")

        # ============================================================
        # 8. CREATE UPLOAD ORDER TXT
        # ============================================================
        logger.info("\n📤 Creating upload order file...")

        upload_order_lines = []
        for i in range(len(video_paths)):
            upload_order_lines.append(f"{i + 1}. short_{i + 1:03d}.mp4")

        upload_order_content = "UPLOAD ORDER (Do in this sequence)\n" + "=" * 40 + "\n\n" + "\n".join(upload_order_lines)

        upload_order_file = batch_folder / "UPLOAD_ORDER.txt"
        try:
            with open(upload_order_file, 'w') as f:
                f.write(upload_order_content)
            logger.info(f"✓ Upload order file: {upload_order_file.name}")
        except Exception as e:
            logger.error(f"❌ Failed to save upload order: {e}")

        # ============================================================
        # SUMMARY
        # ============================================================
        logger.info("\n" + "=" * 70)
        logger.info("📦 OUTPUT PACKAGING COMPLETE")
        logger.info("=" * 70)
        logger.info(f"Batch Folder: {batch_folder}")
        logger.info(f"Videos: {len(copied_videos)}/{len(video_paths)} organized")
        logger.info(f"Thumbnails: {len(copied_thumbnails)}/{len(video_paths)} organized")
        logger.info(f"Metadata: {len(video_paths)} JSON files created")
        logger.info(f"Manifests: {len(manifest_files) + 1} files organized")
        logger.info(f"\n✅ Ready for Upload - Open README.md and start uploading!")
        logger.info("=" * 70)

        return {
            'status': 'success',
            'batch_folder': str(batch_folder),
            'batch_id': f"batch_{batch_timestamp}",
            'videos_organized': len(copied_videos),
            'thumbnails_organized': len(copied_thumbnails),
            'metadata_files': len(video_paths),
            'manifests_saved': len(manifest_files) + 1,
            'timestamp': datetime.now().isoformat()
        }


def package_outputs(
    clip_manifest: Dict,
    seo_manifest: Dict,
    video_manifest: Dict,
    thumbnail_manifest: Dict,
    qc_result: Dict,
    output_dir: str = './output',
    video_base_name: str = ''
) -> Dict:
    """
    Main entry point: Package all outputs into clean, organized batch folder

    Creates folder structure:
    batch_YYYYMMDD_HHMMSS/
    ├── README.md                    (30-second batch summary)
    ├── VIDEO_CHECKLIST.md           (step-by-step upload guide)
    ├── UPLOAD_ORDER.txt             (quick reference order)
    ├── shorts/                      (7 MP4 files)
    ├── thumbnails/                  (7 JPG images or briefs)
    ├── upload_metadata/             (7 JSON files with metadata)
    └── manifests/                   (all pipeline manifests)

    Open README, read in 30 seconds, know exactly what to upload
    """

    logger.info("\n" + "=" * 70)
    logger.info("🎬 OUTPUT PACKAGING AGENT - Step 9")
    logger.info("=" * 70)
    logger.info("Creating clean, organized, upload-ready batch folder")
    logger.info("=" * 70 + "\n")

    try:
        packager = OutputPackager(output_dir)
        result = packager.create_batch_folder(
            clip_manifest, seo_manifest, video_manifest,
            thumbnail_manifest, qc_result, video_base_name
        )

        return {
            'status': 'success',
            'packaging_result': result,
            'batch_folder': result['batch_folder'],
            'batch_id': result['batch_id'],
            'ready_for_upload': qc_result.get('routing') == 'pass',
            'timestamp': datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ Packaging failed: {e}")
        return {
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }
