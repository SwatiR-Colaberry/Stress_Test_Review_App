#!/usr/bin/env node
'use strict';

// One-off operational script: walks the repo and enforces REQ-016 / R4 —
// no credentials stored in source code or shared documents. Exits non-zero
// if anything is found. Run with `npm run scan:secrets`.

const fs = require('node:fs');
const path = require('node:path');
const { scanTextForCredentials } = require('../services/guardrails/credentialLeakGuardrail');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const SKIP_DIRS = new Set(['.git', 'node_modules']);
const SKIP_EXTENSIONS = new Set([
  '.docx', '.doc', '.pdf', '.zip', '.png', '.jpg', '.jpeg', '.gif', '.ico',
  '.woff', '.woff2', '.ttf', '.eot', '.mp4', '.mov', '.mp3',
]);
const MAX_BYTES = 2 * 1024 * 1024;

function walk(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP_DIRS.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, out);
    } else if (entry.isFile()) {
      out.push(full);
    }
  }
  return out;
}

function isLikelyBinary(buffer) {
  return buffer.includes(0);
}

function main() {
  const files = walk(REPO_ROOT, []);
  const allFindings = [];
  let scanned = 0;

  for (const filePath of files) {
    const ext = path.extname(filePath).toLowerCase();
    if (SKIP_EXTENSIONS.has(ext)) continue;
    // Test fixtures deliberately contain fake, credential-shaped values to
    // exercise the detectors themselves — that's the point of those tests.
    if (filePath.endsWith('.test.js')) continue;

    const stat = fs.statSync(filePath);
    if (stat.size === 0 || stat.size > MAX_BYTES) continue;

    const buffer = fs.readFileSync(filePath);
    if (isLikelyBinary(buffer)) continue;

    scanned += 1;
    const relativePath = path.relative(REPO_ROOT, filePath);
    const findings = scanTextForCredentials(buffer.toString('utf8'));
    for (const finding of findings) {
      allFindings.push({ ...finding, file: relativePath });
    }
  }

  if (allFindings.length > 0) {
    console.error(`Credential-shaped content found (${allFindings.length}):`);
    for (const f of allFindings) {
      console.error(`  ${f.file}:${f.line}  ${f.pattern}`);
    }
    console.error('\nRemove or redact the value above, or move it to an env var, before committing.');
    process.exitCode = 1;
    return;
  }

  console.log(`No credential-shaped content found across ${scanned} text files.`);
}

main();
