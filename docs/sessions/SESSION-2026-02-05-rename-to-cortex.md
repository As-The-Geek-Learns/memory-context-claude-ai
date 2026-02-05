# Session Notes: Rename Project to Cortex

**Date:** 2026-02-05
**Duration:** ~30 minutes
**Branch:** main
**Commit:** 8912624

---

## Objective

Rename the project from `memory-context-claude-ai` to `cortex` — a cleaner, more memorable name that better represents the project's purpose as an "AI brain" for context persistence.

---

## What Was Accomplished

### 1. GitHub Repository Rename
- Renamed repo from `As-The-Geek-Learns/memory-context-claude-ai` to `As-The-Geek-Learns/cortex`
- Updated local remote URL to match

### 2. Python Package Rename
- Renamed `src/memory_context_claude_ai/` to `src/cortex/` using `git mv` (preserves git history)
- 11 source files renamed with history intact

### 3. Import Updates (17 files total)
**Source files (7):**
- `src/cortex/__init__.py` — Updated all re-exports
- `src/cortex/__main__.py` — Updated imports and docstring
- `src/cortex/cli.py`
- `src/cortex/briefing.py`
- `src/cortex/hooks.py`
- `src/cortex/extractors.py`
- `src/cortex/store.py`

**Test files (10):**
- `tests/conftest.py`
- `tests/test_integration.py` — Also updated monkeypatch paths
- `tests/test_cli.py` — Also updated monkeypatch paths
- `tests/test_hooks.py` — Also updated 7 monkeypatch paths
- `tests/test_briefing.py`
- `tests/test_config.py`
- `tests/test_extractors.py`
- `tests/test_transcript.py`
- `tests/test_store.py`
- `tests/test_project.py`
- `tests/test_models.py`

### 4. Configuration File Updates
| File | Changes |
|------|---------|
| `pyproject.toml` | Package name, module path |
| `package.json` | Package name |
| `requirements.txt` | Editable install path |
| `CLAUDE.md` | Project references |
| `SECURITY.md` | Repo URL |
| `.github/workflows/ci.yml` | Package references |
| `.github/dependabot.yml` | Directory path |
| `.pre-commit-config.yaml` | Module path |

### 5. Documentation Updates
- `README.md` — Updated `python -m cortex` commands and pip install reference
- `docs/testing/CORTEX-PROJECT-NOTION-IMPORT.md` — Updated repo URL and source paths

### 6. Verification
- All **331 tests passing** after rename
- Commit pushed to `origin/main`

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Use `git mv` for directory rename | Preserves git history for all files |
| Keep historical session docs unchanged | They document what was true at the time; changing them would be revisionist |
| Use `replace_all: true` for monkeypatch paths | Efficient bulk replacement of repeated patterns |
| Name the package simply `cortex` | Clean, memorable, matches the CLI command |

---

## Technical Patterns Used

### 1. Git MV for Package Rename
```bash
git mv src/memory_context_claude_ai src/cortex
```
This stages all files as renames rather than delete+add, preserving blame history.

### 2. Monkeypatch Path Updates
Pytest monkeypatching requires full module paths:
```python
# Before
monkeypatch.setattr("memory_context_claude_ai.hooks.load_config", lambda: config)

# After
monkeypatch.setattr("cortex.hooks.load_config", lambda: config)
```

### 3. Edit Tool with replace_all
For files with multiple identical patterns:
```python
Edit(file_path, old_string, new_string, replace_all=True)
```

---

## Files Changed Summary

```
39 files changed, 1133 insertions(+), 97 deletions(-)

Source (11 files renamed):
  src/memory_context_claude_ai/* → src/cortex/*

Tests (10 files modified):
  tests/test_*.py — import updates

Config (8 files modified):
  pyproject.toml, package.json, requirements.txt, CLAUDE.md,
  SECURITY.md, ci.yml, dependabot.yml, .pre-commit-config.yaml

Docs (2 files modified):
  README.md, docs/testing/CORTEX-PROJECT-NOTION-IMPORT.md
```

---

## Open Questions / Future Work

1. **PyPI package name** — When publishing, ensure `cortex` is available or use `cortex-ai` / `cortex-memory`
2. **Historical docs** — Consider adding a note that the project was renamed from `memory-context-claude-ai`
3. **Cursor rules** — The `.cursor/rules/memory-context-claude-ai-base.mdc` file was deleted; may need new Cortex-specific rules

---

## ASTGL Content Moments

**[ASTGL CONTENT]** Renaming a Python package involves more than just directory rename:
- All internal imports must be updated
- Test monkeypatch paths use string module paths that need updating
- Config files reference the package in various ways (build systems, CI, docs)
- Using `git mv` preserves history, which is valuable for blame/log

**[ASTGL CONTENT]** The pattern of "historical documentation stays historical" — session notes from January 2026 still reference `memory_context_claude_ai` because that's what existed then. Changing them would be revisionist and confusing.

---

## Verification Commands

```bash
# Verify package works
python -m cortex --help
cortex status

# Verify tests pass
pytest tests/ -v

# Verify no old references in source code
grep -r "memory_context_claude_ai" src/ tests/
# Should return empty
```

---

*Session conducted as part of the Cortex project development.*
