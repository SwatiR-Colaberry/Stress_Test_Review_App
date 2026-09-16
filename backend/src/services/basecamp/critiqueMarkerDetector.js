'use strict';

const CRITIQUE_MARKER_PATTERN = /##\s?critique\s?##/i;

/**
 * Normalizes a Basecamp comment body and extracts the canonical critique
 * marker if a valid one is present. Per Master Spec §4: must accept
 * `##Critique##`, `## Critique##`, `##Critique ##`, `## Critique ##`
 * (any case), and must NOT trigger on `Critique`, `#Critique`,
 * `##Review##`, or prose that merely contains the word "critique".
 *
 * @param {string} commentBody
 * @returns {string|null} `##Critique##` if a valid marker is present, else null
 */
function normalizeCritiqueMarker(commentBody) {
  if (typeof commentBody !== 'string') return null;
  return CRITIQUE_MARKER_PATTERN.test(commentBody) ? '##Critique##' : null;
}

/**
 * @param {string} commentBody
 * @returns {boolean}
 */
function isCritiqueMarker(commentBody) {
  return normalizeCritiqueMarker(commentBody) !== null;
}

module.exports = { normalizeCritiqueMarker, isCritiqueMarker };
