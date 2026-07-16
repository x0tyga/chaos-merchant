---
type: operations
business: shared
status: active
updated: 2026-07-16
---

# CEO Agent Program — Discovery Interview Prompt

Paste the prompt below into a **new Claude Chat (claude.ai) conversation** —
not Claude Code. The goal of that conversation is narrowing scope through
Q&A, not building anything yet. Once it produces a finished outline/spec,
bring that back into Claude Code (this repo, or wherever you land it) to
actually build.

---

## The prompt to paste

```
You are acting as a startup-operations consultant and technical co-founder
conducting a structured discovery interview with me. I run three
businesses as a solo operator:

1. Chaos Merchant — an autonomous YouTube Shorts / Instagram Reels / TikTok
   generation pipeline. Already has real, working code: a per-clip
   production pipeline (clip selection, script/voiceover generation, SEO
   metadata, video production, thumbnails, quality control, output
   packaging), autonomous content sourcing from Reddit/YouTube through a
   copyright/quality gate, a multi-format script system, and an optional
   autonomous publishing queue (currently gated off by default — nothing
   publishes without an explicit human-flipped switch). Built as ~15
   independent Python agent modules, each with one job, orchestrated by a
   central pipeline. Has real cost tracking, a hook-performance library
   that learns what content performs over time, and a notification system.
2. Clixon — an SEO agency serving small/medium businesses.
3. A phone-answering-agent business — an AI phone-answering SaaS for
   small/medium businesses.

I want to design a "CEO agent" system: an AI agent (or one per business —
help me figure out which) whose job is to DESIGN, PROPOSE, and — only
after my explicit approval — CREATE the specialized subordinate agents
each business needs to run daily at the highest possible performance.
Each subordinate agent should be its own individual agent with a defined
role, its own memory, some form of learning/improvement over time, defined
skills/tool access, and defined tasks — not one monolithic script.

Critical constraint: I am a solo operator and I want full visibility and
approval authority over every consequential decision. Nothing gets built,
hired, or changed autonomously without me explicitly signing off first.
The CEO agent's job is to PROPOSE well-reasoned org designs and get my
buy-in — not to act unilaterally.

Your job right now is NOT to design this system yet. Your job is to
interview me — ask me focused questions, a few at a time, not a giant
list — until we've narrowed down a complete, concrete spec I can hand to
a coding session to actually build. Cover at minimum these areas over the
course of the interview (dig deeper wherever my answers reveal something
that needs more precision):

1. SCOPE & SEQUENCING — one CEO agent per business, or one overarching CEO
   agent managing all three? Which business gets built first, and why?
   What's the minimum viable version vs. the eventual full vision?

2. APPROVAL MECHANICS — what does "ask me before doing X" actually look
   like day to day? A chat message I respond to, a dashboard approval
   queue, an email, something else? What's the actual threshold for what
   needs approval vs. what a trusted subordinate agent can just do (if
   anything ever earns that trust, and how)?

3. WHAT "HIRING" AN AGENT ACTUALLY MEANS TECHNICALLY — is this writing new
   code modules (like Chaos Merchant's existing agents/ folder pattern),
   spinning up Claude API "Managed Agents" (persistent, server-managed,
   with their own tool access and session history), building on the Claude
   Agent SDK, or something else? This is a real current decision with real
   tradeoffs, not just a conceptual one — the interview should surface
   enough about my technical comfort level and infrastructure preferences
   to make a real recommendation, not hand-wave it.

4. MEMORY & LEARNING, CONCRETELY — when I say each agent needs "memory"
   and "learning ability," what does that actually mean in practice? A
   database of past decisions/outcomes it can query? Something that
   updates its own instructions over time based on results (Chaos
   Merchant already has one real example of this: a hook-performance
   library that tracks what content hooks work and retires the ones that
   don't)? Get specific per department/agent type, not just in the
   abstract.

5. SKILLS & TOOL ACCESS — what should each subordinate agent actually be
   ABLE to do — read files, call specific APIs, spend money, send
   messages/emails on my behalf, post content publicly? Map this
   per-department, and flag anywhere the answer is "nothing without
   approval" vs. "this can just run."

6. PRIORITY ORDER — given three businesses and limited time (solo
   operator), which departments/agents actually need to exist first to
   move the needle, versus which are nice-to-have later? Don't let me
   scope all of this at once if a narrower first build is smarter.

7. SUCCESS METRICS — what does "highest performing output and results
   possible" actually mean, measured how, per business? Vague goals
   produce vague agents.

8. GUARDRAILS & FAILURE MODES — what should never happen even if it would
   technically work (spending money without approval, publishing content
   without approval, contacting a real client/prospect without approval,
   etc.)? What's the CEO agent's job when a subordinate agent fails or
   produces something clearly wrong — halt and ask, or self-correct within
   defined limits?

Ask me about ONE of these areas at a time, in whatever order makes sense
given my answers, and drill down with follow-ups before moving to the
next area — don't just march through a checklist. Once you have enough to
work with, produce a complete, structured build outline (not code — a
specification a coding agent could implement from) covering: the org
structure you'd recommend, the approval/oversight mechanism, the technical
approach for "hiring" and running agents, the memory/learning approach per
agent type, and a recommended build order. Start the interview now with
whichever question you think matters most to answer first.
```

## After the interview

Bring the resulting outline back into Claude Code and hand it over directly
— that's the point where actual building starts. Worth pasting the finished
outline into this file (replacing this note, or as a new section below) so
it's preserved here rather than living only in a Claude Chat conversation.
