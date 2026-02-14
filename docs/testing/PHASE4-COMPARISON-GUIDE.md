# Phase 4 A/B Comparison Guide

**Purpose:** Step-by-step instructions for running Cortex-enabled sessions and measuring improvement against Phase 3 baselines.

**Goal:** Collect 5-10 sessions of real development work **with Cortex hooks enabled** and compare against the 11 baseline sessions collected in Phase 3.

---

## Prerequisites

- [x] Phase 3 baseline data collected (11 sessions in `docs/testing/baseline-data.json`)
- [x] Phase 3 report generated (`docs/testing/BASELINE-DATA-RESULTS.md`)
- [x] Phase 4 automation scripts installed (`scripts/testing/run_phase4.py`)
- [ ] Cortex hooks are **enabled** in Claude Code settings (see Step 1)

---

## Step 1: Enable Cortex Hooks

Cortex hooks must be active so that session context is captured and briefings are generated.

**Generate the hook configuration:**

```bash
cd /Users/jamescruce/Projects/cortex
cortex init
```

This prints a JSON block with three hooks:
- `session-start` — generates a briefing from stored events
- `precompact` — captures context before the conversation compresses
- `stop` — records session-end events

**Add the hooks to your project settings:**

Copy the JSON output into the project's `.claude/settings.local.json` (or `.claude/settings.json`) under the `"hooks"` key.

**Verify it's working:**

Start a Claude Code session and confirm:
1. You see "Running cortex session-start..." during startup
2. A `.claude/rules/cortex-briefing.md` file is generated
3. Running `cortex status` shows events being captured

---

## Step 2: Choose Your Work

Same guidelines as Phase 3 — use **real development tasks** that are comparable in complexity to your baseline sessions.

**Good comparison tasks (aim for variety):**

- Bug fixes and feature work
- Refactoring existing code
- Writing tests or documentation
- Working on any project (Cortex or otherwise)

**Guidelines:**
- Sessions should be **15-60 minutes** of active work
- Use a mix of tasks (match the variety from your baseline sessions)
- Work naturally — don't change your behavior because you're measuring
- Pay attention to how Cortex affects your workflow

---

## Step 3: Run the Session

1. **Start Claude Code normally** — Cortex hooks will activate automatically
2. **Note which project directory you're in** — you'll need the path in Step 4
3. **Do your work** — fix bugs, write code, whatever the task is
4. **Pay attention to these moments** (you'll be asked about them after):
   - How long before Claude does something useful (not just reading files)?
   - Did Claude re-debate any decisions you've already made in past sessions?
   - Did the briefing help Claude understand context from prior sessions?
   - Did Claude seem to "know" things from previous sessions?
5. **End the session normally** (exit Claude Code)

---

## Step 4: Record the Session

Immediately after ending the session (while it's fresh in your mind), run:

```bash
cd /Users/jamescruce/Projects/cortex

# If you worked in the cortex project:
python -m scripts.testing.run_phase4 record

# If you worked in a different project:
python -m scripts.testing.run_phase4 record --project /Users/jamescruce/Projects/jdex-premium
```

> **Important:** Use `--project` if you ran your session in a project other than cortex, just like Phase 3.

**What happens automatically (6 metrics extracted):**
- **Cold start time** — minutes until first file edit or command
- **Re-exploration count** — files read that were also read in prior Phase 4 sessions
- **Briefing token count** — size of the generated briefing (chars / 4)
- **Event count** — number of events in the Cortex event store
- Session stats (duration, tool calls, files explored/modified)

**What you'll be asked (your judgment needed):**

| Prompt | What it means | How to answer |
|--------|--------------|---------------|
| **Task description** | What did you work on? | Short summary, e.g. "Added retry logic to API client" |
| **Decision regression count** | How many times did Claude re-debate a decision from a prior session? | Count of distinct re-debates. Should be lower than baseline. |
| **Continuity score (1-5)** | How well did Claude preserve context from prior sessions? | 1 = blank slate, 3 = some awareness, 5 = seamless memory |
| **Notes** | Observations about briefing quality, context preservation | E.g. "Briefing helped Claude remember the SQLite decision" |

---

## Step 5: Check Your Progress

```bash
# See all recorded comparison sessions
python -m scripts.testing.run_phase4 list

# See running averages (includes briefing tokens and event count)
python -m scripts.testing.run_phase4 summary
```

**Target:** 5-10 sessions. The summary command will tell you how many more you need.

---

## Step 6: Generate the A/B Report (After 5+ Sessions)

```bash
python -m scripts.testing.run_phase4 report
```

This generates `docs/testing/AB-COMPARISON-RESULTS.md` with:
- All comparison session data in tables
- Side-by-side A/B comparison (baseline vs. Cortex-enabled averages)
- Improvement percentages per metric
- Success criteria evaluation (Pass/Fail)
- Auto-generated observations
- Qualitative sections (fill in manually after reviewing)

---

## Quick Reference

| Command | When to use |
|---------|-------------|
| `python -m scripts.testing.run_phase4 record` | After each Cortex-enabled session |
| `python -m scripts.testing.run_phase4 list` | Check what's been recorded |
| `python -m scripts.testing.run_phase4 summary` | See running statistics |
| `python -m scripts.testing.run_phase4 report` | Generate A/B comparison report (after 5+ sessions) |
| `python -m scripts.testing.run_phase4 reset` | Start over (deletes comparison data only; baseline is safe) |

---

## What to Watch For

During Cortex-enabled sessions, observe:

1. **Briefing quality** — Does the briefing contain relevant context? Is anything missing or stale?
2. **Cold start improvement** — Does Claude start productive work faster with the briefing?
3. **Decision preservation** — Does Claude remember prior decisions without re-debating them?
4. **Context carryover** — Does Claude reference things from previous sessions naturally?
5. **Token overhead** — Is the briefing size reasonable (target: <=15% of 200K context window)?

---

## FAQ

**Q: Does the work have to be on the same project as Phase 3?**
A: Not strictly, but it makes the A/B comparison fairer. Use `--project /path/to/project` if working elsewhere.

**Q: What if the briefing seems wrong or stale?**
A: Still record the session. Bad briefings are valid data points — they tell us about extraction accuracy.

**Q: Can I reset and start over?**
A: Yes, `python -m scripts.testing.run_phase4 reset` clears comparison data only. Your Phase 3 baseline data is never touched.

**Q: What if I need to record without Cortex for some reason?**
A: Use the Phase 3 tool instead: `python -m scripts.testing.run_phase3 record`. The two data stores are independent.

**Q: How do I know when I have enough sessions?**
A: Run `python -m scripts.testing.run_phase4 summary` — it tells you progress toward the 5-10 session target and suggests when to generate the report.
