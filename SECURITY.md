# Security Policy

## Supported Versions

We actively support the latest version of Cortex. Security updates are provided for the current release.

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security vulnerability, please follow these steps:

1. **Do not** open a public GitHub issue
2. Email security concerns to: [YOUR_EMAIL]
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will respond within 48 hours and work with you to address the issue.

## Security Best Practices

### For Users

- Keep Cortex updated to the latest version
- Use strong system-level encryption for your device
- Be cautious when sharing database/export files
- Review exported data before sharing

### For Developers

See [SECURITY-REVIEW.md](.github/SECURITY-REVIEW.md) for our security review checklist.

## Secure Coding Guidelines

### Input Validation

- Always validate and sanitize user inputs
- Use centralized validation functions
- Sanitize values before storing in database

### Error Handling

- Never expose sensitive information in error messages
- Use structured logging instead of `print` in production
- Hide stack traces in production builds

### Database Operations

- Always use parameterized queries
- Never concatenate user input into SQL strings
- Use centralized database access functions

### Dependencies

- Keep dependencies up to date
- Review security advisories regularly
- Use `pip-audit` before releases

## Security Features

- **Input Sanitization**: All text inputs should be sanitized to remove HTML and control characters
- **SQL Injection Protection**: All queries use parameterized statements
- **Error Sanitization**: Production error messages are generic and don't expose system details
- **Dependency Scanning**: Automated vulnerability scanning in CI/CD
- **Secrets Scanning**: Gitleaks prevents accidental credential commits

## Threat Model

### Desktop/Python Application Threats

- Local data tampering
- Memory inspection
- Malicious plugins/extensions

### Mitigations

- Input validation at all entry points
- Parameterized database queries
- Secure session management

## Security Updates

Security updates are released as needed. We recommend:

- Enabling automatic updates if available
- Checking for updates regularly
- Reviewing release notes for security fixes

## Disclosure Policy

- Vulnerabilities are disclosed after a fix is available
- We credit security researchers who responsibly disclose issues
- Critical vulnerabilities may be disclosed immediately if already exploited

## CI/CD Security Improvements (Feb 2026)

### Semgrep Action Pinning
- Semgrep v1 action pinned to commit SHA `713efdd345f3035192eaa63f56867b88e63e4e5d` for reproducibility
- Prevents supply chain attacks via floating version tags
- Ensures deterministic security scanning across all CI runs

### Gitleaks Enforcement (CLI-based scanning)
- Added `.gitleaks.toml` allowlist configuration to reduce false positives
- Review `.gitleaks.toml` and customize allowlist rules for your repository
- Note: This repo uses gitleaks CLI directly (not the GitHub Action)

## Contact

For security concerns: [YOUR_EMAIL]

For general questions: Open an issue on GitHub
