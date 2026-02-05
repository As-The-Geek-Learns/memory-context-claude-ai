#!/usr/bin/env node

/**
 * Ship Script
 * ===========
 * Validates file integrity and prepares for shipping:
 * - Verifies file hashes match verification state
 * - Checks all gates are satisfied
 * - Optionally creates PR
 *
 * Usage: node scripts/ship.js [options]
 *
 * Options:
 *   --create-pr        Create a GitHub PR (requires gh CLI)
 *   --dry-run          Show what would be done without doing it
 *   --state <path>     Path to verify-state.json
 */

const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { execSync } = require("child_process");

// Configuration
const DEFAULT_STATE_PATH = ".workflow/state/verify-state.json";

// Parse command line arguments
const args = process.argv.slice(2);
const options = {
  createPR: args.includes("--create-pr"),
  dryRun: args.includes("--dry-run"),
  statePath: DEFAULT_STATE_PATH,
};

const statePathIndex = args.indexOf("--state");
if (statePathIndex !== -1 && args[statePathIndex + 1]) {
  options.statePath = args[statePathIndex + 1];
}

function hashFile(filePath) {
  try {
    const content = fs.readFileSync(filePath);
    return crypto.createHash("sha256").update(content).digest("hex");
  } catch (error) {
    return null;
  }
}

function runCommand(command, dryRun = false) {
  if (dryRun) {
    console.log("[DRY RUN] Would execute: " + command);
    return { success: true, dryRun: true };
  }

  try {
    // nosemgrep: javascript.lang.security.detect-child-process.detect-child-process -- command is from package.json scripts, not user input
    const output = execSync(command, {
      encoding: "utf-8",
      stdio: ["pipe", "pipe", "pipe"],
    });
    return { success: true, output: output.trim() };
  } catch (error) {
    return {
      success: false,
      output: error.stdout ? error.stdout.trim() : "",
      error: error.stderr ? error.stderr.trim() : error.message,
    };
  }
}

function loadVerifyState() {
  if (!fs.existsSync(options.statePath)) {
    console.error("ERROR: Verification state not found at " + options.statePath);
    console.error("Run \"node scripts/verify.js\" first to generate verification state.");
    return null;
  }

  try {
    return JSON.parse(fs.readFileSync(options.statePath, "utf-8"));
  } catch (error) {
    console.error("ERROR: Failed to parse verification state: " + error.message);
    return null;
  }
}

function verifyFileIntegrity(state) {
  console.log("\nVerifying file integrity...");

  const results = {
    verified: 0,
    modified: [],
    missing: [],
    total: Object.keys(state.files.hashes).length,
  };

  for (const [filePath, expectedHash] of Object.entries(state.files.hashes)) {
    if (!fs.existsSync(filePath)) {
      results.missing.push(filePath);
      continue;
    }

    const currentHash = hashFile(filePath);
    if (currentHash === expectedHash) {
      results.verified++;
    } else {
      results.modified.push({
        file: filePath,
        expected: expectedHash.substring(0, 8) + "...",
        actual: (currentHash && currentHash.substring(0, 8) + "...") || "null",
      });
    }
  }

  return results;
}

function checkGates(state) {
  console.log("\nChecking gates...");

  const gates = {
    verificationPassed: state.summary && state.summary.overallPass,
    testsPass: state.summary && state.summary.testsPass,
    lintPass: state.summary && state.summary.lintPass,
    auditPass: state.summary && state.summary.auditPass,
  };

  return gates;
}

function getCurrentBranch() {
  const result = runCommand("git branch --show-current");
  return result.success ? result.output : null;
}

function getDefaultBranch() {
  const result = runCommand("git remote show origin 2>/dev/null | grep \"HEAD branch\" | cut -d: -f2");
  if (result.success && result.output) {
    return result.output.trim();
  }
  const mainExists = runCommand("git show-ref --verify --quiet refs/heads/main");
  return mainExists.success ? "main" : "master";
}

function createPullRequest(state, integrityResults) {
  console.log("\nPreparing pull request...");

  const branch = getCurrentBranch();
  const defaultBranch = getDefaultBranch();

  if (!branch) {
    console.error("ERROR: Could not determine current branch");
    return false;
  }

  if (branch === defaultBranch) {
    console.error("ERROR: Cannot create PR from " + defaultBranch + " branch");
    return false;
  }

  const ghCheck = runCommand("which gh");
  if (!ghCheck.success) {
    console.error("ERROR: GitHub CLI (gh) not found. Install it or create PR manually.");
    return false;
  }

  const prBody = `## Verification Summary

- **Timestamp:** ${state.timestamp}
- **Files Verified:** ${integrityResults.verified}/${integrityResults.total}
- **Tests:** ${state.summary.testsPass ? "PASS" : "FAIL"}
- **Lint:** ${state.summary.lintPass ? "PASS" : "FAIL"}
- **Security Audit:** ${state.summary.auditPass ? "PASS" : "FAIL"}

## File Integrity

All ${integrityResults.verified} files match their verified hashes.

## Checklist

- [x] Verification script passed
- [x] File integrity confirmed
- [ ] Human review completed
`;

  const prTitle = "[Verified] " + branch;

  // Write PR body to temp file to avoid shell injection issues
  // (using --body-file instead of --body with escaped content)
  // Use mkdtempSync for secure temp directory creation (prevents race conditions)
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "cortex-ship-"));
  const tempBodyFile = path.join(tempDir, "pr-body.md");
  fs.writeFileSync(tempBodyFile, prBody, "utf-8");

  try {
    // Escape backslashes first, then other shell-sensitive characters
    const escapedTitle = prTitle
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\$/g, "\\$")
      .replace(/`/g, "\\`");

    const createCmd =
      "gh pr create --title \"" +
      escapedTitle +
      "\" --body-file \"" +
      tempBodyFile +
      "\" --base " +
      defaultBranch;

    const result = runCommand(createCmd, options.dryRun);

    if (result.success) {
      console.log("Pull request created successfully!");
      if (result.output) {
        console.log("PR URL: " + result.output);
      }
      return true;
    } else {
      console.error("Failed to create pull request:", result.error);
      return false;
    }
  } finally {
    // Clean up temp directory and file
    try {
      fs.unlinkSync(tempBodyFile);
      fs.rmdirSync(tempDir);
    } catch (_e) {
      // Ignore cleanup errors
    }
  }
}

async function main() {
  console.log("=".repeat(60));
  console.log("SHIP SCRIPT");
  console.log("=".repeat(60));
  console.log("Timestamp: " + new Date().toISOString());

  if (options.dryRun) {
    console.log("\n*** DRY RUN MODE - No changes will be made ***\n");
  }

  const state = loadVerifyState();
  if (!state) {
    process.exit(1);
  }

  console.log("\nLoaded verification state from: " + options.statePath);
  console.log("Verification timestamp: " + state.timestamp);

  const verifyTime = new Date(state.timestamp);
  const hoursSinceVerify = (Date.now() - verifyTime.getTime()) / (1000 * 60 * 60);

  if (hoursSinceVerify > 4) {
    console.warn("\nWARNING: Verification is " + hoursSinceVerify.toFixed(1) + " hours old.");
    console.warn("Consider re-running verification for fresh state.");
  }

  const gates = checkGates(state);
  let gatesPass = true;

  console.log("\nGate Status:");
  for (const [gate, passed] of Object.entries(gates)) {
    const status = passed ? "PASS" : "FAIL";
    console.log("  " + gate + ": " + status);
    if (!passed) gatesPass = false;
  }

  if (!gatesPass) {
    console.error("\nERROR: Not all gates passed. Cannot proceed with ship.");
    console.error("Run verification again after fixing issues.");
    process.exit(1);
  }

  const integrityResults = verifyFileIntegrity(state);

  console.log("\nIntegrity Results:");
  console.log("  Verified: " + integrityResults.verified + "/" + integrityResults.total);

  if (integrityResults.modified.length > 0) {
    console.error("\nERROR: Files modified since verification:");
    for (const mod of integrityResults.modified) {
      console.error("  " + mod.file);
      console.error("    Expected: " + mod.expected);
      console.error("    Actual:   " + mod.actual);
    }
    console.error("\nCannot ship code that differs from verified state.");
    console.error("Run verification again to capture current state.");
    process.exit(1);
  }

  if (integrityResults.missing.length > 0) {
    console.error("\nERROR: Files missing since verification:");
    for (const file of integrityResults.missing) {
      console.error("  " + file);
    }
    process.exit(1);
  }

  console.log("\n" + "=".repeat(60));
  console.log("ALL CHECKS PASSED - READY TO SHIP");
  console.log("=".repeat(60));

  if (options.createPR) {
    const prSuccess = createPullRequest(state, integrityResults);
    if (!prSuccess && !options.dryRun) {
      process.exit(1);
    }
  } else {
    console.log("\nNext steps:");
    console.log("1. Create a pull request with the verification evidence");
    console.log("2. Include the verification timestamp in PR description");
    console.log("3. Request human review");
    console.log("\nOr run with --create-pr to automatically create a GitHub PR");
  }

  process.exit(0);
}

main().catch(function (error) {
  console.error("Ship failed:", error);
  process.exit(1);
});
