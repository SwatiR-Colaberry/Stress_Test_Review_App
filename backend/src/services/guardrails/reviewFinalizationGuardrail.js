'use strict';

const AI_ACTOR_IDS = new Set(['ai', 'claude', 'claude-ai', 'system', 'bot', 'automation']);

class UnsafeFinalizationError extends Error {
  constructor(reasonCode, message) {
    super(message);
    this.name = 'UnsafeFinalizationError';
    this.errorClass = 'ContractViolation';
    this.reasonCode = reasonCode;
  }
}

/**
 * @typedef {Object} ReviewerDecision
 * @property {string} reviewerId - Identity of the human reviewer who made the decision.
 * @property {'approved' | 'rejected' | 'pending'} outcome
 * @property {string} decidedAt - ISO-8601 timestamp.
 */

/**
 * @typedef {Object} StressTestReview
 * @property {string} reviewId
 * @property {string} finalFeedbackText - Content that would be posted to Basecamp.
 * @property {string} aiDraftAuthorId - Identity used to author the AI's draft (e.g. "claude-ai").
 * @property {ReviewerDecision | null | undefined} reviewerDecision
 */

/**
 * Enforces R4: a review may only be finalized (marked Completed / posted to
 * Basecamp) once a genuine human reviewer has approved it. Throws
 * UnsafeFinalizationError otherwise.
 *
 * Pure and synchronous by design: this is the gate every future finalize /
 * post-to-Basecamp code path must call, so it must not depend on the
 * database, Basecamp, or Claude being available.
 *
 * See Master Project Specification §22 (Status Model) and §26 (MVP
 * Acceptance Criteria): "Completed must never mean AI finished" and "AI
 * never final-approves a submission."
 *
 * @param {StressTestReview} review
 * @returns {{ safe: true }}
 */
function assertSafeToFinalize(review) {
  const decision = review && review.reviewerDecision;

  if (!decision) {
    throw new UnsafeFinalizationError(
      'NO_HUMAN_REVIEW',
      `Review ${review && review.reviewId} has no reviewer decision recorded; cannot finalize.`
    );
  }

  if (!decision.reviewerId || typeof decision.reviewerId !== 'string' || decision.reviewerId.trim() === '') {
    throw new UnsafeFinalizationError(
      'MISSING_REVIEWER_IDENTITY',
      `Review ${review.reviewId} decision has no reviewer identity; cannot finalize.`
    );
  }

  const normalizedReviewerId = decision.reviewerId.trim().toLowerCase();
  const normalizedAiAuthorId = String(review.aiDraftAuthorId || '').trim().toLowerCase();
  if (AI_ACTOR_IDS.has(normalizedReviewerId) || (normalizedAiAuthorId && normalizedReviewerId === normalizedAiAuthorId)) {
    throw new UnsafeFinalizationError(
      'AI_CANNOT_APPROVE',
      `Review ${review.reviewId} decision was recorded under an AI/system identity ("${decision.reviewerId}"); AI may never final-approve a submission.`
    );
  }

  if (decision.outcome !== 'approved') {
    throw new UnsafeFinalizationError(
      'NOT_APPROVED',
      `Review ${review.reviewId} reviewer decision outcome is "${decision.outcome}", not "approved"; cannot finalize.`
    );
  }

  if (!review.finalFeedbackText || review.finalFeedbackText.trim() === '') {
    throw new UnsafeFinalizationError(
      'EMPTY_FEEDBACK',
      `Review ${review.reviewId} has no final feedback text; cannot finalize.`
    );
  }

  return { safe: true };
}

module.exports = { assertSafeToFinalize, UnsafeFinalizationError, AI_ACTOR_IDS };
