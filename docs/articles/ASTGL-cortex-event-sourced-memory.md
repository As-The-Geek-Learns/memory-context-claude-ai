# Cortex: An Event-Sourced Memory Architecture for AI Coding Assistants

**As The Geek Learns | Technical Deep Dive**
**Author:** James Cruce
**Date:** February 2026

---

## The Problem Every AI Developer Knows Too Well

You've been working with Claude Code for two hours. It understands your codebase intimately. It knows you rejected MongoDB because you need zero-config deployment. It remembers the authentication approach you chose and why. It's halfway through a five-step refactoring plan.

Then the session ends.

The next session begins with total amnesia. Claude suggests MongoDB. It re-reads files it already analyzed. It asks questions you answered an hour ago. You spend 30 minutes re-establishing context that evaporated at the session boundary.

**This is the single most painful aspect of working with AI coding assistants today.**

The cruelest irony? The better the AI performs within a session — deeper exploration, more nuanced understanding, more careful planning — the MORE devastating the loss when the session ends. Excellence within a session amplifies the frustration at its boundary.

---

## What Gets Lost (A Taxonomy of Amnesia)

Through rigorous analysis, I identified five categories of information destroyed at every session boundary:

### Category 1: Architectural Understanding
The AI builds a mental model of your codebase through exploration — how components relate, which patterns are used, where the important logic lives. This understanding takes significant token investment to build. Gone.

### Category 2: Decision History
During a session, the AI evaluates multiple approaches, rejects some with specific reasoning, selects others. Without this decision trail, it will re-suggest previously rejected approaches, wasting your time on explanations already given.

### Category 3: Work State
Multi-step plans, in-progress tasks, partial implementations, test results — the overall progress of complex work. The next session cannot seamlessly resume; it must rediscover the current state from scratch.

### Category 4: Tool & Environment State
Modified files, git state, environment configuration, your tooling preferences. Implicitly known during a session, not carried forward.

### Category 5: Conversational Nuance
Your preferences, communication style, implicit priorities, the collaborative rapport built during a session. Ephemeral.

### The Cascade Effect

Information loss creates cascading secondary problems:

1. **Re-exploration waste**: 10-30 minutes spent re-reading files
2. **Decision regression**: Re-suggesting rejected approaches, eroding trust
3. **Plan fragmentation**: Multi-step work loses coherence
4. **Cognitive burden shift**: YOU become the memory system

---

## The Research Journey

I spent weeks researching this problem using an AI assistant WITH the context window problem to design a solution FOR the context window problem. The meta-irony was not lost on me.

### Surveying 15+ Existing Solutions

I examined academic architectures (MemGPT, MIRIX, Nemori) and community tools (claude-cortex, memory-mcp, claude-diary). Nine distinct design patterns emerged:

| Pattern | Automatic | Semantic | Scalable |
|---------|:---------:|:--------:|:--------:|
| Static file injection | No | No | Limited |
| Manual checkpointing | No | No | Medium |
| Hook-based capture | Yes | No | Medium |
| Two-tier (brief + store) | Yes | Partial | Good |
| Salience-scored + decay | Yes | Yes | Good |
| OS-style virtual memory | Yes | Yes | Excellent |

### Eight Candidate Architectures

Through two rounds of brainstorming, I developed:

1. **Cognitive Journal** — Human-readable structured entries
2. **Memory Palace** — Salience scoring with decay
3. **Git-for-Thought** — Branch-aligned context
4. **Event Sourcery** — Append-only event log
5. **Dual-Mind** — Scribe + Sage separation

Then three hybrids combining the best ideas:

6. **Cortex** — Event sourcing + projected briefings
7. **Engram** — Neural-inspired memory consolidation
8. **Chronicle** — Git-native version control

### Quantitative Scoring

I applied an 11-criteria weighted scoring framework across 210 total points. After two rounds of comparison:

**Winner: Cortex (185/210)** — 14-point margin over the runner-up.

---

## The Cortex Architecture

Cortex is an **event-sourced memory system** with three key innovations:

### Innovation 1: Three-Layer Event Extraction

Context is captured automatically through three independent extraction layers:

**Layer 1 (Structural)**: Parses tool call metadata from Claude Code hook payloads. When Claude reads a file, runs a command, or modifies code, the hook captures it. 100% accuracy for its scope — this is objective data.

**Layer 2 (Semantic)**: Pattern-matches Claude's response text for decision markers. Looks for phrases like "Decision:", "Rejected:", "Fixed:", "Learned:" at line starts. Confidence-scored based on pattern strength.

**Layer 3 (Self-Reporting)**: Claude flags important context via `[MEMORY: ...]` tags. You tell Claude about this mechanism, and it proactively tags decisions worth remembering. Highest accuracy because it's deliberate intent.

```python
# Example: Claude tags a decision
[MEMORY: Using SQLite for storage — zero-config, single file, no external dependencies.]
[MEMORY: Rejected MongoDB — overkill for single-user; no need for scaling.]
```

**[ASTGL CONTENT]** The "many independent extractors" pattern appears across NLP pipelines, content classification, and log analysis. Each extractor looks for one signal type. They compose through aggregation + dedup. The alternative — a monolithic extractor with complex branching — becomes unmaintainable as signal types grow.

### Innovation 2: Projected Briefings

Instead of replaying raw events, Cortex generates **token-budget-aware briefings**:

```markdown
# Cortex Session Briefing
Generated: 2026-02-14 09:15:00 | Branch: main | Events: 47

## Active Decisions
- **Authentication**: JWT with refresh tokens (rejected session cookies — stateless requirement)
- **Database**: SQLite with WAL mode (rejected PostgreSQL — zero-config priority)

## Current Plan
1. [x] Set up project structure
2. [x] Implement data models
3. [ ] Add API endpoints ← YOU ARE HERE
4. [ ] Write tests
5. [ ] Deploy to staging

## Recent Knowledge
- Config file format changed to TOML (2 sessions ago)
- Tests require PYTHONPATH set (discovered yesterday)
```

The briefing fits within a token budget (default 2000 tokens, ~0.1% of context window). Decisions are "immortal" — they never decay out of the briefing. Tactical knowledge fades over sessions.

**[ASTGL CONTENT]** The "immortal vs. bounded" design tension appears everywhere: never lose critical data vs. respect resource limits. The resolution is to separate retention from representation. Keep everything in the store; compress what you show.

### Innovation 3: Progressive Tiers

Cortex uses progressive complexity tiers — start simple, upgrade when needed:

| Tier | Install Time | What You Get |
|------|-------------|--------------|
| **Tier 0** | 30 seconds | JSON storage, three-layer extraction, basic briefing |
| **Tier 1** | 2 minutes | SQLite + FTS5, snapshot caching, migration CLI |
| **Tier 2** | 5 minutes | Vector embeddings, hybrid search, anticipatory retrieval |
| **Tier 3** | 10 minutes | MCP server, branch alignment, git-tracked projections |

Each tier builds on the previous. You get value immediately and upgrade when the additional capability matters.

---

## Implementation Learnings

### The Build Backend Gotcha

**[ASTGL CONTENT]** `setuptools.build_meta` is the one true build backend string for setuptools. The original scaffold had `setuptools.backends.build_meta` which gives a confusing `ModuleNotFoundError: No module named 'setuptools.backends'` at install time. This is a common pyproject.toml pitfall.

### Event Sourcing vs. CRUD

**[ASTGL CONTENT]** The difference between "store the latest state" (CRUD) and "store every fact that happened" (event sourcing) becomes concrete when you build it. The Event model is immutable; all views are projections. This makes the system naturally auditable — you can always answer "why did the system think X?"

### Defensive Defaults Pattern

**[ASTGL CONTENT]** When building systems that must never crash (like Claude Code hooks), every `.get()` needs a default, every JSON parse needs a try/except, and every function that could fail returns a safe fallback. The pattern is: `try: parse → except: return defaults`. This is enterprise-grade error handling for a developer tool.

### Content Hash Scoping

**[ASTGL CONTENT]** Deduplication hashes need careful scoping. Hashing just the content would miss that the same text as a "decision" vs. "knowledge" is semantically different. Hashing the ID would prevent all dedup. The sweet spot: `hash(type + content + session_id)`.

### GitHub Action ≠ Free CLI Tool

**[ASTGL CONTENT]** The gitleaks GitHub Action requires a paid license for org accounts, but the gitleaks CLI is completely free. Many security scanning actions monetize the GitHub integration while the underlying tool remains open-source. Always check if you can run the CLI directly before paying for the wrapper.

### Confidence as Architecture

**[ASTGL CONTENT]** Making confidence a first-class field on every event (not just a boolean "is this relevant?") enables richer downstream behavior. The briefing generator can sort by confidence, the decay function can weight it, users can tune the threshold. A little extra data at creation time enables flexibility at consumption time.

---

## A/B Testing Results

I ran 18 Cortex-enabled sessions vs. 11 baseline sessions:

| Metric | Baseline | Cortex | Improvement |
|--------|----------|--------|-------------|
| Cold start time | 9.0 min | 1.4 min | **84% reduction** |
| Decision regression | 0.5/session | 0.1/session | **80% reduction** |
| Continuity score (1-5) | 2.9 | 4.7 | **+1.8 points** |
| Token overhead | N/A | 0.2% | Well under 15% limit |

### Qualitative Feedback

- Briefings were "very useful" — consistently contained relevant context
- Claude remembered decisions and plans **consistently** across sessions
- No major issues encountered
- **Faster onboarding than expected** — 84% cold start reduction translated to noticeably smoother session starts

**[ASTGL CONTENT]** Independent evaluation before implementation catches blind spots you can't see from inside the design. I had an external AI stress-test my plan, which caught a genuinely missing measurement strategy and forced vague aspirations into concrete mechanisms. 30 minutes of critique response saved hours of implementation confusion.

---

## The Meta-Irony

Throughout this project, I used an AI assistant with session boundary amnesia to design and build a solution for session boundary amnesia. The session notes I wrote exist precisely because of the problem I was trying to solve.

When the external evaluator reviewed my plan, it was an AI that would forget it did the evaluation. When I implemented the code, I had to re-explain context that the previous session knew perfectly.

**[ASTGL CONTENT]** The meta-irony continues — and it's the most visceral validation of the problem. If I didn't feel the pain daily, I might have under-invested in the solution.

---

## Tier 3: The Latest Features

The recently completed Tier 3 adds three major capabilities:

### MCP Server (Mid-Session Queries)

Claude can now query Cortex memory during a session, not just at session start:

```
"What decisions have I made about authentication?"
"What's my current plan?"
"Search my memory for database configuration issues"
```

Five tools expose memory: `cortex_search`, `cortex_search_decisions`, `cortex_get_plan`, `cortex_get_recent`, `cortex_get_status`.

### Git-Tracked Projections

Auto-generated markdown files in `.cortex/`:

```
.cortex/
├── decisions.md          # Active decisions with reasoning
├── decisions-archive.md  # Archived/aged decisions
└── active-plan.md        # Current work plan
```

These files are regenerated on session end and can be committed to git — your teammates can see what decisions Claude helped you make.

### Branch Alignment

Context isolation per git branch. When you switch branches, Cortex loads the relevant context for that branch. No more cross-contamination between feature branches.

---

## Getting Started

```bash
pip install -e .
cortex init          # Print hook config for Claude Code
cortex status        # Show project state
cortex upgrade       # Migrate to next tier
```

Add the hooks from `cortex init` to your Claude Code settings. Copy `templates/cortex-memory-instructions.md` to `.claude/rules/` so Claude knows to use `[MEMORY: ...]` tags.

That's it. Context capture starts automatically.

---

## Key Takeaways

1. **The context window boundary is the #1 barrier** to using AI assistants for complex, multi-session work.

2. **Event sourcing is the right foundation** — immutable events with projections give you auditability, flexibility, and clean separation of concerns.

3. **Three-layer extraction** (structural + semantic + self-reporting) achieves >95% recall for important events without requiring secondary LLM calls.

4. **Progressive tiers** let you start simple and upgrade incrementally. Tier 0 alone provides significant value.

5. **Decisions are immortal** — the "why" behind choices is never lost to temporal decay.

6. **Real-world testing validates the design** — 84% cold start reduction, 80% decision regression reduction, 0.2% token overhead.

---

## Future Work

- **Tier 4**: Team memory sharing, cross-project knowledge graphs
- **Multi-model support**: Extend beyond Claude to other LLM assistants
- **IDE integration**: Deeper VS Code / JetBrains integration
- **Memory visualization**: UI for exploring and editing the event store

---

## The Bottom Line

Every developer who has worked with AI coding assistants knows the frustration of session boundary amnesia. Cortex is my answer: an event-sourced memory architecture that captures context automatically, persists it reliably, and projects it intelligently — without requiring model modifications or your active maintenance.

The AI assistant finally remembers.

---

*This article was written with Claude Code, using Cortex to maintain context across the multiple sessions required to complete it. The irony remains unresolved.*

**713 tests passing. Ships today.**

---

## References

- [Cortex GitHub Repository](https://github.com/As-The-Geek-Learns/cortex)
- [Full Research Paper](docs/research/paper/cortex-research-paper.md)
- [A/B Comparison Results](docs/testing/AB-COMPARISON-RESULTS.md)
- [v0.3.0 Release Notes](https://github.com/As-The-Geek-Learns/cortex/releases/tag/v0.3.0)
