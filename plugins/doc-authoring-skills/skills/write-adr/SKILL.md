---
name: write-adr
description: Create Architecture Decision Records (ADRs) to document technical decisions with context, alternatives, and consequences.
---

# ADR Authoring Guide

Record technical decisions in `docs/adr/NNNN-<slug>.md`.

## When to Write an ADR

- When selecting or rejecting a library, engine, or framework
- When changing an architectural pattern (introducing decorators, switching HTTP clients, etc.)
- When deciding how to handle linter warnings
- When a future developer would ask "why was this done this way?"

## Format

```markdown
# ADR-NNNN: Title

- **Status:** Accepted | Superseded | Deprecated
- **Date:** YYYY-MM-DD
- **Decision makers:** @username

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

## Decision

**What was chosen.** Brief rationale.

## Consequences

What changes as a result of this decision.
- Positive impacts
- Trade-offs
- Future concerns
```

## Writing Principles

- **Record the rationale**: Not just "X was rejected" but "X was tested and rejected because of Y"
- **Include empirical data**: Whenever possible, record benchmarks, quality comparisons, memory usage measurements
- **Document rejected options**: Prevents re-investigation when the same option is proposed later
- **Keep it short**: 1-2 pages. Defer details to code or commit messages

## Numbering

Use the highest existing number in `docs/adr/` + 1. Zero-padded to 4 digits (0001, 0002, ...).

## Common ADR Topics

- Library/framework selection
- Database/storage choices
- API design decisions
- Authentication/authorization approaches
- Testing strategy changes
- Performance optimization decisions
- License compatibility decisions
- Linter/formatter warning handling policies
