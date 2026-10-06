#!/usr/bin/env node
// Render Mermaid sources to static SVG for a review report (called by scripts/review_mermaid.py).
// stdin: [{"id": "mm-abc", "source": "sequenceDiagram ..."}]
// stdout: {"mm-abc": {"svg": "<svg ...>"} | {"error": "..."}}
// The report never loads Mermaid; render_review.py sanitizes and inlines the SVG.
'use strict';
const fs = require('fs');
const path = require('path');
const {chromium} = require('playwright-core');
const {chromePath, refuseInSandbox} = require('./chrome.cjs');

refuseInSandbox();

(async () => {
  const items = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({executablePath: chromePath(), args: ['--no-sandbox']});
  const result = {};
  try {
    const page = await browser.newPage();
    await page.route(/^https?:/, route => route.abort());
    // Measure labels with the font the report uses, or they overflow their boxes.
    const font = fs.readFileSync(path.join(__dirname, '..', '..', 'assets', 'fonts', 'ibm-plex-sans-400.woff2')).toString('base64');
    await page.setContent(`<!doctype html><style>@font-face{font-family:"IBM Plex Sans";src:url(data:font/woff2;base64,${font}) format("woff2")}body{font-family:"IBM Plex Sans"}</style><body>x</body>`);
    await page.evaluate(() => document.fonts.ready);
    await page.addScriptTag({path: require.resolve('mermaid/dist/mermaid.min.js')});
    await page.evaluate(() => window.mermaid.initialize({
      startOnLoad: false, securityLevel: 'strict', theme: 'base', htmlLabels: false,
      fontFamily: 'IBM Plex Sans, system-ui, sans-serif',
      flowchart: {htmlLabels: false, useMaxWidth: true},
      sequence: {useMaxWidth: true, messageFontSize: 14, actorFontSize: 14, noteFontSize: 13, mirrorActors: false,
                 showSequenceNumbers: true, boxMargin: 8, noteMargin: 12, messageMargin: 34, actorMargin: 40, wrap: true, width: 140},
    }));
    for (const {id, source} of items) {
      try {
        result[id] = {svg: await page.evaluate(async ([i, s]) => (await window.mermaid.render(i, s)).svg, [id, source])};
      } catch (error) {
        result[id] = {error: String(error.message || error).split('\n').slice(0, 4).join(' ')};
        await page.evaluate(i => document.getElementById('d' + i)?.remove(), id);
      }
    }
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(result));
})().catch(error => { process.stderr.write(String(error.stack || error)); process.exit(1); });
