---
type: meta
status: active
updated: 2026-07-16
---

# 🏠 Home

Dashboard for all businesses. Requires the **Dataview** community plugin for
the tables below to populate automatically — see `README.md` if you haven't
installed it yet. Without Dataview, use the plain links in each section
instead.

## Businesses

```dataview
TABLE status, updated
FROM "business-hq/Businesses"
SORT business ASC
```

- [[Chaos-Merchant]] — YouTube Shorts / Reels / TikTok generation automation
- [[Clixon]] — SEO agency for SMBs
- [[Phone-Agent]] — AI phone-answering agent for SMBs

## Departments (the shared "manager" definitions)

```dataview
TABLE status, updated
FROM "business-hq/Departments"
SORT file.name ASC
```

- [[Marketing]]
- [[Outreach]]
- [[Reporting]]
- [[Sales-Pitching]]
- [[RD]] (Research & Development)
- [[Strategic-Planning]]
- [[Accounting-Bookkeeping]]
- [[Business-Philosophy]]

## Operations (cross-business tracking)

- [[Token-Usage]] — Claude API spend, per business
- [[Agent-Registry]] — every AI agent built, across all businesses, what it does, its status
- [[File-Audit]] — doc health / staleness checklist, across all businesses

## Anything needing your attention right now

```dataview
TASK
FROM "business-hq"
WHERE !completed
```

This pulls any unchecked `- [ ]` task from anywhere in this folder into one
list. Add tasks directly in whichever business/department note they belong
to — they'll surface here automatically once Dataview is running.

## People

- [[You]]
