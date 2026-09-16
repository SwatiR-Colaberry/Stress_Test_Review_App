'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { scanTextForCredentials, assertNoCredentialLeaks, CredentialLeakError } = require('./credentialLeakGuardrail');

// Happy path
test('happy path: config read from env vars and safe prose produces no findings', () => {
  const content = [
    'const apiKey = process.env.ANTHROPIC_API_KEY;',
    'const clientSecret = os.environ["BASECAMP_CLIENT_SECRET"]',
    '// Never place API keys in source code, browser JavaScript, or plain-text SQL tables.',
    'ANTHROPIC_API_KEY=your-key-here',
    'password = "changeme"',
  ].join('\n');

  assert.deepEqual(scanTextForCredentials(content), []);
  assert.deepEqual(assertNoCredentialLeaks(content, 'example.js'), { safe: true });
});

// Failure paths — one per shaped detector
test('detects an AWS access key id literal', () => {
  const findings = scanTextForCredentials('aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"');
  assert.equal(findings.length, 1);
  assert.equal(findings[0].pattern, 'AWS_ACCESS_KEY_ID');
});

test('detects an Anthropic-shaped API key literal', () => {
  const findings = scanTextForCredentials('const key = "sk-ant-api03-abcdefghijklmnopqrstuvwx";');
  assert.ok(findings.some((f) => f.pattern === 'ANTHROPIC_API_KEY'));
});

test('detects a GitHub token literal', () => {
  const findings = scanTextForCredentials('token: ghp_16C7e42F292c6912E7710c838347Ae178B4a');
  assert.ok(findings.some((f) => f.pattern === 'GITHUB_TOKEN'));
});

test('detects a private key block', () => {
  const findings = scanTextForCredentials('-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----');
  assert.ok(findings.some((f) => f.pattern === 'PRIVATE_KEY_BLOCK'));
});

test('detects a generic secret-shaped assignment with a real-looking value', () => {
  const findings = scanTextForCredentials('DB_PASSWORD="tr0ub4dor&3-actual-value"');
  assert.ok(findings.some((f) => f.pattern === 'GENERIC_SECRET_ASSIGNMENT'));
});

test('throws CredentialLeakError, never including the raw secret text, when a leak is found', () => {
  const content = 'api_key = "AKIAIOSFODNN7EXAMPLE-LOOKS-REAL"';
  assert.throws(
    () => assertNoCredentialLeaks(content, 'config.js'),
    (err) => {
      assert.ok(err instanceof CredentialLeakError);
      assert.equal(err.errorClass, 'ContractViolation');
      assert.equal(err.sourceLabel, 'config.js');
      assert.ok(!err.message.includes('AKIAIOSFODNN7EXAMPLE-LOOKS-REAL'), 'error message must not leak the raw secret');
      return true;
    }
  );
});

// Boundary cases
test('empty content produces no findings', () => {
  assert.deepEqual(scanTextForCredentials(''), []);
});

test('does not flag placeholder values assigned to secret-shaped keys', () => {
  const content = [
    'API_KEY=YOUR_API_KEY_HERE',
    'client_secret: "<client-secret>"',
    'token = "xxxxxxxxxxxxxxxxxxxx"',
    'password: "${DB_PASSWORD}"',
  ].join('\n');
  assert.deepEqual(scanTextForCredentials(content), []);
});

test('does not flag short generic values below the real-secret length threshold', () => {
  assert.deepEqual(scanTextForCredentials('token = "abc123"'), []);
});

test('non-string input produces no findings instead of throwing', () => {
  assert.deepEqual(scanTextForCredentials(undefined), []);
  assert.deepEqual(scanTextForCredentials(null), []);
});

// Idempotency
test('idempotent: scanning the same content twice yields identical results', () => {
  const content = 'aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"\napi_key="another-real-looking-secret-value"';
  const first = scanTextForCredentials(content);
  const second = scanTextForCredentials(content);
  assert.deepEqual(first, second);
});
