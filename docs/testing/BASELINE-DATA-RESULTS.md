# Tier 0 Baseline Data Collection Results

**Purpose:** Record 5-10 sessions **without Cortex** to establish baselines for cold start time, decision regression, and re-exploration.

**Period:** 2026-02-05 to 2026-02-10
**Sessions recorded:** 11
**Method:** Automated extraction (scripts/testing/run_phase3.py) + manual input

---


## Data Collection Method

- **Cold start time** and **re-exploration count**: Auto-extracted from Claude Code JSONL transcripts
- **Decision regression count** and **continuity score**: Recorded manually by the developer after each session

---


## Session Data

### Session 1 (without Cortex)

| Field | Value |
|-------|-------|
| **Date** | 2026-02-05 |
| **Task** | Working on functionality of the UpdateKit project |
| **Cold start time** | 0.1 minutes |
| **Decision regression count** | 0 |
| **Re-exploration count** | 0 |
| **Continuity score** | 5 |
| **Notes** | The entire session just seemed slower than normal. I usually have Claude bring up the last sesstesting memory so it didn't seem like I should. |
| **Session details** | 62.5 min, 83 tool calls, 14 files explored, 9 files modified |

---

### Session 2 (without Cortex)

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | refactoring app |
| **Cold start time** | 0.2 minutes |
| **Decision regression count** | 1 |
| **Re-exploration count** | 0 |
| **Continuity score** | 3 |
| **Notes** | (none) |
| **Session details** | 24.5 min, 81 tool calls, 8 files explored, 7 files modified |

---

### Session 3 (without Cortex)

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | More Refactoring |
| **Cold start time** | 1.3 minutes |
| **Decision regression count** | 0 |
| **Re-exploration count** | 3 |
| **Continuity score** | 3 |
| **Notes** | (none) |
| **Session details** | 55.4 min, 127 tool calls, 7 files explored, 3 files modified |

---

### Session 4 (without Cortex)

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | refactoring |
| **Cold start time** | 0.4 minutes |
| **Decision regression count** | 0 |
| **Re-exploration count** | 2 |
| **Continuity score** | 4 |
| **Notes** | (none) |
| **Session details** | 54.0 min, 57 tool calls, 8 files explored, 5 files modified |

---

### Session 5 (without Cortex)

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | More refactoring |
| **Cold start time** | 3.5 minutes |
| **Decision regression count** | 0 |
| **Re-exploration count** | 5 |
| **Continuity score** | 3 |
| **Notes** | had lots of communication issues with Github |
| **Session details** | 45.4 min, 63 tool calls, 6 files explored, 3 files modified |

---

### Session 6 (without Cortex) — Optional

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | git and github cleanup |
| **Cold start time** | 0.4 minutes |
| **Decision regression count** | 0 |
| **Re-exploration count** | 0 |
| **Continuity score** | 2 |
| **Notes** | (none) |
| **Session details** | 14.0 min, 42 tool calls, 2 files explored, 2 files modified |

---

### Session 7 (without Cortex) — Optional

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | More refactors |
| **Cold start time** | 2.1 minutes |
| **Decision regression count** | 1 |
| **Re-exploration count** | 5 |
| **Continuity score** | 2 |
| **Notes** | (none) |
| **Session details** | 184.3 min, 107 tool calls, 15 files explored, 8 files modified |

---

### Session 8 (without Cortex) — Optional

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | refactor work |
| **Cold start time** | 2.1 minutes |
| **Decision regression count** | 0 |
| **Re-exploration count** | 15 |
| **Continuity score** | 2 |
| **Notes** | (none) |
| **Session details** | 221.4 min, 109 tool calls, 15 files explored, 8 files modified |

---

### Session 9 (without Cortex) — Optional

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | refactoring |
| **Cold start time** | 0.3 minutes |
| **Decision regression count** | 1 |
| **Re-exploration count** | 8 |
| **Continuity score** | 3 |
| **Notes** | (none) |
| **Session details** | 87.7 min, 170 tool calls, 12 files explored, 7 files modified |

---

### Session 10 (without Cortex) — Optional

| Field | Value |
|-------|-------|
| **Date** | 2026-02-09 |
| **Task** | refatoring we go |
| **Cold start time** | 0.1 minutes |
| **Decision regression count** | 2 |
| **Re-exploration count** | 7 |
| **Continuity score** | 3 |
| **Notes** | (none) |
| **Session details** | 85.5 min, 283 tool calls, 26 files explored, 22 files modified |

---


## Summary Statistics

| Metric | Sessions Recorded | Average | Min | Max |
|--------|------------------|---------|-----|-----|
| Cold start time (min) | 11 | 9.0 | 0.1 | 89.0 |
| Decision regression count | 11 | 0.5 | 0.0 | 2.0 |
| Re-exploration count | 11 | 5.2 | 0.0 | 15.0 |
| Continuity score (1-5) | 11 | 2.9 | 2.0 | 5.0 |

---


## Observations

### Files Most Frequently Explored

Files explored in multiple sessions (candidates for Cortex memory):

- `/Users/jamescruce/Projects/substack-scheduler/substack_poster.py` — 7 sessions
- `/Users/jamescruce/Projects/substack-scheduler/api/dependencies.py` — 6 sessions
- `/Users/jamescruce/Projects/substack-scheduler/api/routes/accounts.py` — 5 sessions
- `/Users/jamescruce/Projects/substack-scheduler/.workflow/sessions/SESSION-2026-02-09-codeant-followup/SESSION-NOTES.md` — 5 sessions
- `/Users/jamescruce/Projects/substack-scheduler/api/routes/notes.py` — 5 sessions
- `/Users/jamescruce/Projects/substack-scheduler/.workflow/sessions/SESSION-2026-02-09-daemon-architecture/SESSION-NOTES.md` — 4 sessions
- `/Users/jamescruce/Projects/substack-scheduler/api/routes/daemon.py` — 4 sessions
- `/Users/jamescruce/Projects/substack-scheduler/tests/conftest.py` — 4 sessions
- `/Users/jamescruce/Projects/substack-scheduler` — 3 sessions
- `/Users/jamescruce/Projects/substack-scheduler/docs/ROADMAP.md` — 3 sessions
- `/Users/jamescruce/Projects/substack-scheduler/.workflow/sessions/SESSION-2026-02-09-housekeeping.md` — 3 sessions
- `/Users/jamescruce/Projects/substack-scheduler/.workflow/sessions/SESSION-2026-02-09-testing-gap-sprint/SESSION-NOTES.md` — 3 sessions
- `/Users/jamescruce/Projects/substack-scheduler/api/license.py` — 3 sessions
- `/Users/jamescruce/Projects/substack-scheduler/tests/integration/test_api_endpoints.py` — 3 sessions
- `/Users/jamescruce/Projects/substack-scheduler/tests/test_scheduler.py` — 3 sessions

### Common Context Loss Patterns

1 of 11 sessions had 2+ decision regressions:

- Session 10: 2 regressions —

### Cold Start Analysis

Average cold start: 9.0 minutes. 1 sessions had notably slow starts (>1.5x average):

- Session 11: 89.0 min — add feature timezone aware

---


## Next Steps

After completing 5-10 baseline sessions:
1. Re-enable Cortex hooks in Claude Code settings
2. Proceed to Phase 4 (A/B Comparison)
3. Use the same project and comparable tasks for fair comparison
