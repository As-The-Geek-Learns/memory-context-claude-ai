# Branch Protection Configuration

Recommended GitHub branch protection settings for the `main` branch:

## Required Settings

### 1. Require Status Checks to Pass
- ✅ Require branches to be up to date before merging
- Required status checks (from CI):
  - Semgrep (security-scan job)
  - Gitleaks (secrets-scan job)
  - Build/test jobs

### 2. Require Code Reviews
- ✅ Require at least 1 approving review
- ✅ Dismiss stale reviews on new commits
- ✅ Require review from code owners (CODEOWNERS)

### 3. Require Conversation Resolution
- ✅ Require all comments addressed

### 4. Include Administrators
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------nality |

## Related Documents

- [CODEOWNERS](.github/CODEOWNERS) - Code owners
- [CONTRIBUTING.md](.github/CONTRIBUTING.md) - Contributor guide
- [SECURITY.md](../../SECURITY.md) - Security policy
