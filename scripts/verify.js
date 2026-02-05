#!/usr/bin/env node

/**
 * Verification Script
 * ===================
 * Generates verification state including:
 * - SHA256 hashes of source files
 * - Test results
 * - Lint status
 * - AI code review (Gemini)
 * - Timestamp
 * 
 * Usage: node scripts/verify.js [options]
 * 
 * Options:
 *   --skip-tests       Skip running tests
 *   --skip-lint        Skip running linter
 *   --skip-ai-review   Skip AI code review
 *   --security-focus   Focus AI review on security only
 * 
 * Environment:
 *   GEMINI_API_KEY     Required for AI review (optional if --skip-ai-review)
 */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execSync, execFileSync, spawn } = require('child_process');

// Configuration
const DEFAULT_EXTENSIONS = ['.js', '.jsx', '.ts', '.tsx', '.css', '.json'];
const OUTPUT_PATH = '.workflow/state/verify-state.json';

// Parse command line arguments
const args = process.argv.slice(2);
const options = {
  skipTests: args.includes('--skip-tests'),
  skipLint: args.includes('--skip-lint'),
  skipAiReview: args.includes('--skip-ai-review'),
  securityFocus: args.includes('--security-focus'),
  outputPath: OUTPUT_PATH
};

// Utility functions
function hashFile(filePath) {
  try {
    const content = fs.readFileSync(filePath);
    return crypto.createHash('sha256').update(content).digest('hex');
  } catch (error) {
    console.error('Error hashing ' + filePath + ':', error.message);
    return null;
  }
}

function findFiles(baseDir) {
  const files = [];
  
  function walkDir(dir) {
    if (!fs.existsSync(dir)) return;
    
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      
      if (entry.name.startsWith('.') || entry.name === 'node_modules') {
        continue;
      }
      
      if (entry.isDirectory()) {
        walkDir(fullPath);
      } else if (entry.isFile()) {
        const ext = path.extname(entry.name);
        if (DEFAULT_EXTENSIONS.includes(ext)) {
          files.push(fullPath);
        }
      }
    }
  }
  
  const srcDir = path.join(baseDir, 'src');
  if (fs.existsSync(srcDir)) {
    walkDir(srcDir);
  } else {
    console.log('No src/ directory found. Scanning current directory...');
    walkDir(baseDir);
  }
  
  return files.sort();
}

function runCommand(command, description) {
  console.log('\n' + description + '...');
  try {
    const output = execSync(command, { 
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    return { success: true, output: output.trim() };
  } catch (error) {
    return { 
      success: false, 
      output: error.stdout ? error.stdout.trim() : '',
      error: error.stderr ? error.stderr.trim() : error.message
    };
  }
}

function runTests() {
  if (options.skipTests) {
    console.log('Skipping tests (--skip-tests)');
    return { skipped: true };
  }
  
  try {
    const pkg = JSON.parse(fs.readFileSync('package.json', 'utf-8'));
    if (!pkg.scripts || !pkg.scripts.test) {
      console.log('No test script found in package.json');
      return { skipped: true, reason: 'no test script' };
    }
  } catch (e) {
    console.log('No package.json found');
    return { skipped: true, reason: 'no package.json' };
  }
  
  const result = runCommand('npm test 2>&1', 'Running tests');
  return {
    success: result.success,
    output: result.output,
    error: result.error
  };
}

function runLint() {
  if (options.skipLint) {
    console.log('Skipping lint (--skip-lint)');
    return { skipped: true };
  }
  
  try {
    const pkg = JSON.parse(fs.readFileSync('package.json', 'utf-8'));
    if (!pkg.scripts || !pkg.scripts.lint) {
      console.log('No lint script found in package.json');
      return { skipped: true, reason: 'no lint script' };
    }
  } catch (e) {
    return { skipped: true, reason: 'no package.json' };
  }
  
  const result = runCommand('npm run lint 2>&1', 'Running linter');
  return {
    success: result.success,
    output: result.output,
    error: result.error
  };
}

function runAudit() {
  const result = runCommand('npm audit --audit-level=high 2>&1', 'Running security audit');
  
  const output = result.output || '';
  const hasHighCritical = output.includes('high') || output.includes('critical');
  
  return {
    success: !hasHighCritical || result.success,
    output: output.substring(0, 500)
  };
}

function runAiReview() {
  if (options.skipAiReview) {
    console.log('Skipping AI review (--skip-ai-review)');
    return { skipped: true };
  }
  
  // Check for API key
  if (!process.env.GEMINI_API_KEY) {
    console.log('No GEMINI_API_KEY set, skipping AI review');
    console.log('Set with: export GEMINI_API_KEY="your-key"');
    return { skipped: true, reason: 'no API key' };
  }
  
  // Check if ai-review.js exists
  const aiReviewPath = path.join(__dirname, 'ai-review.js');
  if (!fs.existsSync(aiReviewPath)) {
    console.log('AI review script not found');
    return { skipped: true, reason: 'script not found' };
  }
  
  console.log('\nRunning AI Code Review (Gemini)...');
  
  try {
    const aiArgs = options.securityFocus ? ['--security-focus'] : [];
    // Use execFileSync to avoid shell interpretation of the path
    const result = execFileSync(process.execPath, [aiReviewPath, ...aiArgs], {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
      env: process.env,
      timeout: 120000 // 2 minute timeout
    });
    
    // Read the AI review results
    const aiResultPath = '.workflow/state/ai-review.json';
    if (fs.existsSync(aiResultPath)) {
      const aiResults = JSON.parse(fs.readFileSync(aiResultPath, 'utf-8'));
      return {
        success: aiResults.summary.passesReview,
        securityRisk: aiResults.summary.securityRisk,
        codeQuality: aiResults.summary.codeQuality,
        securityIssues: aiResults.securityReview?.issues?.length || 0,
        qualityIssues: aiResults.qualityReview?.issues?.length || 0
      };
    }
    
    return { success: true, output: result };
  } catch (error) {
    console.log('AI review completed with findings');
    
    // Still try to read results even if exit code was non-zero
    const aiResultPath = '.workflow/state/ai-review.json';
    if (fs.existsSync(aiResultPath)) {
      try {
        const aiResults = JSON.parse(fs.readFileSync(aiResultPath, 'utf-8'));
        return {
          success: aiResults.summary.passesReview,
          securityRisk: aiResults.summary.securityRisk,
          codeQuality: aiResults.summary.codeQuality,
          securityIssues: aiResults.securityReview?.issues?.length || 0,
          qualityIssues: aiResults.qualityReview?.issues?.length || 0,
          needsAttention: !aiResults.summary.passesReview
        };
      } catch (e) {
        // Ignore parse errors
      }
    }
    
    return {
      success: false,
      error: error.message
    };
  }
}

// Main verification process
async function main() {
  console.log('='.repeat(60));
  console.log('VERIFICATION SCRIPT');
  console.log('='.repeat(60));
  console.log('Timestamp: ' + new Date().toISOString());
  
  // Find and hash files
  console.log('\nFinding source files...');
  const files = findFiles('.');
  console.log('Found ' + files.length + ' files to hash');
  
  const fileHashes = {};
  for (const file of files) {
    const hash = hashFile(file);
    if (hash) {
      fileHashes[file] = hash;
    }
  }
  
  // Run checks
  const testResults = runTests();
  const lintResults = runLint();
  const auditResults = runAudit();
  const aiReviewResults = runAiReview();
  
  // Build verification state
  const verifyState = {
    version: '1.1.0',
    timestamp: new Date().toISOString(),
    files: {
      count: Object.keys(fileHashes).length,
      hashes: fileHashes
    },
    tests: testResults,
    lint: lintResults,
    audit: auditResults,
    aiReview: aiReviewResults,
    summary: {
      filesHashed: Object.keys(fileHashes).length,
      testsPass: testResults.success || testResults.skipped,
      lintPass: lintResults.success || lintResults.skipped,
      auditPass: auditResults.success,
      aiReviewPass: aiReviewResults.success || aiReviewResults.skipped,
      overallPass: (testResults.success || testResults.skipped) &&
                   (lintResults.success || lintResults.skipped) &&
                   auditResults.success &&
                   (aiReviewResults.success || aiReviewResults.skipped)
    }
  };
  
  // Ensure output directory exists
  const outputDir = path.dirname(options.outputPath);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }
  
  // Write verification state
  fs.writeFileSync(
    options.outputPath,
    JSON.stringify(verifyState, null, 2)
  );
  
  // Print summary
  console.log('\n' + '='.repeat(60));
  console.log('VERIFICATION SUMMARY');
  console.log('='.repeat(60));
  console.log('Files hashed:    ' + verifyState.summary.filesHashed);
  console.log('Tests:           ' + (verifyState.summary.testsPass ? 'PASS' : 'FAIL'));
  console.log('Lint:            ' + (verifyState.summary.lintPass ? 'PASS' : 'FAIL'));
  console.log('Security Audit:  ' + (verifyState.summary.auditPass ? 'PASS' : 'FAIL'));
  console.log('AI Review:       ' + (verifyState.summary.aiReviewPass ? 'PASS' : 'NEEDS ATTENTION'));
  
  if (aiReviewResults.securityRisk) {
    console.log('  Security Risk: ' + aiReviewResults.securityRisk);
  }
  if (aiReviewResults.codeQuality) {
    console.log('  Code Quality:  ' + aiReviewResults.codeQuality);
  }
  
  console.log('-'.repeat(60));
  console.log('OVERALL:         ' + (verifyState.summary.overallPass ? 'PASS' : 'FAIL'));
  console.log('='.repeat(60));
  console.log('\nVerification state written to: ' + options.outputPath);
  
  if (aiReviewResults.needsAttention) {
    console.log('\nNote: AI review found issues that need attention.');
    console.log('Review details in: .workflow/state/ai-review.json');
  }
  
  // Exit with appropriate code
  process.exit(verifyState.summary.overallPass ? 0 : 1);
}

main().catch(function(error) {
  console.error('Verification failed:', error);
  process.exit(1);
});
