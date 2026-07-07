# CHAOS MERCHANT - PROJECT HANDOFF DOCUMENT

**Current Date:** 2026-07-07
**Branch:** `claude/session-handoff-review-bawvji` (this session's designated branch, kept 1:1 in sync with `main` via fast-forward push after every fix/component)
**Current model:** `claude-sonnet-5`
**Status:** Two completed bodies of work are now on `main`:
1. The original 5-bug punch list from the first real-hardware run (all fixed).
2. The format pivot + autonomous sourcing/publishing system (Components 1-4 of 4, all built and pushed).

**Next Action:** This is a home-machine handoff. Nothing in Components 1-4 has been exercised against real Reddit/YouTube/Anthropic APIs, real ffmpeg/moviepy, or a real browser hitting the dashboard - all of it was built and verified with fake-object test harnesses in a sandbox that has none of those dependencies installed. Work through the **HOME MACHINE TO-DO LIST** below before trusting any of this in production, in the priority order given. The single biggest remaining gap is `agents/quality_control.py`'s validator has NOT been extended to gate freshly-DOWNLOADED sourced clips before they enter the pipeline (see "WHAT STILL NEEDS BUILDING" below) - autonomous sourcing currently has no post-download sanity check beyond the metadata-only `CopyrightRiskGate`.

**Branch/remote note:** `origin/main` and `claude/session-handoff-review-bawvji` are confirmed in sync as of this update - every fix/component this session was pushed to both via fast-forward (one exception: the last 3 commits show as "Unverified" on GitHub due to a missing commit-signing key in this sandbox's git config - a signing-key limitation of this environment, not a content or authorship issue; every commit already carries the correct `Claude <noreply@anthropic.com>` author/committer identity).

---

## EXECUTIVE SUMMARY

### Phase 1 (complete): 5-bug punch list from the first real-hardware run

A prior hardening session did a full documentation + Docker pass. The session after that ran the pipeline against real hardware for the first time (real moviepy/ffmpeg/Kokoro, not mocks) and it broke in five distinct ways. Fixed one at a time, full root-cause debrief + individual push after each. **All 5 are fixed and on `main`.** Full root-cause writeups are preserved below under "PHASE 1 - BUGS FIXED" for reference - nothing there has changed since the last handoff.

### Phase 2 (complete): Format pivot + autonomous sourcing/publishing

The user identified that the pipeline's emotion-based "reaction" scripts read as AI slop (synthetic voices can't perform genuine emotion; reaction content needs a human personality AI can't replicate), and that requiring a human to manually drop source videos into `input/` defeated the point of an "autonomous" system. A full planning session (plan mode) produced a 4-area architecture plan; the user then directed component-by-component implementation with a debrief + confirmation gate after each. All 4 were built, plus several follow-up fix rounds the user requested along the way:

- **Component 1** - Multi-format script system (5 formats, hybrid selector, format tracking)
- **Component 2** - Autonomous clip sourcing agent (Reddit + YouTube, copyright gate, dedup)
- **Component 2 follow-up** - Threshold verification + louder empty-whitelist warning
- **Four flagged-item fixes** - format-selector confidence scoring, per-clip SEO dedup, Kokoro voice test command, `--verify` setup command
- **Two more flagged-item fixes** - SEO dedup failure now gates QC as a warning, `--verify`'s ImageMagick check does a real render test
- **Component 3 (expanded)** - Content calendar, format-mix rebalancing, autonomous publishing queue, posting-schedule optimizer, cost-per-Short tracking, dashboard Schedule tab
- **Component 3 addendum** - Empty-sourcing dashboard alerts + desktop notification, download bandwidth folded into cost-per-Short
- **Component 4** - Sourcing setup verification (dashboard-reachable), curated-channel whitelist UI, sourcing run-schedule config UI, full offline integration test (caught and fixed a real DATA_DIR bug in the process)
- **Notification durability fix** (bundled with Component 4) - every notification is now logged to disk regardless of delivery, and the empty-sourcing alert persists until dismissed instead of auto-clearing

Full detail on each is under "PHASE 2 - FORMAT PIVOT COMPONENTS" below.

**Note on numbering:** the user's most recent message referred to "all 5 components" - as built, this is 4 components (matching the original plan's 4 areas, with Component 4 redirected mid-session from the original plan's "Quality Gate for Sourced Content" to sourcing-setup/UI work instead, at the user's explicit request). The original Area 4 (Quality Gate for Sourced Content) has **not** been built - see "WHAT STILL NEEDS BUILDING" below. Flagging this discrepancy explicitly rather than silently asserting a 5th component exists.

---

## PHASE 1 - BUGS FIXED (unchanged since last handoff - full historical record)

**Bug 1 - Original source video audio bleeding through underneath voiceover/music.**
Root cause: `AudioProcessor.prepare_audio()` in `agents/video_production.py` was still building final audio using the source video clip's own audio track - there was no real background-music infrastructure anywhere in the codebase, so whatever the "music" layer was actually doing, the source audio was never actually excluded from the composite.
Fix: two-part structural strip, not a volume-based patch.
1. Extracted clips get `.without_audio()` called immediately after extraction in `produce_single_short()`, before any reframe/composite step - the source audio is severed at the earliest possible point, structurally, so no downstream code path can accidentally reintroduce it.
2. Added a new `BackgroundMusicLibrary` class that loads a real royalty-free track from `assets/music/` (rotating by short number, looping/trimming to the clip's duration), and `prepare_audio()` was rewritten to build final audio exclusively from `voiceover_audio` + this explicit `background_music` parameter - it no longer reads `video_clip.audio` at all.
Verified via audio-lineage fake objects proving the final composited audio's lineage never contains `'srcaudio'`, with and without background music present, end-to-end through `produce_single_short()`.

**Bug 2 - Music way louder than voiceover.**
Root cause: insufficient ducking depth, and no base-level attenuation at all when no voiceover was playing.
Fix: replaced `apply_music_ducking()` with `apply_music_envelope()` - a full gain envelope: **-12dB base** outside the voiceover, **-18dB duck** during it, with 0.25s linear ramps. Configurable via `MUSIC_BASE_DB`/`MUSIC_DUCK_DB`. A new `_verify_envelope_callback()` invokes the actual render callback with synthetic frames at known timestamps and checks measured gain against expected - if verification fails, returns un-enveloped audio with `applied=False` and a loud error, instead of silently shipping a broken envelope.
Both fixes are in `agents/video_production.py` only. `.env.example` gained `BACKGROUND_MUSIC_DIR`, `MUSIC_BASE_DB`, `MUSIC_DUCK_DB`. `assets/music/README.md` documents the folder.

**Bug 3 - Captions cut off at the bottom of the screen.**
Root cause was two layers deep: a hardcoded flat 160px-from-bottom position, AND moviepy 2.x's `TextClip` (Pillow-backed, no ImageMagick, no built-in default font) raising on every construction when `CAPTION_FONT_PATH` was unset - silently zero-captioning every video on a machine without that env var.
Fix: captions anchor at 80% down from the top, clamped to an 80px bottom margin; new `_resolve_font_path()` falls back through DejaVu/Liberation/macOS system fonts if `CAPTION_FONT_PATH` is unset, logging one loud error if nothing resolves; `render_captions()` distinctly logs "ALL segments failed" vs partial; new `CaptionSynchronizer.verify_captions_in_export()` reopens the finished MP4 and samples frames at caption-active timestamps to confirm captions actually survived to the export file.
Change is in `agents/video_production.py` only.

**Bug 4 - Video goes black and silent after ~30 seconds despite the clip being longer.**
Root cause: a source video's duration metadata can overstate how much is actually decodable (a container-header gotcha) - reading past real content silently returns black frames, and audio built to the claimed duration has nothing real to drive it either.
Fix: new `ClipExtractor._detect_playable_duration()` samples frames and requires the **last 3 samples** to all be black before concluding there's an undecodable tail (avoids false-triggering on a single legitimately dark moment); truncates to the last confirmed content when a genuine gap is found. Hardened the (already-correct) clip/voiceover duration reconciliation with explicit post-hoc assertions. Added detailed clip/voiceover/final duration logging at two points in the pipeline.
**Caveat carried forward:** this is a heuristic, not a certainty, and was never validated against the actual source file from the original broken run (unavailable in this environment). The new duration logging will make it obvious on the next real hardware run whether this was the actual cause - watch for it.
Change is in `agents/video_production.py` only.

**Bug 5 - Fewer Shorts produced than clips detected.**
Root cause, three compounding issues: (1) `core/pipeline.py`'s QC step aborted the ENTIRE pipeline run if even 1 of N clips had any QC issue - the other clips' videos existed on disk but never got packaged; (2) QC's content-similarity check only ever compared one title (the first successful clip's) against channel history, so a collision on clip 1 could flag the whole batch while clips 2/3 were never actually evaluated; (3) QC's caption-presence detector hardcoded a stale frame region (bottom 15%) that no longer matched Bug 3's new caption position (80% down from top), causing false "no captions detected" positives.
Fix: QC failures are now logged loudly and per-clip QC failure files are written, but the batch **always proceeds to packaging** with `routing=manual_review` if needed, instead of not existing at all; content similarity runs once per clip against that clip's own SEO result; the caption-detection region now imports `CaptionSynchronizer.CAPTION_TOP_RATIO` directly instead of an independently-hardcoded guess; every step logs an explicit `[Short N/M]` tag; every failure (production or QC) writes a dedicated human-readable error file into the output folder.
Change spans `agents/video_production.py`, `agents/quality_control.py`, `agents/output_packaging.py`, and `core/pipeline.py`.

---

## PHASE 2 - FORMAT PIVOT COMPONENTS (built this session)

### Component 1 - Multi-format script system

Five format templates (`prompts/formats/{hidden_details,news_recap,ranking,comparison,reaction}.txt`), each with its own STRUCTURE section, sharing a common HARD RULES preamble. New `agents/format_selector.py`: hybrid selection - Reaction is hard-gated by `REACTION_MIN_VIRAL_SCORE` (viral_score >= 8.0, enforced in code, never an LLM suggestion), everything else goes through one cheap Haiku tiebreak call given clip content + trending context + the content calendar's format-mix guidance. The script generation call's JSON schema gained a required `format_used` field (the model echoes back what it actually wrote, not just what was requested - a mismatch is a real signal, same "verify, don't trust" pattern as this codebase's other post-hoc verification steps). `core/memory.py`'s `channel_shorts` table gained a migrated `format_used` column; `ChannelMemory.get_format_performance()` reports CTR/retention/viral_score per format (report-only, no auto-adjustment, per the launch decision).

### Component 2 - Autonomous clip sourcing agent

New `agents/clip_sourcing.py`: `RedditClipFetcher` (PRAW, reuses `trend_intelligence.py`'s credential pattern) + `YouTubeClipFetcher` (yt-dlp, both curated-channel and trending-search discovery modes). `CopyrightRiskGate` - all three signals required before any real download: minimum popularity (`MIN_REDDIT_SCORE`/`MIN_YOUTUBE_VIEWS`), max source length (`MAX_SOURCE_CLIP_SECONDS`), known-risk uploader blocklist (`config/source_blocklist.json`). New `SourceRegistry` (SQLite) guarantees a clip is never downloaded twice, checked before any probe/download. `SourcingRateLimiter` caps probes/downloads per run with a politeness delay - a separate limiter from `core/scheduler.py`'s YouTube-Data-API-specific `QuotaTracker`, not a reuse of it (the two quota systems are unrelated). Dual pipeline routing: already-short sourced clips skip scene-detection and map to a single Short; long sourced videos go through the existing multi-clip extraction unchanged.

**Component 2 follow-up:** `MIN_REDDIT_SCORE`/`MIN_YOUTUBE_VIEWS` verified already at the requested 500/50000 (no change needed - reported as such rather than silently no-op'd). Dashboard Sources tab added with a loud, impossible-to-miss warning that the YouTube curated-channel whitelist starts empty on purpose.

**Four flagged-item fixes:** format selector now scores its own vision-description confidence and defaults to Hidden Details below `FORMAT_SELECTOR_MIN_DESCRIPTION_CONFIDENCE` (0.5) rather than risk a wrong format call; per-clip SEO metadata is checked for duplicates against recent history with automatic regeneration; `KOKORO_VOICE` env var + a voice-test CLI command generating a 10s sample across all 8 valid Kokoro voices; `python main.py --verify` command checking ffmpeg/ImageMagick/Kokoro/Anthropic/Reddit/YouTube/music/font, checked BEFORE the heavy agent-stack imports so a broken dependency can't crash the verification command itself.

**Two more flagged-item fixes:** unresolved SEO duplicates (regeneration attempted and still collided) now flag the clip in QC as a warning instead of silently passing through with duplicate metadata; `--verify`'s ImageMagick check now attempts a real `label:` render and checks the actual output file size, not just installation/exit-code.

### Component 3 (expanded) - Content calendar + autonomous publishing system

- **`core/content_calendar.py`**: format-mix ratio updated to the approved 35% Hidden Details / 30% News Recap / 20% Ranking / 10% Comparison / 0% Reaction (Reaction stays selectable only via the hard viral_score gate, never via this ratio). New `posts_per_day` (default 3, distinct from sourcing's `target_batches_per_day`). New `get_effective_format_mix()` reads the last 7 days of actually-produced shorts and nudges the mix back toward target if it's skewed - a real rolling rebalance, not just a static config.
- **`core/memory.py`**: new `PostingQueue` class (`posting_queue` table) - every queued/posted/skipped/failed Short tracked by content hash (SHA-256 of the actual video bytes), checked both within a batch and across all prior batches/runs before ever being scheduled. `ChannelMemory.get_format_counts()` (rebalancing signal), `SourceRegistry.get_by_file_path()` (source attribution).
- **`core/posting_schedule.py`**: `PostingScheduleOptimizer` picks posting hours from THIS channel's own posted-hour vs. viral-score history once ~5+ real posts exist (the YouTube Analytics API has no public "audience active by hour" report - confirmed before writing this, not assumed - so this uses the channel's own real outcome data instead), falling back to fixed sane default hours (noon/5pm/8pm) until then.
- **`core/posting_queue.py`**: `enqueue_batch_for_posting()` (called from the pipeline right after QC passes - hashes every short, skips content duplicates within AND across batches, schedules the rest at spaced-out optimal times respecting `posts_per_day`) and `drain_due_posts()` (called on a schedule, posts whatever's due, gated purely by `AUTO_POST_YOUTUBE` checked fresh every run).
- **`core/pipeline.py`**: new Step 9 wires packaged+QC-passed batches into the posting queue.
- **`core/scheduler.py`** + **`main.py`**: new `schedule_every_n_minutes()` and a `posting_queue_drain` job (`POSTING_QUEUE_DRAIN_MINUTES`, default 15).
- **Dashboard**: new Schedule tab (queue, next post time, posting history, 7-day format distribution chart, format-mix targets, `AUTO_POST_YOUTUBE` toggle state with an explicit autonomy warning).

**`AUTO_POST_YOUTUBE` is NOT a review queue - it is a one-time safety switch.** Defaults `false`. While false, batches still get queued/scheduled but nothing uploads. The moment it's `true`, the queue drains on its own schedule and every due Short posts to YouTube automatically, with zero human review, forever, until switched back. There is no "pending approval" state.

**Component 3 addendum (two fixes requested before Component 4):**
1. A real (non-dry-run) sourcing run that downloads zero clips - the direct cause of an empty/stalled posting queue - now logs a root-cause-specific alert (no candidates discovered / all duplicates / all rejected by the gate with top reasons) and sends a desktop notification, instead of being a silent no-op.
2. Cost-per-Short now includes yt-dlp download bandwidth cost, not just Anthropic API spend. New `core.cost_tracker.log_download_usage()`/`get_cost_for_source_url()` (tagged by source_url, since a source video is downloaded well before the pipeline run that turns it into Shorts - outside the pipeline-run time window `get_cost_between()` uses). `DOWNLOAD_COST_PER_GB_USD` defaults to 0.0 (honest default - a home-machine deployment has no metered bandwidth; only set this if deployed to a metered cloud host).

### Component 4 - Sourcing setup verification, whitelist UI, schedule config, integration test

(Redirected mid-session, at the user's explicit request, from the original plan's "Quality Gate for Sourced Content" area - see "WHAT STILL NEEDS BUILDING" below for that unbuilt work.)

- **`core/setup_verification.py`**: new `_check_ytdlp_sourcing()` - a live metadata-only test search confirming yt-dlp actually works (no API key needed for YouTube sourcing, unlike `YOUTUBE_API_KEY` elsewhere). Added to both `python main.py --verify` and a new dashboard "Verify Sourcing Setup" button on the Sources tab.
- **`agents/clip_sourcing.py`**: `add_source_channel()`/`remove_source_channel()` and `add_sourcing_run_time()`/`remove_sourcing_run_time()` - the curated channel whitelist and sourcing run schedule are now editable from the dashboard instead of hand-editing JSON. New `config/source_schedule.json` (`run_times`, default `07:30`/`18:00`) replaces the two hardcoded `schedule_job` calls in `main.py`; `ClipSourcingAgent` derives its runs-per-day content-calendar guidance from the SAME file, so the two can never drift apart.
- **`tests/test_clip_sourcing_integration.py`**: full end-to-end integration test (fake praw/yt-dlp injected, real SourceRegistry/cost-tracking/alert logic exercised), runnable offline with no real credentials. 21/21 checks passing. Run it with `python tests/test_clip_sourcing_integration.py`.
- **Real bug caught and fixed while building the integration test**: `ClipSourcingAgent`'s `SourceRegistry` (and the sourcing alert log path) were hardcoded to `./data/...` regardless of the `DATA_DIR` env var, unlike every other memory-backed class in this codebase. On a deployment with a custom `DATA_DIR` (the `.env.example` shows one), this would have silently broken the "never download the same clip twice" dedup guarantee. Fixed both to resolve from `DATA_DIR` consistently.

**Notification durability fix (bundled with Component 4):** every `send_notification()` call is now also logged to `data/notification_log.json` (timestamp, title, message, delivered bool) regardless of `ENABLE_NOTIFICATIONS` or whether a desktop mechanism exists - the log is the durable record, since an osascript/notify-send popup disappears if the machine is asleep or locked. The empty-sourcing alert now persists to `data/sourcing_alerts.json` with an id + dismissed flag and stays on the dashboard's Schedule tab until explicitly dismissed, not auto-cleared by time or a later successful run.

---

## WHAT STILL NEEDS BUILDING (not yet implemented in code)

### Quality Gate for Sourced Content (original plan's Area 4 - never built)

The original 4-area format-pivot plan's 4th area was never built under that name - Component 4 was redirected to sourcing-setup/UI work instead, at the user's explicit request. This is genuinely still missing:

- **Tier 1 (sourcing-time)**: `CopyrightRiskGate` currently checks popularity/length/blocklist from metadata alone. It does NOT yet reject sub-480p-adjacent format garbage or image-only/GIF posts beyond what the existing `MIN_SOURCE_RESOLUTION_HEIGHT` check already catches - worth a second look at whether that's sufficient.
- **Tier 2 (pipeline-entry gate) - the real gap**: nothing validates the actual DOWNLOADED file before it reaches Step 1 (`analyze_video`). A corrupt/truncated download, or a genuinely unusable file that slipped past the metadata-only gate, currently wastes a full pipeline run before failing somewhere downstream. The plan was to reuse `agents/quality_control.py`'s existing `VideoValidator` class with source-appropriate thresholds (reject <10s or >20min raw source, corrupt/no-video-track) right after download, before Step 1 - same validator, different thresholds than the finished-Short 15-45s check, per this session's established "don't let two independently-hardcoded checks drift apart" lesson (that's literally what caused Bug 5's caption-region false positive).
- **Loud rejections**: a rejected downloaded clip should write `data/sourcing/rejected/{platform}_{id}_REJECTED.txt` stating exactly which check/threshold it failed, same pattern as this session's other rejection-file work (QC failure files, sourcing alerts).
- **Verification plan**: feed a too-short, too-long, and corrupt test source through both tiers; confirm correct rejection files and that nothing bad reaches Step 1.

This is comparatively small scope - mostly wiring an existing validator to a new call site plus the rejection-file convention - and is the natural next candidate for "Component 5" if the user wants to proceed with it.

### Other known gaps, carried forward or newly surfaced

- **`agents/watcher.py`'s in-memory-only dedup** (`self.processed_files = set()`, lost on every restart) - a pre-existing gap, deliberately NOT fixed. `SourceRegistry` routes around it for autonomously-sourced clips, but a manually-dropped video that gets re-added to `input/` after a restart could still be reprocessed. Flagged repeatedly, never actioned - still open.
- **TikTok/Instagram publishers** (`core/publisher.py`) are implemented per each platform's documented API shape but have never been exercised against a live endpoint (no approved TikTok app, no live Instagram Business token available in any session so far) - review against current platform docs before ever flipping `AUTO_POST_TIKTOK`/`AUTO_POST_INSTAGRAM` on.
- **Twitter/X sourcing** was deliberately deferred at the start of the format-pivot planning (no existing credentials/library, paid API tier) - still deferred, no code exists for it.
- **YouTube Analytics OAuth** (`python -m agents.analytics_feedback setup`) has not been run in any session - `PostingScheduleOptimizer` and the 48h/7d performance checks all degrade gracefully without it, but posting-time optimization stays on generic defaults (noon/5pm/8pm) until it has real posted-hour-vs-performance data, which itself requires the YouTube upload OAuth AND enough real posting history to accumulate.
- **None of Phase 2's code has run against real APIs, real ffmpeg/moviepy, or a real browser.** Every verification this session used fake-object test harnesses (`praw`/`yt_dlp`/`anthropic`/`flask`/`moviepy` stubbed via `sys.modules` injection) because this sandbox has none of those packages installed. This is a materially different confidence level than "tested" - see the home-machine to-do list below.

---

## HOME MACHINE TO-DO LIST

Everything below is either still-pending from before this session (items 1-4, never confirmed done) or newly required by Phase 2 (items 5+). Do these in order before trusting any autonomous behavior in production, and especially before ever setting `AUTO_POST_YOUTUBE=true`.

1. **Pull latest from `main`.** `git pull origin main` (or re-clone) - confirm you're on commit `16673d5` or later.

2. **Add real music files to `assets/music/`.** Still just a README as of the last confirmed check - Bugs 1/2's audio fixes can't be meaningfully verified without real tracks present (an empty folder silently degrades to voiceover-only, which falsely looks like "Bug 1 fixed" without ever exercising Bug 2's ducking logic). Supported formats: `.mp3/.wav/.m4a/.aac/.ogg/.flac`.

3. **Set `CAPTION_FONT_PATH` in `.env`.** `fc-list | grep -i dejavu` (or your preferred gaming-style font), then set the printed path. Not strictly required (Bug 3's fallback chain will find something), but recommended for a known-good, on-brand font.

4. **Run a clean real-hardware pipeline test.** Confirm all 5 Phase 1 bugs actually stay fixed outside fake-object test harnesses - this has not been confirmed since the last handoff. Pay particular attention to Bug 4's duration logging (its fix was a best-effort heuristic never validated against the original broken source file) and Bug 5's per-clip `*_ERROR.txt`/`*_QC_ERROR.txt` files.

5. **Run `python main.py --verify`.** Confirms ffmpeg, ImageMagick (real render test), Kokoro model files, `ANTHROPIC_API_KEY` (live call), Reddit credentials (live call), `YOUTUBE_API_KEY`, yt-dlp (live test search), music folder, and caption font - all in one command, before starting anything else.

6. **Run the sourcing integration test.** `python tests/test_clip_sourcing_integration.py` - should print `21/21 checks passed`. This runs entirely offline (fake praw/yt-dlp), so it's safe to run on any machine regardless of credentials, and worth re-running after any future change to `agents/clip_sourcing.py`.

7. **Populate `config/source_channels.json`** via the dashboard's Sources tab (or leave it empty - trending/search-query sourcing still works independently, curated-channel sourcing just contributes nothing until at least one channel is added).

8. **Dry-run the sourcing agent for real** before it ever downloads anything: `python -m agents.clip_sourcing --dry-run`. Review what it WOULD download and why, against real live Reddit/YouTube data.

9. **Review `config/content_calendar.json`** (`posts_per_day`, `format_mix`) and the copyright-gate thresholds in `.env` (`MIN_REDDIT_SCORE`, `MIN_YOUTUBE_VIEWS`, `MAX_SOURCE_CLIP_SECONDS`, `MIN_SOURCE_RESOLUTION_HEIGHT`) - defaults are in place and were reviewed during this session, but this is your channel and your risk tolerance to confirm.

10. **Run `python -m core.publisher setup-youtube` once** (interactive OAuth) - required before `AUTO_POST_YOUTUBE` can ever actually post anything, independent of the flag's value. Do this well before you intend to flip the flag on, so you can confirm it worked with `AUTO_POST_YOUTUBE` still `false`.

11. **Optionally run `python -m agents.analytics_feedback setup`** (YouTube Analytics OAuth) - not required, but the posting-schedule optimizer and the 48h/7d performance checks both improve once this is authorized and enough real posting history accumulates. Everything degrades gracefully without it.

12. **Let one full autonomous cycle run with `AUTO_POST_YOUTUBE` still `false`.** Sourcing → gate → pipeline → format-scripted Shorts → QC → packaging → queued (not posted). Manually review the queued batch's actual output before ever flipping the flag.

13. **Set `DOWNLOAD_COST_PER_GB_USD`** only if deploying to a metered cloud host - leave at `0.0` (the default) for a home machine with no metered bandwidth.

14. **Only after all of the above:** set `AUTO_POST_YOUTUBE=true` if and when you're ready for genuinely zero-touch autonomous publishing. Re-read this document's Component 3 section first - there is no review step once this is on.

15. **If you change `config/source_schedule.json`** (via the dashboard or by hand) after `main.py` is already running, restart it - sourcing jobs are registered once at startup, not re-read live.

---

## HOW TO RESUME THIS PROJECT

1. Read this HANDOFF.md top to bottom.
2. `git log --oneline -20` and `git status` to confirm exactly which fixes/components have landed and on which branch/remote.
3. Both Phase 1 (5 bugs) and Phase 2 (Components 1-4) are complete and on `main`. Work through the HOME MACHINE TO-DO LIST above before trusting any of it in production.
4. The next candidate body of work is the Quality Gate for Sourced Content (see "WHAT STILL NEEDS BUILDING" above) - scoped but not built. Don't start building it until the user explicitly asks.
5. Everything in Phase 2 was verified with fake-object test harnesses only (this sandbox has no `anthropic`/`praw`/`yt_dlp`/`flask`/`moviepy`/etc. installed) - treat it as "logic verified, never run for real" until the home-machine to-do list has been worked through.

---

## DOCUMENT META

**Document created:** 2026-07-02
**Last updated:** 2026-07-07, full handoff rewrite after the format-pivot session (Components 1-4 complete) - added Phase 2 section, flagged that the original plan's "Quality Gate for Sourced Content" area was redirected to different Component 4 scope and remains unbuilt, rewrote the home-machine to-do list to merge still-pending Phase 1 items with new Phase 2 setup/verification steps in priority order.
**Status:** Phase 1 (5 bugs) and Phase 2 (Components 1-4 of the format pivot) are both complete and on `main`. Next milestone: work through the HOME MACHINE TO-DO LIST (real-hardware pipeline test still unconfirmed since before this session; all Phase 2 sourcing/publishing/dashboard code needs its first real-API exercise). Quality Gate for Sourced Content is the scoped-but-not-built next candidate.
