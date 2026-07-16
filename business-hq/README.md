---
type: meta
status: active
updated: 2026-07-16
---

# business-hq — portable ops vault template

This folder is **not part of the Chaos Merchant codebase.** It's a self-contained,
portable Obsidian vault template covering all three of your businesses:

- **Chaos Merchant** (this repo) — YouTube Shorts / Instagram Reels / TikTok generation automation
- **Clixon** — SEO agency for small/medium businesses
- **Phone Agent** — AI phone-answering agent for small/medium businesses

It lives inside this repo right now only because this is the one place this
session can actually write and commit files that survive. Move it once you're
set up properly — see "How to actually use this" below.

## What's in here

```
business-hq/
├── 00-Home.md              ← open this first; the dashboard note
├── People/
│   └── You.md              ← top of the hierarchy
├── Departments/            ← the 8 "manager" roles, defined ONCE, reused by every business
│   ├── Marketing.md
│   ├── Outreach.md
│   ├── Reporting.md
│   ├── Sales-Pitching.md
│   ├── RD.md
│   ├── Strategic-Planning.md
│   ├── Accounting-Bookkeeping.md
│   └── Business-Philosophy.md
├── Businesses/
│   ├── Chaos-Merchant.md   ← REAL content — I have full context on this one
│   ├── Clixon.md           ← DRAFT — general SEO-agency best practices, not your actual specifics
│   └── Phone-Agent.md      ← DRAFT — general AI-phone-agent-SaaS best practices, same caveat
└── Operations/              ← cross-business tracking
    ├── Token-Usage.md
    ├── Agent-Registry.md
    └── File-Audit.md
```

**Read the Clixon and Phone Agent business notes as a starting skeleton to edit,
not a description of your actual business.** I don't have any real information
about either — no repo access, no context in this conversation. Everything in
those two files is general best practice for "an SEO agency serving SMBs" and
"an AI phone-answering SaaS serving SMBs" as business categories. Correct it
once you're in those repos.

## The hierarchy model

```
You (top level)
  └── one Departments/*.md definition per role (Marketing, Outreach, Reporting,
      Sales & Pitching, R&D, Strategic Planning, Accounting & Bookkeeping,
      Business Philosophy) — these describe WHAT each "manager" does, generically
        └── each business's file has one section per department, tailoring
            that generic role to what it actually means for THAT business
```

One department definition, three tailored applications. When you add a 4th
business later, you write one more `Businesses/<name>.md` and don't touch
`Departments/` at all unless the role itself needs to change everywhere.

## How to actually use this

**Obsidian vaults are just folders** — no database, no import step. To get
the full cross-business picture (this repo + Clixon's repo + the phone-agent
repo all in one vault, cross-linkable, one graph view, one Dataview query
surface), the cleanest structure on your actual machine is:

```
~/AllBusinesses/              ← open THIS folder as your Obsidian vault
├── business-hq/              ← this folder, moved here
├── chaos-merchant/           ← full clone of this repo
├── clixon/                   ← full clone of that repo
└── phone-agent/              ← full clone of that repo
```

Obsidian recursively indexes every `.md` file under the vault root regardless
of how deep it is, so once it's arranged like that, all four projects' docs
(HANDOFF.md, KNOWN_ISSUES.md, README.md, whatever Clixon/Phone Agent have)
become part of one searchable, linkable, graph-viewable vault automatically
— nothing needs to be copied or converted.

Steps:
1. Install Obsidian, install the **Dataview** community plugin (Settings →
   Community plugins → browse → search "Dataview") — required for the
   auto-updating tables in `00-Home.md` and the department notes to work.
   Without it, this is still fully readable, just static.
2. Create `~/AllBusinesses/`, clone all three repos into it, move this
   `business-hq/` folder in alongside them (out of `chaos-merchant/`).
3. Open `~/AllBusinesses/` as an Obsidian vault.
4. Open `00-Home.md` and pin it (or use the community "Homepage" plugin to
   make it load by default).
5. Once you've moved `business-hq/` out, delete it from the chaos-merchant
   repo (or leave a stub — your call) so the codebase repo isn't carrying a
   business-ops folder that doesn't belong to it long-term.

## Frontmatter convention (why the queries in 00-Home.md work)

Every note in here has YAML frontmatter at the top:

```yaml
---
type: department | business | operations | meta | person
business: shared | chaos-merchant | clixon | phone-agent
status: template | draft | active
updated: YYYY-MM-DD
---
```

Dataview queries in `00-Home.md` filter on these fields. Keep using this
schema on any new note you add and the dashboard keeps working without
editing the queries themselves.

## What this does NOT do yet

- **No live token-usage import.** `Operations/Token-Usage.md` is a manual
  rollup format for now, seeded with how Chaos Merchant already tracks this
  for real (`core/cost_tracker.py` → `data/cost_log.json`). A script that
  dumps each business's cost log into a markdown table here is a reasonable
  future addition — not built yet, don't assume it's automatic.
- **No file-staleness automation.** `Operations/File-Audit.md` is a manual
  checklist, seeded with Chaos Merchant's real doc set as a working example.
- **Wikilinks (`[[Note Name]]`) don't render as links on GitHub** — only in
  Obsidian. If any of these files also need to display correctly on GitHub,
  keep that in mind before linking heavily.
