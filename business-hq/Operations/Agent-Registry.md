---
type: operations
business: shared
status: active
updated: 2026-07-16
---

# Agent Registry — every AI agent built, across all businesses

The point of this note: as more AI agents get built across all three
businesses, this is where you can see all of them at once — what exists,
what it does, whether it's autonomous or human-reviewed, and its current
status. Prevents rebuilding something that already exists in a slightly
different form, and keeps autonomy-level decisions visible (see
[[Business-Philosophy]]).

## Chaos Merchant

Production pipeline agents (`agents/`):

| Agent | Does | Autonomy level |
|---|---|---|
| `watcher.py` | Monitors input folder for new source videos | Fully autonomous |
| `clip_intelligence.py` | Scene detection + engagement scoring | Fully autonomous |
| `script_voiceover.py` | Per-clip script gen (Claude) + voiceover (Kokoro/ElevenLabs) | Fully autonomous |
| `format_selector.py` | Picks script format (hidden details/news recap/ranking/comparison/reaction) per clip | Fully autonomous (reaction hard-gated by viral score) |
| `seo_optimizer.py` | Per-clip SEO metadata | Fully autonomous |
| `video_production.py` | Captions, ducking, color grading, branding, export | Fully autonomous |
| `thumbnail.py` | Per-clip thumbnail brief/generation | Fully autonomous (Canva MCP or brief-only) |
| `quality_control.py` | Validates outputs, routes pass/warning/manual_review | Fully autonomous (routes to manual_review, doesn't gate a human in-line) |
| `output_packaging.py` | Assembles the deliverable batch folder | Fully autonomous |
| `clip_sourcing.py` | Discovers/downloads source clips from Reddit + YouTube through a copyright/quality gate | Fully autonomous |
| `analytics_feedback.py` | YouTube performance pulls, hook library updates, spike alerts | Fully autonomous (read-only against YouTube) |
| `trend_intelligence.py` | Daily trend brief (Reddit/RSS/Google Trends) | Fully autonomous |
| `competitor_monitor.py` | Competitive channel tracking | Fully autonomous |
| `comment_mining.py` | Comment sentiment/pattern analysis | Fully autonomous |
| `thumbnail_research.py` | Trending-thumbnail scrape + analysis | Fully autonomous |

Publishing (`core/publisher.py`, `core/posting_queue.py`): **the one place
autonomy is explicitly gated** — `AUTO_POST_YOUTUBE`/`AUTO_POST_TIKTOK`/
`AUTO_POST_INSTAGRAM` all default `false`. Everything above can run fully
unattended; whether content actually goes live publicly is a separate,
deliberate switch.

## Clixon

*(none registered yet — add here as agents get built: what does it
automate in service delivery, e.g. audit generation, report drafting,
outreach drafting)*

## Phone Agent

*(none registered yet — add here as agents get built: the core
conversation agent itself is presumably the first entry once you're
tracking this properly, plus anything automating scheduling/CRM
integration/escalation logic)*
