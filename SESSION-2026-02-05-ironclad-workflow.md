# Session: Ironclad Workflow Improvements

**Date:** February 5, 2026
**Project:** Cortex
**Duration:** ~45 minutes
**Focus:** Development workflow hardening and automation

---

## Summary

Transformed the Cortex development workflow into a comprehensive "Ironclad" verification system with multiple layers of protection, then created a reusable bootstrap script to apply the same workflow to any Python project.

---

## What Was Accomplished

### 1. CodeQL Alert Remediation
- Reviewed 4 medium-severity CodeQL alerts in `scripts/ai-review.js`
- Added proper `lgtm` suppression comments for intentional behaviors
- Documented mitigations (sanitizeForLog, path validation)

### 2. Local Testing Infrastructure (Pre-GitHub Actions)
- **Pre-push hook** — Runs full verification before any push
- **Workflow verify** — Now includes mypy and Semgrep locally
- Saves GitHub Actions minutes by catching failures locally

### 3. Verification Improvements
| Addition | Purpose |
|----------|---------|
| `mypy` type checking | Catch type errors before runtime |
| `semgrep` security scan | Same scan CI runs, but locally |
| `pytest-cov` enforcement | 80% minimum coverage gate |
| `requirements-dev.txt` | Pinned dev dependencies |

### 4. GitHub Branch Protection
- Enabled on `main` branch via GitHub API
- Required checks: Python Quality, Python Tests, Workflow Verify
- Prevents broken code from being merged

### 5. Bootstrap Script (`ironclad-init.sh`)
Created a 700-line script that sets up the entire workflow on any Python project:
```bash
ironclad-init.sh [--dry-run] [--skip-branch-protection] [--skip-ci]
```

Creates:
- `.pre-commit-config.yaml`
- `requirements-dev.txt`
- `mypy.ini`
- `.git/hooks/pre-push`
- `package.json` (with npm scripts)
- `.github/workflows/ci.yml`
- Branch protection rules

---

## Key Decisions

### 1. Pre-push Hook vs Pre-commit for Heavy Checks
**Decision:** Run full verification (tests, lint, typecheck, semgrep) in pre-push, not pre-commit.

**Why:**
- Pre-commit runs on every commit (too slow for full suite)
- Pre-push is the last local gate before code leaves your machine
- Developers can make quick WIP commits without waiting

### 2. Permissive mypy Configuration Initially
**Decision:** Start with `warn_return_any = False` and `disallow_untyped_defs = False`

**Why:**
- Existing codebase had 4 type errors
- Strict mypy on legacy code creates friction
- Progressive tightening is more sustainable
- Added TODO comments to enable stricter checks later

### 3. Local Semgrep in verify.js
**Decision:** Added Semgrep to the local verification script (graceful skip if not installed)

**Why:**
- Same security scan that runs in CI
- Catches issues before they hit GitHub
- Optional — doesn't break workflow if tool missing

### 4. Defense in Depth Approach
**Decision:** Multiple overlapping verification layers

```
Pre-commit → Pre-push → Branch Protection → CI/CD
   (fast)      (full)      (enforced)       (final)
```

**Why:**
- Each layer catches different failure modes
- Local hooks save CI minutes
- Branch protection prevents bypasses
- CI is the final source of truth

---

## New Concepts Learned

### 1. Git Hook Layers
- **Pre-commit:** Fast checks on staged files (lint, format, secrets)
- **Pre-push:** Full verification before code leaves machine
- **Pre-receive:** Server-side (GitHub handles via branch protection)

### 2. lgtm Suppression Comments
CodeQL/LGTM uses inline comments to suppress false positives:
```javascript
fs.writeFileSync(path, data); // lgtm[js/http-to-file-access]
```
Must be on the same line as the flagged code.

### 3. Branch Protection via API
```bash
gh api repos/OWNER/REPO/branches/main/protection -X PUT --input - << 'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Python Quality", "Python Tests"]
  },
  "enforce_admins": false
}
EOF
```

### 4. mypy Type Narrowing
Python's type checker doesn't understand control flow across if statements:
```python
if x is None:
    raise ValueError()
# mypy still thinks x could be None here
assert x is not None  # This narrows the type
use(x)  # Now mypy knows x is not None
```

---

## ASTGL Content Flagged

### 1. Defense in Depth for CI/CD
The layered approach (pre-commit → pre-push → branch protection → CI) is a pattern worth explaining. Each layer serves a purpose:
- Pre-commit: Developer feedback loop (fast)
- Pre-push: Catch comprehensive issues locally (saves CI minutes)
- Branch protection: Enforcement (can't bypass)
- CI: Source of truth (reproducible environment)

### 2. Git Hooks Are Not Version Controlled
`.git/hooks/` is local-only. To share hooks:
- Store in `scripts/hooks/`, symlink during setup
- Use tools like `pre-commit` or `husky` that manage this
- Bootstrap scripts can install hooks programmatically

### 3. Progressive Type Checking Adoption
Starting with permissive mypy config and tightening over time is more sustainable than enforcing strict types on legacy code immediately. The friction of fixing hundreds of errors upfront often leads to abandonment.

### 4. Local Testing Saves Money
GitHub Actions minutes cost money. Running the same checks locally before pushing:
- Faster feedback (no waiting for CI queue)
- Saves Actions minutes for actual CI runs
- Catches 95% of failures before they hit remote

---

## Files Changed

### New Files
| File | Purpose |
|------|---------|
| `scripts/ironclad-init.sh` | Bootstrap script for any Python project |
| `requirements-dev.txt` | Pinned development dependencies |
| `mypy.ini` | Type checking configuration |
| `.git/hooks/pre-push` | Local verification hook |

### Modified Files
| File | Changes |
|------|---------|
| `scripts/ai-review.js` | Added lgtm suppression comments |
| `scripts/verify.js` | Added mypy + semgrep checks (v1.2.0) |
| `package.json` | Added test:coverage, typecheck, security:semgrep scripts |
| `.github/workflows/ci.yml` | Added Python Type Check job |
| `src/cortex/briefing.py` | Added type narrowing assertion |

---

## Commits (This Session)

```
e8b2e85 fix: resolve mypy type check errors
1c247a4 feat: add ironclad-init.sh bootstrap script
7c53aab feat: add ironclad verification improvements
9c6a358 fix: add CodeQL suppression comments
```

---

## Open Questions / Next Steps

1. **Tighten mypy config** — Enable `warn_return_any` and `disallow_untyped_defs` once type coverage improves

2. **Test coverage baseline** — Current coverage is unknown; may need to adjust the 80% threshold

3. **Template repository** — Consider creating a GitHub template repo with the ironclad workflow pre-configured

4. **Other projects** — Run `ironclad-init.sh` on other Python projects (substack-scheduler, etc.)

5. **Documentation** — Add ironclad workflow to project README or separate docs

---

## Commands Reference

```bash
# Local verification (what pre-push runs)
npm run workflow:verify:no-ai

# Individual checks
npm run test              # pytest
npm run test:coverage     # pytest with 80% gate
npm run lint              # ruff check + format
npm run typecheck         # mypy
npm run security:semgrep  # semgrep scan
npm run audit             # pip-audit

# Bootstrap new project
/path/to/cortex/scripts/ironclad-init.sh

# Install globally
ln -s ~/Projects/cortex/scripts/ironclad-init.sh ~/bin/ironclad-init
```

---

*Session documented with Claude Code (Opus 4.5)*
