---
type: department
business: shared
status: template
updated: 2026-07-16
---

# Business Philosophy & Best Practices (department definition)

This one isn't really a "manager" in the same sense as the other seven —
it's the baseline every department operates inside of. It's where you write
down the operating principles that are true across all three businesses,
so a new decision anywhere can be checked against "does this match how we
actually run things" instead of being decided from scratch each time.

## What belongs here (shared, across all businesses)

- Non-negotiables: things you won't do regardless of upside (e.g. Chaos
  Merchant's own `AUTO_POST_YOUTUBE` design — autonomous publishing is
  opt-in and reversible, never silently defaulted on; that's a philosophy
  decision, not just a technical one)
- How you make decisions when data is incomplete
- How much autonomy AI agents get before a human reviews their output,
  as a general principle (each business's note can set stricter rules,
  never looser ones, than whatever's set here)
- What "done" or "good enough to ship" means across your businesses

## What does NOT belong here

- Business-specific tactics — those go in that business's own note under
  the relevant department
- One-off decisions — those go in [[You]]'s decision log or the specific
  business's note

## Starter principles (edit these — this is a first draft, not gospel)

- Fail loud, not silent. A system that quietly does the wrong thing is
  worse than one that visibly breaks (this is a real, tested principle
  from Chaos Merchant's own bug-fixing history — see that business's R&D
  section for the concrete version of this).
- Autonomy is earned, not assumed. New AI-agent capability starts with a
  human-reviewed step before it's trusted to run fully unattended.
- Verify the artifact, don't trust the process. If a step reports success,
  check the actual output before believing it.

## Per-business application

- [[Chaos-Merchant#Business Philosophy]]
- [[Clixon#Business Philosophy]]
- [[Phone-Agent#Business Philosophy]]
