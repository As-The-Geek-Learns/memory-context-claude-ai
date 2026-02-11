# Phase 3 Baseline Session Guide

**Purpose:** Step-by-step instructions for running baseline dev sessions and recording metrics.

**Goal:** Collect 7-8 sessions of real development work **without Cortex hooks** to establish baseline measurements of Claude Code's memory limitations. (5 minimum, stop early if variance is low; push to 10 if results are inconsistent.)

---

## Prerequisites

- [x] Phase 2 manual testing passed (all scenarios verified)
- [x] Phase 3 automation scripts installed (`scripts/testing/run_phase3.py`)
- [ ] Cortex hooks are **not** configured in Claude Code settings (see Step 1)

---

## Step 1: Verify Cortex Hooks Are Disabled

Cortex hooks would normally be added to your Claude Code project settings. For baseline sessions, they must **not** be present.

**Check your settings files:**

```bash
# Global settings — should NOT have cortex hooks
cat ~/.claude/settings.json

# Project settings — should NOT have cortex hooks
cat /Users/jamescruce/Projects/cortex/.claude/settings.json 2>/dev/null || echo "(no project settings.json — good)"
cat /Users/jamescruce/Projects/cortex/.claude/settings.local.json
```

**What to look for:** If any settings file contains a `"hooks"` section with `cortex stop`, `cortex precompact`, or `cortex session-start`, remove or comment out that entire `"hooks"` block for the duration of Phase 3.

> **Note:** Your global `~/.claude/settings.json` has an ASTGL content check hook — that's fine, it's unrelated to Cortex. Only Cortex-specific hooks (`cortex stop`, `cortex precompact`, `cortex session-start`) need to be disabled.

**How you'll know it's working:** When you start a Claude Code session, you should **not** see any "Running cortex..." messages or a `cortex-briefing.md` file being generated.

---

## Step 2: Choose Your Work

Each baseline session should involve **real development work** — the same kind of tasks you'd normally do with Claude Code. The data is only useful if the sessions are genuine.

**Good baseline tasks (aim for variety):**

- Bug fixes in the Cortex codebase
- Adding a new feature or test
- Refactoring existing code
- Writing documentation
- Working on ASTGL articles
- Any real project work (doesn't have to be Cortex)

**Guidelines:**
- Sessions should be **15-60 minutes** of active work
- Use a mix of tasks (don't do the same thing 10 times)
- Work naturally — don't change your behavior because you're measuring
- You can use any project, but using Cortex itself is ideal since that's what Phase 4 will compare against

---

## Step 3: Run the Session

1. **Start Claude Code normally** in whatever project you're working on — it does **not** have to be the cortex project (see FAQ)
2. **Note which project directory you're in** — you'll need the path in Step 4
3. **Do your work** — fix bugs, write code, whatever the task is
4. **Pay attention to these moments** (you'll be asked about them after):
   - How long before Claude does something useful (not just reading files)?
   - Did Claude re-debate any decisions you've already made in past sessions?
   - Did Claude seem to "know" anything from your previous sessions, or was it starting completely fresh?
5. **End the session normally** (exit Claude Code)

---

## Step 4: Record the Session

Immediately after ending the session (while it's fresh in your mind), run:

```bash
cd /Users/jamescruce/Projects/cortex

# If you worked in the cortex project:
python -m scripts.testing.run_phase3 record

# If you worked in a different project:
python -m scripts.testing.run_phase3 record --project /Users/jamescruce/Projects/substack-scheduler
```

> **Important:** The `record` command auto-discovers transcripts by project directory. Without `--project`, it looks for transcripts from the cortex project. If you ran your session in a different project (e.g. UpdateKit), you **must** use `--project` or you'll get a "No Claude Code transcript directory found" error.

**What happens automatically:**
- Finds the most recent Claude Code transcript for the specified project
- Extracts **cold start time** (minutes until first file edit or command)
- Extracts **re-exploration count** (files read that were also read in prior sessions)
- Shows you session stats (duration, tool calls, files explored/modified)

**What you'll be asked (your judgment needed):**

| Prompt | What it means | How to answer |
|--------|--------------|---------------|
| **Task description** | What did you work on? | Short summary, e.g. "Fixed logging bug in store.py" |
| **Decision regression count** | How many times did Claude re-debate a decision you'd already made in a prior session? | Count of distinct re-debates. 0 is common for early sessions. |
| **Continuity score (1-5)** | How well did Claude preserve context from prior sessions? | 1 = total blank slate, 3 = some awareness, 5 = seamless memory |
| **Notes** | Anything notable about context loss? | Optional. E.g. "Claude forgot we chose SQLite over JSON" |

**Decision regression examples:**
- Claude suggests an approach you explicitly rejected last session → count it
- Claude asks "should we use X or Y?" when you already decided Y → count it
- Claude re-reads files it explored extensively yesterday → that's re-exploration (auto-counted), not regression

**Continuity score guide:**
- **1** — Complete blank slate. Claude has zero awareness of prior work.
- **2** — Minimal awareness. Maybe picks up on file structure but not decisions.
- **3** — Moderate. Understands the codebase structure but not project history.
- **4** — Good. Seems aware of patterns and conventions but misses some decisions.
- **5** — Seamless. Feels like Claude remembers everything (unlikely without Cortex).

> **Tip:** For early sessions (1-2), decision regression will likely be 0 and continuity score will be 1-2. That's expected — there's not much prior context to lose yet. The interesting data comes from sessions 3+.

---

## Step 5: Check Your Progress

```bash
# See all recorded sessions
python -m scripts.testing.run_phase3 list

# See running averages
python -m scripts.testing.run_phase3 summary
```

**Target:** 7-8 sessions. Check variance after session 5 — if metrics are consistent (low spread between min/max), you can stop at 7. If results are scattered, push to 10.

---

## Step 6: Generate the Report (After 7+ Sessions)

```bash
python -m scripts.testing.run_phase3 report
```

This generates `docs/testing/BASELINE-DATA-RESULTS.md` with:
- All session data in tables
- Summary statistics (avg/min/max for each metric)
- Auto-generated observations (most re-explored files, context loss patterns)

---

## Step 7: Move to Phase 4

After collecting baseline data:

1. **Enable Cortex hooks** — add the hook JSON to your Claude Code project settings:
   ```bash
   # Generate the hook JSON
   cd /Users/jamescruce/Projects/cortex
   cortex init
   ```
   Copy the output into `.claude/settings.json` (create it if needed).

2. **Run Phase 4 (A/B Comparison)** — same kinds of tasks, but now with Cortex enabled.

---

## Quick Reference

| Command | When to use |
|---------|-------------|
| `python -m scripts.testing.run_phase3 record` | After each baseline session |
| `python -m scripts.testing.run_phase3 list` | Check what's been recorded |
| `python -m scripts.testing.run_phase3 summary` | See running statistics |
| `python -m scripts.testing.run_phase3 report` | Generate final report (after 7+ sessions) |
| `python -m scripts.testing.run_phase3 reset` | Start over (deletes all data) |

---

## FAQ

**Q: Does the work have to be on the Cortex project?**
A: No, but it's ideal. Phase 4 will compare Cortex-enabled sessions against these baselines, so using the same project makes the comparison fairer. You can use `--project /path/to/other/project` if working elsewhere.

**Q: What if I forget to record right away?**
A: The transcript is still on disk. Run `record` and it'll find the most recent one. If you've started a new session since then, use `--transcript /path/to/transcript.jsonl` to point at the specific file.

**Q: What if a session is really short (< 10 minutes)?**
A: Still record it. Short sessions are valid data points — they show how much time is spent on cold start vs. productive work.

**Q: Can I record sessions from different projects?**
A: Yes. Use `--project /path/to/project` to auto-discover that project's transcript, or `--transcript` to specify it directly.

**Q: What if I mess up a recording?**
A: Run `reset` to clear all data and start over (you'll be asked to confirm).
