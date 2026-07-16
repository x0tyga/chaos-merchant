---
type: business
business: chaos-merchant
status: active
updated: 2026-07-16
---

# Chaos Merchant

Autonomous YouTube Shorts / Instagram Reels / TikTok generation pipeline.
Takes source gaming footage (increasingly self-sourced from Reddit/YouTube,
not just manually dropped) and produces finished, captioned, branded
vertical Shorts with per-clip scripts, voiceover, SEO metadata, and
thumbnails — with an optional fully-autonomous publishing queue.

Full technical detail lives in this repo's own `CLAUDE.md`, `HANDOFF.md`,
and `KNOWN_ISSUES.md` — this note is the business-layer view on top of that,
organized by department.

## Marketing

Unusually, Marketing and Product are close to the same thing here: the
Shorts themselves ARE the marketing — there's no separate ad campaign
driving traffic, distribution is algorithmic (platform recommendation
engines) plus on-video SEO (titles/hashtags/keywords, handled per-clip by
`agents/seo_optimizer.py`).

- **Positioning**: currently gaming-content reaction Shorts, actively
  pivoting toward format-templated content (news recap, hidden details,
  ranking, comparison) — see Strategic Planning below for why.
- **Brand consistency**: channel name/watermark applied per-short
  (`BrandingOverlay`), caption styling now fixed at 80% frame height / 80px
  bottom margin.
- **Channel/thumbnail strategy**: `agents/thumbnail_research.py` scrapes
  trending Shorts thumbnails weekly and cross-references against this
  channel's own CTR once enough data exists.
- Open question: no brand voice/personality has been defined yet for the
  new multi-format approach — worth a real pass once real posted data exists.

## Outreach

No direct outreach function currently exists — distribution is entirely
algorithmic/platform-driven, not relationship-driven. This is worth
revisiting if:
- Cross-promotion/collab opportunities with other channels become relevant
- Sponsorship/brand-deal outreach becomes a monetization angle (would be a
  new capability, not something the current pipeline does)

## Reporting

Real, not aspirational — this is one of the more built-out departments:

- `agents/analytics_feedback.py`: real YouTube Data API + Analytics API
  pulls at 48h/7d marks, spike detection (3x views/6h → desktop
  notification), confidence-gated prompt auto-tuning
- `core/memory.py`'s `ChannelMemory.get_format_performance()`: CTR/
  retention/viral_score per script format (report-only — no automatic
  reallocation yet, a deliberate launch decision)
- Hook Library: tracks every hook used, CTR/retention per hook, status
  progression new → testing → proven_winner/declining
- Dashboard Analytics page: real spend + performance charts, once
  `dashboard/app.py` is actually run

Everything above is real code, verified only against fake-object test
harnesses so far — **zero of it has run against a real posted video yet**
(see R&D's "unverified" note below).

## Sales Ideology & Pitching

Doesn't apply in the traditional sense — there's no customer being sold to.
Revenue model is platform monetization (YouTube Partner Program primarily;
TikTok/Instagram monetization mechanisms differ and aren't specifically
built out yet). If sponsorships/brand deals ever become part of the model,
THAT would introduce a real Sales function (pitching to sponsors) — doesn't
exist today.

## Research & Development

This is where almost all the actual work has happened. Current state:

- **Production pipeline** (Steps 1-9): clip intelligence → per-clip script/
  voiceover → per-clip SEO → video production (captions/ducking/color
  grading/branding) → per-clip thumbnails → quality control → output
  packaging → posting-queue enqueue
- **Format pivot** (recently completed): moved from single-format emotion-
  reaction scripts to 5 format templates (hidden details, news recap,
  ranking, comparison, reaction) selected by `agents/format_selector.py` —
  reaction is now hard-gated to only very high viral-score clips
- **Autonomous sourcing**: `agents/clip_sourcing.py` pulls candidate clips
  from Reddit + YouTube through a copyright/quality gate (popularity
  threshold, max length, blocklist, and — as of this session — real
  post-download file validation, not just metadata) before they ever enter
  the pipeline
- **Autonomous publishing**: content calendar + posting queue + schedule
  optimizer; `AUTO_POST_YOUTUBE` is off by default and is a one-time safety
  switch, not a review queue (see Business Philosophy below)
- **Known-issues tracking**: this repo's `KNOWN_ISSUES.md` is the working
  example of what an R&D known-issues log looks like in practice
- **Current real gap**: none of Phase 2 (format pivot + sourcing +
  publishing) has run against real Reddit/YouTube/Anthropic APIs, real
  ffmpeg/moviepy, or a real browser yet — everything verified with
  fake-object test harnesses only. See this repo's `HANDOFF.md` "HOME
  MACHINE TO-DO LIST" for the actual path to a first real-hardware run.

## Strategic Planning

Two major pivot decisions made and built out this cycle:

1. **Format pivot** — moved away from single-note emotion-reaction content
   (read as synthetic/AI-slop) toward multiple structured formats, on the
   reasoning that structured formats (rankings, comparisons, recaps) don't
   depend on a synthetic voice convincingly performing genuine emotion the
   way reaction content does.
2. **Autonomous sourcing** — moved away from requiring a human to manually
   drop source videos into the input folder, since that defeated the point
   of an "autonomous" pipeline. This is also the highest-risk decision made
   so far (sourced content publishes with NO human review once
   `AUTO_POST_YOUTUBE` is on — see Business Philosophy).

Open strategic question: whether/when to build a Quality Gate "Tier 1"
improvement (rejecting more garbage at the metadata-probe stage, before
download) — currently a small, non-blocking open item, not urgent.

## Accounting & Bookkeeping

- Real Claude API cost tracking (`core/cost_tracker.py`), wired into every
  real `.messages.create()` call site — not an estimate once running for
  real
- Download bandwidth cost tracking (`log_download_usage`), defaults to
  `$0.00/GB` (correct for a home-machine deployment with no metered
  bandwidth — only set `DOWNLOAD_COST_PER_GB_USD` if ever deployed to a
  metered cloud host)
- Rough current cost estimate: ~$2-5/month (Claude Haiku for most calls,
  Kokoro TTS free/local, Google Trends free)
- **Not yet built**: any revenue-side tracking. Makes sense — nothing has
  been published yet, so there's no revenue to track. This becomes a real
  gap the moment the channel goes live and starts earning anything.

## Business Philosophy

These aren't aspirational — they're principles that got established through
actually fixing real bugs this cycle, and are worth carrying to the other
two businesses:

- **Fail loud, not silent.** Multiple real bugs this cycle were caused by
  broad `try/except` blocks silently swallowing failures (captions failing
  to render with no signal, one bad clip in a batch silently killing the
  whole batch's output). The fix pattern every time was: log the full
  failure, and make the manifest/output honestly reflect what actually
  happened rather than what was supposed to happen.
- **Verify the artifact, don't trust the process reporting success.**
  Applied repeatedly: verifying an exported video file's real duration
  instead of trusting `write_videofile()`'s return, verifying a caption
  gain-envelope's actual render-time behavior instead of trusting the
  lambda was written correctly, verifying a downloaded file is a real
  decodable video instead of trusting yt-dlp's exit code.
- **Autonomy is opt-in and reversible, never silently assumed.**
  `AUTO_POST_YOUTUBE`/`AUTO_POST_TIKTOK`/`AUTO_POST_INSTAGRAM` all default
  to `false`. The system builds toward full autonomy deliberately, one
  verified layer at a time, rather than defaulting to "just do it and see."
