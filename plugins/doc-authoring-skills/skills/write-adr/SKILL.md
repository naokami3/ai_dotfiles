---
name: write-adr
description: >
  Create Architecture Decision Records (ADRs) to document technical decisions with context, alternatives, and consequences.
  TRIGGER when: a technical decision is made (library selection, architecture change,
  protocol decision, reversal of existing policy, etc.).
  DO NOT TRIGGER when: minor typo fixes in existing ADRs, code-only changes.
---

# ADR Authoring Guide

Record technical decisions in `docs/adr/NNNN-<slug>.md`.

## Purpose of ADRs

ADRs serve two purposes:

1. **Record**: Ensure the reasoning behind decisions remains understandable months or years later
2. **Clarify thinking and build consensus**: The act of writing surfaces differing viewpoints and creates an opportunity to discuss and resolve them

## When to Write an ADR

- When selecting or rejecting a library, engine, or framework
- When changing an architectural pattern (introducing decorators, switching HTTP clients, etc.)
- When choosing a database, storage system, or authentication approach
- When deciding on API design or testing strategy
- When making linter/formatter policy or license compatibility decisions
- When a future developer would ask "why was this done this way?"

## Format

Write in **inverted pyramid structure** — lead with the most important conclusion, then provide supporting details.

```markdown
# ADR-NNNN: Title

- **Status:** Proposed | Accepted | Superseded | Deprecated
- **Date:** YYYY-MM-DD
- **Decision makers:** @username
- **Confidence:** High | Medium | Low (confidence in this decision)

## Decision

**What was chosen.** Summarize the rationale in 1-2 sentences.

## Context

Why this decision was needed. Describe the problem and background.

## Candidates (if alternatives were considered)

### A. Option A
- Characteristics, pros, cons

### B. Option B
- Characteristics, pros, cons

## Evaluation (if empirical data exists)

Results from actual testing. Code examples, benchmarks, quality comparisons.
Show that the decision is data-driven.

## Consequences

What changes as a result of this decision.
- Positive impacts
- Trade-offs
- Future concerns

## Re-evaluation Triggers

This decision should be revisited if:
- (List specific context changes that would invalidate the assumptions behind this decision)
```

## Writing Principles

- **Inverted pyramid**: Lead with the conclusion. The decision should be clear without reading the details
- **Record the rationale**: Not just "X was rejected" but "X was tested and rejected because of Y"
- **Include empirical data**: Whenever possible, record benchmarks, quality comparisons, memory usage measurements
- **Document rejected options**: Prevents re-investigation when the same option is proposed later
- **State confidence explicitly**: Use the Confidence field to indicate whether this was a firm decision or a tentative one
- **Define re-evaluation triggers**: Specify what context changes would warrant revisiting this decision
- **Keep it concise**: Target one page. Link to supplementary materials rather than embedding them

## Status Lifecycle

| Status | Meaning |
|---|---|
| Proposed | Under review — awaiting discussion and approval |
| Accepted | Approved by the team and currently in effect |
| Superseded | Replaced by a newer ADR (link to the replacing ADR) |
| Deprecated | The subject has been retired and no longer applies |

## How to Create

1. Ensure the `docs/adr/` directory exists (create if missing)
2. Find the highest existing number and increment by 1 (zero-padded to 4 digits: 0001, 0002, ...)
3. Create `docs/adr/NNNN-<slug>.md` and fill in the template above
4. Initialize Status as `Proposed`

## Example

```markdown
# ADR-0003: Switch HTTP client from axios to ky

- **Status:** Accepted
- **Date:** 2026-03-15
- **Decision makers:** @naokami3
- **Confidence:** High

## Decision

**Replace axios with ky.** Bundle size is 1/10th, it is fetch-based and works in both Node.js and browsers, aligning with the project's lightweight dependency policy.

## Context

Frontend bundle size reduction was required, prompting a review of dependencies. axios is feature-rich but large (29kB min+gzip), and the project only uses basic GET/POST requests.

## Candidates

### A. ky
- Fetch-based wrapper. 2.5kB min+gzip. Built-in retry and timeout

### B. ofetch
- 3.1kB. From the Nuxt ecosystem. Capable but smaller community

### C. Native fetch
- No additional dependency. But retry and timeout must be implemented manually

## Consequences

- Bundle size reduced by ~27kB
- axios-specific features (interceptors) must be replaced with ky hooks
- Existing API client layer requires rewriting

## Re-evaluation Triggers

- ky maintenance stalls (no release for 6+ months)
- Server-side needs arise for axios-specific features (proxy support, etc.)
```
