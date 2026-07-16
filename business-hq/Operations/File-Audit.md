---
type: operations
business: shared
status: active
updated: 2026-07-16
---

# File Audit — doc health across all businesses

A running checklist, not automated. The point: docs rot silently (a
HANDOFF.md that says "next step X" three sessions after X was already
done is worse than no doc at all, since it actively misleads). Check this
periodically, especially before starting a new work session on any
business.

## Chaos Merchant

| File | Purpose | Last known state |
|---|---|---|
| `HANDOFF.md` | Current state / next action, rewritten each session | Active, kept current — this is the one to read first when resuming work |
| `KNOWN_ISSUES.md` | Bug/limitation history with status | Last full update predates the most recent bug-fix + Quality Gate work — due for a refresh pass |
| `CLAUDE.md` | Architecture/modification guide for AI agents working in this repo | Stable, update when architecture actually changes |
| `README.md` | Human-facing setup/quick-start | Should be checked against `.env.example` periodically — new env vars have been added faster than README's config section has been updated |
| `.env.example` | Every env var, documented inline | Kept current as vars are added — this is actually the most reliable single source of truth for config right now |

**Standing audit question for this business**: does `KNOWN_ISSUES.md` still
match reality, or has HANDOFF.md's fast-moving current-state log outpaced
it? (As of this note's writing: yes, due for a sync pass.)

## Clixon

*(no docs audited yet — once you're in that repo, list its equivalent docs
here: does it have anything like a HANDOFF.md/README/known-issues doc at
all, or does this vault become the first place that exists?)*

## Phone Agent

*(same as Clixon — not yet audited)*

## General audit questions to ask, per business, periodically

- Does the "next step" the doc claims match what's actually true right now?
- Are there decisions made in conversation/chat that never made it into a
  doc at all (the single biggest way context gets lost between sessions)?
- Is there config/env documentation that's drifted from the actual code?
