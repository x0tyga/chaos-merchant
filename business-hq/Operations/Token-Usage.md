---
type: operations
business: shared
status: active
updated: 2026-07-16
---

# Token / API Usage — cross-business rollup

Manual rollup for now — see README.md's "What this does NOT do yet" for why
this isn't auto-populated. Update this monthly by pulling each business's
own cost-tracking source.

## Chaos Merchant

Real tracking exists: `core/cost_tracker.py` logs every Claude API call's
actual token usage to `data/cost_log.json`, plus download-bandwidth cost
via `log_download_usage()`. Pull the monthly total from there.

| Month | Claude API spend | Download bandwidth | Notes |
|---|---|---|---|
| — | — | — | Not yet run for real; ~$2-5/month is the pre-launch estimate per HANDOFF.md |

## Clixon

No cost-tracking mechanism confirmed yet. If Clixon's operations use any
Claude/LLM API calls (content generation, report drafting, client
communication drafting, etc.), that's worth wiring up something equivalent
to Chaos Merchant's `cost_tracker.py` pattern — log every real API call's
token usage rather than estimate after the fact.

| Month | Spend | Notes |
|---|---|---|
| — | — | Not yet tracked |

## Phone Agent

No cost-tracking mechanism confirmed yet. This business likely has a
DIFFERENT cost shape than the other two — voice/telephony API costs scale
directly with call volume, not just with development/content-generation
activity, so cost-per-call-minute matters as much as total monthly spend
here. Worth tracking both.

| Month | Total spend | Cost per call-minute | Notes |
|---|---|---|---|
| — | — | — | Not yet tracked |

## Future automation idea (not built)

A small script per business that reads its own cost log (JSON/CSV/however
each business tracks it) and appends a row to that business's table above
automatically would remove the manual-rollup step. Not built — this file is
deliberately just a place to put numbers by hand until that exists.
