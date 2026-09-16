'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { normalizeCritiqueMarker, isCritiqueMarker } = require('./critiqueMarkerDetector');

test('accepts the four documented spacing variants', () => {
  for (const variant of ['##Critique##', '## Critique##', '##Critique ##', '## Critique ##']) {
    assert.equal(isCritiqueMarker(variant), true, `expected "${variant}" to trigger`);
    assert.equal(normalizeCritiqueMarker(variant), '##Critique##');
  }
});

test('accepts reasonable case variants of the same spacing forms', () => {
  for (const variant of ['##critique##', '##CRITIQUE##', '## CrItIqUe ##']) {
    assert.equal(isCritiqueMarker(variant), true, `expected "${variant}" to trigger`);
  }
});

test('detects the marker embedded inside a larger comment', () => {
  assert.equal(isCritiqueMarker('Done with V2, ready for review. ##Critique##'), true);
});

test('rejects plain "Critique" with no delimiters', () => {
  assert.equal(isCritiqueMarker('Critique'), false);
});

test('rejects a single-hash "#Critique"', () => {
  assert.equal(isCritiqueMarker('#Critique'), false);
});

test('rejects "##Review##"', () => {
  assert.equal(isCritiqueMarker('##Review##'), false);
});

test('rejects ordinary prose containing the word "critique"', () => {
  assert.equal(isCritiqueMarker('Can you give this a quick critique when you have time?'), false);
});

test('rejects non-string input without throwing', () => {
  assert.equal(isCritiqueMarker(null), false);
  assert.equal(isCritiqueMarker(undefined), false);
  assert.equal(isCritiqueMarker(42), false);
});

test('idempotent: evaluating the same comment twice yields the same result', () => {
  const body = '## Critique ##';
  assert.equal(isCritiqueMarker(body), isCritiqueMarker(body));
  assert.equal(normalizeCritiqueMarker(body), normalizeCritiqueMarker(body));
});
