'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { assertSafeToFinalize, UnsafeFinalizationError } = require('./reviewFinalizationGuardrail');

function baseReview(overrides = {}) {
  return {
    reviewId: 'REV-1',
    finalFeedbackText: 'Looks good, ship it.',
    aiDraftAuthorId: 'claude-ai',
    reviewerDecision: {
      reviewerId: 'jane.reviewer',
      outcome: 'approved',
      decidedAt: '2026-09-13T00:00:00.000Z',
    },
    ...overrides,
  };
}

function assertRejects(review, expectedReasonCode) {
  assert.throws(
    () => assertSafeToFinalize(review),
    (err) => {
      assert.ok(err instanceof UnsafeFinalizationError);
      assert.equal(err.errorClass, 'ContractViolation');
      assert.equal(err.reasonCode, expectedReasonCode);
      return true;
    }
  );
}

// Happy path
test('happy path: genuine human approval is safe to finalize', () => {
  const result = assertSafeToFinalize(baseReview());
  assert.deepEqual(result, { safe: true });
});

// Failure paths
test('rejects when no reviewer decision exists at all', () => {
  assertRejects(baseReview({ reviewerDecision: null }), 'NO_HUMAN_REVIEW');
});

test('rejects a decision left pending', () => {
  assertRejects(
    baseReview({ reviewerDecision: { reviewerId: 'jane.reviewer', outcome: 'pending', decidedAt: '2026-09-13T00:00:00.000Z' } }),
    'NOT_APPROVED'
  );
});

test('rejects a decision the reviewer explicitly rejected', () => {
  assertRejects(
    baseReview({ reviewerDecision: { reviewerId: 'jane.reviewer', outcome: 'rejected', decidedAt: '2026-09-13T00:00:00.000Z' } }),
    'NOT_APPROVED'
  );
});

test('rejects when the AI/system actor is recorded as the approver', () => {
  assertRejects(
    baseReview({ reviewerDecision: { reviewerId: 'claude-ai', outcome: 'approved', decidedAt: '2026-09-13T00:00:00.000Z' } }),
    'AI_CANNOT_APPROVE'
  );
});

test("rejects when reviewerId matches the review's own aiDraftAuthorId, even outside the known-name list", () => {
  assertRejects(
    baseReview({
      aiDraftAuthorId: 'agent-42',
      reviewerDecision: { reviewerId: 'agent-42', outcome: 'approved', decidedAt: '2026-09-13T00:00:00.000Z' },
    }),
    'AI_CANNOT_APPROVE'
  );
});

// Boundary cases
test('rejects when reviewer identity is blank', () => {
  assertRejects(
    baseReview({ reviewerDecision: { reviewerId: '   ', outcome: 'approved', decidedAt: '2026-09-13T00:00:00.000Z' } }),
    'MISSING_REVIEWER_IDENTITY'
  );
});

test('rejects empty final feedback text even when properly approved', () => {
  assertRejects(baseReview({ finalFeedbackText: '   ' }), 'EMPTY_FEEDBACK');
});

// Idempotency
test('idempotent: evaluating the same review twice yields the same result', () => {
  const review = baseReview();
  const first = assertSafeToFinalize(review);
  const second = assertSafeToFinalize(review);
  assert.deepEqual(first, second);
});
