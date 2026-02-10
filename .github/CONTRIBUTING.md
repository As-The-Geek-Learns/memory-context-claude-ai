# Contributing Guidelines

Thank you for contributing! Please follow these guidelines to maintain code quality and security.

## Security First

- **Never commit secrets**: API keys, tokens, credentials, or passwords
- Gitleaks runs on every commit to catch secrets automatically
- If you accidentally commit a secret, alert immediately
- See [SECURITY.md](../../SECURITY.md) for reporting procedures

## CI/CD Requirements

All pull requests must pass:
- ✅ Semgrep (static security analysis)
- ✅ Gitleaks (secrets detection)
- ✅ Build verification
- ✅ T# Code ownership and review rench protection is enabled**: PRs require al
# Default owners for everything
* @jamescruce

# Security critical files require review
/.github/workflows/ @jamescruce
.gitleaks.toml @j
``* @jamescruce

# Security crit
p
# Security n -/.github/workflows/ @jamescruce
.gitleaPu.gitleaks.toml @jamescrcks for:
SECURITY.md @jamescruce
.at.pre-commit-config.yammgEOF

cat > /tmp/CONTRIBUTING.md <<l casts passing

## Submitting Changes

1. Create a feature branch
2. Make focused commits
3. Push to your branch
4. Open a PR with clear description
5. Address review feedback
6. Merge after CI passes and approval

## Getting Help

See [SECURITY.md](../../SECURITY.md) for security concerns or [BRANCH_PROTECTION.md](.github/BRANCH_PROTECTION.md) for merge requirements.
