'use strict';

class CredentialLeakError extends Error {
  constructor(findings, sourceLabel) {
    const summary = findings.map((f) => `${f.pattern} at line ${f.line}`).join('; ');
    super(`Credential-shaped content found in ${sourceLabel || 'source'}: ${summary}`);
    this.name = 'CredentialLeakError';
    this.errorClass = 'ContractViolation';
    this.findings = findings;
    this.sourceLabel = sourceLabel || null;
  }
}

/**
 * Values that look like they're assigned to a secret-shaped key but are not
 * real secrets: placeholders, env-var interpolation, angle-bracket
 * instructions, redaction markers. Never flag these.
 */
function isPlaceholderValue(value) {
  const v = value.trim();
  if (v === '') return true;
  if (/^(x{3,}|\*{3,}|-{3,}|\.{3,})$/i.test(v)) return true;
  if (/^(your[_-]?|replace[_-]?me|change[_-]?me|placeholder|example|dummy|fake|sample|redacted|todo)/i.test(v)) return true;
  if (/^<.*>$/.test(v)) return true;
  if (/^\$\{.*\}$/.test(v)) return true;
  if (/^%[A-Z_]+%$/.test(v)) return true;
  return false;
}

// Fixed-format secrets: matching the shape alone is enough to flag them.
const SHAPED_DETECTORS = [
  { pattern: 'AWS_ACCESS_KEY_ID', regex: /\bAKIA[0-9A-Z]{16}\b/g },
  { pattern: 'ANTHROPIC_API_KEY', regex: /\bsk-ant-[A-Za-z0-9_-]{20,}\b/g },
  { pattern: 'OPENAI_STYLE_API_KEY', regex: /\bsk-[A-Za-z0-9]{32,}\b/g },
  { pattern: 'GITHUB_TOKEN', regex: /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g },
  { pattern: 'SLACK_TOKEN', regex: /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g },
  { pattern: 'PRIVATE_KEY_BLOCK', regex: /-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----/g },
];

// Assignment-shaped secrets: a secret-sounding key bound to a non-placeholder
// literal value, e.g. a credential hardcoded directly in a config or source
// file, as opposed to a process.env.X / os.environ[...] reference or a
// placeholder value, neither of which this should flag.
const ASSIGNMENT_KEY_PATTERN = /(api[_-]?key|secret|password|passwd|token|client[_-]?secret|auth[_-]?token)/i;
const ASSIGNMENT_REGEX = /([A-Za-z0-9_.-]*(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret|auth[_-]?token)[A-Za-z0-9_.-]*)\s*[:=]\s*(?:["']([^"'\n]{8,})["']|([A-Za-z0-9/+_=-]{12,})(?=[\s,;)]|$))/gi;

function lineNumberAt(text, index) {
  let line = 1;
  for (let i = 0; i < index; i += 1) {
    if (text.charCodeAt(i) === 10) line += 1;
  }
  return line;
}

/**
 * @typedef {Object} CredentialFinding
 * @property {string} pattern - which detector matched, e.g. "AWS_ACCESS_KEY_ID"
 * @property {number} line - 1-indexed line number
 */

/**
 * Scans text content for credential-shaped strings. Pure and synchronous;
 * never includes the matched secret value itself in its output, only the
 * detector name and line — findings must be safe to log per the repo's own
 * "no secrets in logs" rule.
 *
 * @param {string} content
 * @returns {CredentialFinding[]}
 */
function scanTextForCredentials(content) {
  if (typeof content !== 'string' || content.length === 0) return [];

  const findings = [];

  for (const detector of SHAPED_DETECTORS) {
    detector.regex.lastIndex = 0;
    let match;
    while ((match = detector.regex.exec(content)) !== null) {
      findings.push({ pattern: detector.pattern, line: lineNumberAt(content, match.index) });
    }
  }

  ASSIGNMENT_REGEX.lastIndex = 0;
  let match;
  while ((match = ASSIGNMENT_REGEX.exec(content)) !== null) {
    const key = match[1];
    const value = match[2] !== undefined ? match[2] : match[3];
    if (!ASSIGNMENT_KEY_PATTERN.test(key)) continue;
    if (isPlaceholderValue(value)) continue;
    // process.env.X / os.environ[...] references have no literal value to
    // capture in the first place, so they never reach this branch.
    findings.push({ pattern: 'GENERIC_SECRET_ASSIGNMENT', line: lineNumberAt(content, match.index) });
  }

  return findings.sort((a, b) => a.line - b.line);
}

/**
 * Enforces REQ-016 / R4: no credentials stored in source code or shared
 * documents. Throws CredentialLeakError if scanTextForCredentials finds
 * anything; otherwise returns { safe: true }.
 *
 * @param {string} content
 * @param {string} [sourceLabel] - file path or document name, for the error message
 * @returns {{ safe: true }}
 */
function assertNoCredentialLeaks(content, sourceLabel) {
  const findings = scanTextForCredentials(content);
  if (findings.length > 0) {
    throw new CredentialLeakError(findings, sourceLabel);
  }
  return { safe: true };
}

module.exports = { scanTextForCredentials, assertNoCredentialLeaks, CredentialLeakError };
