# Session Notes: Tier 0 Real-World Testing Setup

**Date:** 2026-01-31
**Project Phase:** Testing — Tier 0 Real-World Validation

---

## What Was Accomplished

Implemented the Tier 0 Real-World Testing Plan (Phase 1: Setup & Verification) and created templates for Phases 2–5. Cortex is installed, CLI commands verified, test project created, and all testing documentation is in place.

### Phase 1: Setup & Verification (Completed)

- Installed Cortex package (`pip install -e .`)
- Verified `cortex --help` shows `stop`, `precompact`, `session-start`, `reset`, `status`, `init`
- Generated hook configuration JSON via `cortex init`
- Copied memory instructions to `.claude/rules/cortex-memory-instructions.md`
- Verified `cortex status` and `cortex reset` in the main project
- Created test project at `~/cortex-test-project` with git on `main` branch
- Copied memory instructions into test project `.claude/rules/`

### Files Created

| File | Purpose |
|------|---------|
| `docs/testing/SETUP-VERIFICATION-CHECKLIST.md` | Phase 1 results and hook JSON for Claude Code |
| `docs/testing/MANUAL-TESTING-TEMPLATE.md` | Phase 2 manual testing checklist |
| `docs/testing/BASELINE-DATA-TEMPLATE.md` | Phase 3 baseline data collection (5–10 sessions) |
| `docs/testing/AB-COMPARISON-TEMPLATE.md` | Phase 4 A/B comparison (10 sessions) |
| `docs/testing/README.md` | Testing overview and quick start |

---

## Test Project

- **Path:** `~/cortex-test-project`
- **Hash:** `adf739349471d136`
- **Purpose:** Isolated project for manual testing without polluting Cortex’s own memory

---

## Next Steps (User Action Required)

1. **Configure Claude Code hooks** — Add hook JSON from `docs/testing/SETUP-VERIFICATION-CHECKLIST.md` to `~/.claude/settings.json`
2. **Phase 2: Manual Testing** — Run single-session and multi-session tests using `docs/testing/MANUAL-TESTING-TEMPLATE.md`
3. **Phase 3: Baseline Collection** — Disable Cortex, run 5–10 sessions, record metrics via `docs/testing/BASELINE-DATA-TEMPLATE.md`
4. **Phase 4: A/B Comparison** — Re-enable Cortex, run 10 sessions, compare via `docs/testing/AB-COMPARISON-TEMPLATE.md`
5. **Phase 5: Calibration** — After 20+ sessions, analyze event utility and adjust decay parameters

---

## Success Criteria (from Research Paper §11.4)

| Criterion | Target |
|-----------|--------|
| Cold start time reduction | 80%+ |
| Decision regression | Near-zero |
| Plan continuity | Seamless |
| Token overhead | ≤15% |
| Extraction accuracy | >90% recall |
| User maintenance effort | Near-zero |

---

## Reference

- [Tier 0 Real-World Testing Plan](docs/testing/README.md) (see docs/testing/ for templates)
- [Research paper §11.4 (Evaluation & Measurement)](docs/research/paper/cortex-research-paper.md)
- [Testing README](docs/testing/README.md)
