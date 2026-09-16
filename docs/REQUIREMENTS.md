# Stress Test Review Application — Requirements

A controlled review platform integrating Basecamp and human reviewers, with AI-assisted draft reviews.

This is the source of truth for what you are building. Your Claude Code prompts
point here. If you sharpen a requirement, edit it — your version is the real one.

| Kind | Meaning |
|---|---|
| Functional | something the system does |
| Safety | a guardrail, with a check that enforces it |
| Reliability | how it behaves when something fails |
| Constraint | a technology or vendor you must use — context, not a task |

## AI Evaluation

### REQ-005 — Functional · must

Claude must evaluate submissions against loaded rules, returning structured draft findings with rule ID, status, severity, evidence, reason, and confidence score.

Fulfilled by: STORY-004

### REQ-014 — Constraint

The system must use Claude via the Anthropic API for AI evaluations.

Context for the stories that use it — constraints do not get their own story.

## API Design

### REQ-015 — Constraint

The system must expose a typed API using FastAPI and Pydantic models.

Context for the stories that use it — constraints do not get their own story.

## Audit and History

### REQ-008 — Safety · must

The system must preserve the history of each review, including AI drafts and human edits, for audit purposes.

Fulfilled by: STORY-007

## Data Retrieval

### REQ-004 — Functional · must

The system must retrieve all necessary submission data from Basecamp, including comments, attachments, and links.

Fulfilled by: STORY-002

## Data Storage

### REQ-013 — Constraint

The system must connect to Microsoft SQL Server for data storage and retrieval.

Context for the stories that use it — constraints do not get their own story.

## Error Handling

### REQ-009 — Functional · must

The system must route ambiguous project or Stress Test identifications to manual resolution rather than guessing.

Fulfilled by: STORY-008

### REQ-010 — Safety · must

The system must retry external API calls safely within a bounded number of attempts and surface visible errors if they fail.

Fulfilled by: STORY-009

## Extensibility

### REQ-017 — Non-functional · should

The system must support adding new Stress Test modules (ST1–ST5) as configuration without rebuilding the core application.

Fulfilled by: STORY-010

## Human Review

### REQ-006 — Functional · must

Human reviewers must be able to approve, edit, reject, or add findings before final feedback is posted back to Basecamp.

Fulfilled by: STORY-005

### REQ-011 — Safety · must

The system must not auto-approve any submission; human review is mandatory.

Fulfilled by: STORY-011

## Integration

### REQ-012 — Constraint

The system must use Basecamp's OAuth 2.0 for authentication and authorization.

Fulfilled by: STORY-002

## Marker Detection

### REQ-001 — Functional · must

The system must detect a '##Critique##' marker in Basecamp comments, normalizing reasonable spacing and case variants.

Fulfilled by: STORY-001

## Review Completion

### REQ-007 — Functional · must

The system must mark reviews as 'Completed' only after human review and Basecamp posting are both done.

Fulfilled by: STORY-006

## Review Queue

### REQ-002 — Functional · must

The system must create a Review Queue item with status 'Pending' for each detected critique marker, tied to the exact submission/version.

Fulfilled by: STORY-001

## Rule Application

### REQ-003 — Functional · must

The system must load only the rule module for the identified Stress Test (ST0) and never apply generic or incorrect rules.

Fulfilled by: STORY-003

## Security

### REQ-016 — Safety · must

The system must ensure that no credentials are stored in source code or shared documents.

Fulfilled by: STORY-011

## User Interface

### REQ-018 — Functional · must

The system must provide a web UI for reviewers to manage the Review Queue and perform reviews.

Fulfilled by: STORY-012
