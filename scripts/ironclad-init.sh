#!/bin/bash
# =============================================================================
# Ironclad Project Initializer
# =============================================================================
# Sets up a Python project with the Ironclad Development Workflow:
#   - Pre-commit hooks (ruff, gitleaks, pytest)
#   - Pre-push verification hook
#   - mypy type checking
#   - Semgrep security scanning
#   - GitHub branch protection
#   - CI/CD workflow
#
# Usage:
#   ironclad-init.sh [options]
#
# Options:
#   --skip-branch-protection   Skip GitHub branch protection setup
#   --skip-ci                  Skip CI workflow creation
#   --skip-scripts             Skip copying verify/ship scripts
#   --dry-run                  Show what would be done without doing it
#   -h, --help                 Show this help message
#
# Requirements:
#   - Git repository initialized
#   - GitHub CLI (gh) installed and authenticated (for branch protection)
#   - Node.js (for workflow scripts)
#   - Python 3.11+
#
# Author: As The Geek Learns
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory (where ironclad templates live)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IRONCLAD_SOURCE="$(dirname "$SCRIPT_DIR")"

# Options
SKIP_BRANCH_PROTECTION=false
SKIP_CI=false
SKIP_SCRIPTS=false
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-branch-protection) SKIP_BRANCH_PROTECTION=true; shift ;;
        --skip-ci) SKIP_CI=true; shift ;;
        --skip-scripts) SKIP_SCRIPTS=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        -h|--help)
            head -35 "$0" | tail -30
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Utility functions
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

run() {
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} $1"
    else
        eval "$1"
    fi
}

# Check prerequisites
check_prereqs() {
    info "Checking prerequisites..."

    if [ ! -d ".git" ]; then
        error "Not a git repository. Run 'git init' first."
        exit 1
    fi

    if ! command -v python3 &> /dev/null; then
        error "Python 3 not found"
        exit 1
    fi

    if ! command -v node &> /dev/null; then
        warn "Node.js not found - workflow scripts won't work without it"
    fi

    if ! command -v gh &> /dev/null; then
        warn "GitHub CLI not found - branch protection won't be configured"
        SKIP_BRANCH_PROTECTION=true
    fi

    success "Prerequisites checked"
}

# Detect project info
detect_project() {
    info "Detecting project info..."

    PROJECT_NAME=$(basename "$PWD")

    # Try to get GitHub remote
    if git remote get-url origin &> /dev/null; then
        REMOTE_URL=$(git remote get-url origin)
        # Extract owner/repo from URL
        if [[ "$REMOTE_URL" =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
            GITHUB_OWNER="${BASH_REMATCH[1]}"
            GITHUB_REPO="${BASH_REMATCH[2]}"
            success "Detected GitHub repo: $GITHUB_OWNER/$GITHUB_REPO"
        fi
    else
        warn "No git remote found - branch protection will be skipped"
        SKIP_BRANCH_PROTECTION=true
    fi

    # Detect Python source directory
    if [ -d "src" ]; then
        PYTHON_SRC="src"
        # Try to find the package name
        PACKAGE_DIR=$(find src -maxdepth 1 -type d ! -name src ! -name __pycache__ 2>/dev/null | head -1)
        if [ -n "$PACKAGE_DIR" ]; then
            PACKAGE_NAME=$(basename "$PACKAGE_DIR")
        else
            PACKAGE_NAME=""
        fi
    else
        PYTHON_SRC="."
        PACKAGE_NAME=""
    fi

    info "Project: $PROJECT_NAME"
    info "Python source: $PYTHON_SRC"
    [ -n "$PACKAGE_NAME" ] && info "Package: $PACKAGE_NAME"
}

# Create pre-commit config
create_precommit_config() {
    info "Creating .pre-commit-config.yaml..."

    if [ -f ".pre-commit-config.yaml" ]; then
        warn ".pre-commit-config.yaml already exists - skipping"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would create .pre-commit-config.yaml"
        return
    fi

    cat > .pre-commit-config.yaml << 'EOF'
# Pre-commit hooks - Ironclad Development Workflow
# Install: pip install pre-commit && pre-commit install
# Run manually: pre-commit run --all-files

repos:
  # Ruff - Fast Python linter and formatter
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.6
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  # Security: Detect secrets before they're committed
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks

  # Run tests before commit
  - repo: local
    hooks:
      - id: pytest
        name: pytest
        entry: pytest tests/ -v --tb=short
        language: system
        pass_filenames: false
        stages: [pre-commit]

  # General file hygiene
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
      - id: detect-private-key
EOF

    success "Created .pre-commit-config.yaml"
}

# Create requirements-dev.txt
create_requirements_dev() {
    info "Creating requirements-dev.txt..."

    if [ -f "requirements-dev.txt" ]; then
        warn "requirements-dev.txt already exists - skipping"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would create requirements-dev.txt"
        return
    fi

    cat > requirements-dev.txt << 'EOF'
# =============================================================================
# Development Dependencies - Ironclad Development Workflow
# =============================================================================
# Install: pip install -r requirements-dev.txt
# =============================================================================

# Include runtime dependencies
-r requirements.txt

# -----------------------------------------------------------------------------
# Testing
# -----------------------------------------------------------------------------
pytest>=8.0.0
pytest-cov>=5.0.0
pytest-mock>=3.12.0

# -----------------------------------------------------------------------------
# Code Quality
# -----------------------------------------------------------------------------
ruff>=0.4.0
mypy>=1.10.0

# -----------------------------------------------------------------------------
# Security Scanning
# -----------------------------------------------------------------------------
pip-audit>=2.7.0
semgrep>=1.50.0

# -----------------------------------------------------------------------------
# Git Hooks
# -----------------------------------------------------------------------------
pre-commit>=3.7.0
EOF

    success "Created requirements-dev.txt"
}

# Create mypy.ini
create_mypy_config() {
    info "Creating mypy.ini..."

    if [ -f "mypy.ini" ]; then
        warn "mypy.ini already exists - skipping"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would create mypy.ini"
        return
    fi

    cat > mypy.ini << 'EOF'
[mypy]
# =============================================================================
# mypy Configuration - Ironclad Development Workflow
# =============================================================================
python_version = 3.11
warn_return_any = True
warn_unused_configs = True
ignore_missing_imports = True

# Progressive strictness (enable as codebase matures)
disallow_untyped_defs = False
disallow_incomplete_defs = False
check_untyped_defs = True

# Useful warnings
warn_redundant_casts = True
warn_unused_ignores = True
warn_unreachable = True

# Output formatting
show_error_codes = True
show_column_numbers = True
pretty = True
EOF

    success "Created mypy.ini"
}

# Create pre-push hook
create_prepush_hook() {
    info "Creating pre-push hook..."

    if [ -f ".git/hooks/pre-push" ]; then
        warn ".git/hooks/pre-push already exists - skipping"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would create .git/hooks/pre-push"
        return
    fi

    mkdir -p .git/hooks

    cat > .git/hooks/pre-push << 'HOOK'
#!/bin/bash
# =============================================================================
# Pre-push Hook - Ironclad Development Workflow
# =============================================================================
# Runs verification before pushing to prevent CI failures.
# Bypass (emergency only): git push --no-verify
# =============================================================================

set -e

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔍 Pre-push: Running verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Try npm script first, fall back to direct commands
if [ -f "package.json" ] && grep -q "workflow:verify" package.json; then
    npm run workflow:verify:no-ai
elif [ -f "Makefile" ] && grep -q "verify:" Makefile; then
    make verify
else
    # Direct commands fallback
    echo "Running tests..."
    pytest tests/ -v --tb=short || exit 1

    echo "Running linter..."
    ruff check . || exit 1
    ruff format --check . || exit 1

    echo "Running type check..."
    if command -v mypy &> /dev/null; then
        mypy src/ --ignore-missing-imports || true
    fi

    echo "Running security audit..."
    pip-audit --strict || true
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Verification passed — pushing to remote"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
HOOK

    chmod +x .git/hooks/pre-push
    success "Created pre-push hook"
}

# Create or update package.json with npm scripts
create_package_json() {
    info "Setting up package.json scripts..."

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would create/update package.json"
        return
    fi

    # Determine the mypy target path
    MYPY_TARGET="src/"
    if [ -n "$PACKAGE_NAME" ]; then
        MYPY_TARGET="src/$PACKAGE_NAME"
    fi

    if [ ! -f "package.json" ]; then
        cat > package.json << EOF
{
  "name": "$PROJECT_NAME",
  "version": "0.1.0",
  "description": "Python project with Ironclad Development Workflow",
  "scripts": {
    "test": "pytest tests/ -v",
    "test:coverage": "pytest tests/ -v --cov=$MYPY_TARGET --cov-report=term-missing --cov-fail-under=80",
    "lint": "ruff check . && ruff format --check .",
    "lint:fix": "ruff check --fix . && ruff format .",
    "typecheck": "mypy $MYPY_TARGET --ignore-missing-imports",
    "security:semgrep": "semgrep scan --config=p/python --config=p/security-audit --config=p/secrets .",
    "audit": "pip-audit --strict --vulnerability-service pypi",
    "verify": "npm run lint && npm run typecheck && npm run test && npm run audit",
    "workflow:verify": "node scripts/verify.js",
    "workflow:verify:no-ai": "node scripts/verify.js --skip-ai-review",
    "workflow:ship": "node scripts/ship.js"
  },
  "license": "MIT"
}
EOF
        success "Created package.json"
    else
        warn "package.json exists - please add scripts manually if needed"
        info "Recommended scripts:"
        echo '  "test:coverage": "pytest tests/ -v --cov=src/ --cov-fail-under=80"'
        echo '  "typecheck": "mypy src/ --ignore-missing-imports"'
        echo '  "security:semgrep": "semgrep scan --config=p/python ."'
    fi
}

# Create CI workflow
create_ci_workflow() {
    if [ "$SKIP_CI" = true ]; then
        info "Skipping CI workflow (--skip-ci)"
        return
    fi

    info "Creating GitHub Actions CI workflow..."

    if [ -f ".github/workflows/ci.yml" ]; then
        warn ".github/workflows/ci.yml already exists - skipping"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would create .github/workflows/ci.yml"
        return
    fi

    mkdir -p .github/workflows

    cat > .github/workflows/ci.yml << 'EOF'
# =============================================================================
# CI Workflow - Ironclad Development Workflow
# =============================================================================
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  quality:
    name: Code Quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Ruff
        run: pip install ruff
      - name: Lint
        run: ruff check . --output-format=github
      - name: Format Check
        run: ruff format --check .

  typecheck:
    name: Type Check
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install mypy
        run: pip install mypy
      - name: Type Check
        run: mypy src/ --ignore-missing-imports

  tests:
    name: Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run tests
        run: pytest tests/ -v --cov=src/ --cov-report=term-missing

  security:
    name: Security Scan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: pip install -r requirements.txt pip-audit
      - name: Audit dependencies
        run: pip-audit --strict
        continue-on-error: true
      - name: Semgrep
        uses: returntocorp/semgrep-action@v1
        with:
          config: p/python p/security-audit
EOF

    success "Created .github/workflows/ci.yml"
}

# Copy workflow scripts
copy_workflow_scripts() {
    if [ "$SKIP_SCRIPTS" = true ]; then
        info "Skipping workflow scripts (--skip-scripts)"
        return
    fi

    info "Copying workflow scripts..."

    # Check if source scripts exist
    if [ ! -f "$IRONCLAD_SOURCE/scripts/verify.js" ]; then
        warn "Source verify.js not found at $IRONCLAD_SOURCE/scripts/"
        warn "Skipping script copy - you may need to create these manually"
        return
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would copy verify.js, ship.js, ai-review.js"
        return
    fi

    mkdir -p scripts

    for script in verify.js ship.js ai-review.js; do
        if [ -f "$IRONCLAD_SOURCE/scripts/$script" ]; then
            if [ ! -f "scripts/$script" ]; then
                cp "$IRONCLAD_SOURCE/scripts/$script" "scripts/$script"
                success "Copied $script"
            else
                warn "scripts/$script already exists - skipping"
            fi
        fi
    done
}

# Set up branch protection
setup_branch_protection() {
    if [ "$SKIP_BRANCH_PROTECTION" = true ]; then
        info "Skipping branch protection"
        return
    fi

    if [ -z "$GITHUB_OWNER" ] || [ -z "$GITHUB_REPO" ]; then
        warn "GitHub repo not detected - skipping branch protection"
        return
    fi

    info "Setting up branch protection for $GITHUB_OWNER/$GITHUB_REPO..."

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would enable branch protection on main"
        return
    fi

    # Check if gh is authenticated
    if ! gh auth status &> /dev/null; then
        warn "GitHub CLI not authenticated - run 'gh auth login' first"
        return
    fi

    gh api "repos/$GITHUB_OWNER/$GITHUB_REPO/branches/main/protection" -X PUT \
        -H "Accept: application/vnd.github+json" \
        --input - << 'EOF' 2>/dev/null && success "Branch protection enabled" || warn "Could not enable branch protection (may require admin access)"
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["Code Quality", "Tests"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
}

# Install pre-commit hooks
install_precommit() {
    info "Installing pre-commit hooks..."

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would run: pre-commit install"
        return
    fi

    if command -v pre-commit &> /dev/null; then
        pre-commit install && success "Pre-commit hooks installed"
    else
        warn "pre-commit not installed - run: pip install pre-commit && pre-commit install"
    fi
}

# Ensure requirements.txt exists
ensure_requirements() {
    if [ ! -f "requirements.txt" ]; then
        info "Creating empty requirements.txt..."
        if [ "$DRY_RUN" = false ]; then
            echo "# Runtime dependencies" > requirements.txt
            success "Created requirements.txt"
        fi
    fi
}

# Ensure tests directory exists
ensure_tests_dir() {
    if [ ! -d "tests" ]; then
        info "Creating tests directory..."
        if [ "$DRY_RUN" = false ]; then
            mkdir -p tests
            cat > tests/__init__.py << 'EOF'
# Test package
EOF
            cat > tests/test_placeholder.py << 'EOF'
"""Placeholder test - replace with real tests."""


def test_placeholder():
    """Placeholder test to ensure pytest runs."""
    assert True
EOF
            success "Created tests/ with placeholder test"
        fi
    fi
}

# Print summary
print_summary() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${GREEN}✅ Ironclad initialization complete!${NC}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Next steps:"
    echo "  1. Install dev dependencies:"
    echo "     pip install -r requirements-dev.txt"
    echo ""
    echo "  2. Install pre-commit hooks:"
    echo "     pre-commit install"
    echo ""
    echo "  3. Run verification:"
    echo "     npm run verify"
    echo "     # or: pytest && ruff check . && mypy src/"
    echo ""
    echo "  4. Commit the new files:"
    echo "     git add -A && git commit -m 'feat: add Ironclad workflow'"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main
main() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🔧 Ironclad Project Initializer"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    if [ "$DRY_RUN" = true ]; then
        warn "DRY RUN MODE - no changes will be made"
        echo ""
    fi

    check_prereqs
    detect_project

    echo ""
    info "Setting up Ironclad workflow..."
    echo ""

    ensure_requirements
    ensure_tests_dir
    create_precommit_config
    create_requirements_dev
    create_mypy_config
    create_prepush_hook
    create_package_json
    create_ci_workflow
    copy_workflow_scripts
    setup_branch_protection
    install_precommit

    print_summary
}

main "$@"
