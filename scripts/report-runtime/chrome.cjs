// Locate an installed Chrome/Chromium for headless report work (Mermaid rendering and report checks).
'use strict';
const fs = require('fs');
const path = require('path');

// Chrome aborts at startup inside the Codex seatbelt sandbox (no WindowServer access) and macOS shows a
// crash dialog each time. Callers refuse before launching it; report_check.py runs them outside the sandbox.
const SANDBOXED = 'Chrome cannot start inside the Codex sandbox. In a dashboard review, run scripts/report_check.py; otherwise rerun this command with escalated permissions.';

function chromePath() {
  const candidates = [
    process.env.PR_REVIEW_CHROME_PATH,
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
  ].filter(Boolean);
  const cache = path.join(process.env.HOME || '', 'Library/Caches/ms-playwright');
  if (fs.existsSync(cache)) {
    for (const dir of fs.readdirSync(cache).filter(d => /^chromium-\d+$/.test(d)).sort().reverse()) {
      candidates.push(path.join(cache, dir, 'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'));
      candidates.push(path.join(cache, dir, 'chrome-mac/Chromium.app/Contents/MacOS/Chromium'));
    }
  }
  const found = candidates.find(p => fs.existsSync(p));
  if (!found) throw new Error('No Chrome or Chromium found; set PR_REVIEW_CHROME_PATH');
  return found;
}

function refuseInSandbox() {
  if (process.env.CODEX_SANDBOX) { process.stderr.write(SANDBOXED + '\n'); process.exit(3); }
}

module.exports = {chromePath, refuseInSandbox};
