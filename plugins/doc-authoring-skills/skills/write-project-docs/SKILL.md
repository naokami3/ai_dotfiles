---
name: write-project-docs
description: >
  Standards for creating and updating project documentation (architecture.md, roadmap.md, security-design.md, etc.).
  TRIGGER when: creating or updating project docs under docs/ such as architecture.md,
  roadmap.md, security-design.md, etc.
  DO NOT TRIGGER when: ADRs (use write-adr), AGENTS.md / CLAUDE.md (use write-agent-instructions),
  code-only changes.
---

# Project Documentation Guide

## Related Skills

| Target | Skill |
|---|---|
| architecture.md / roadmap.md and other docs/ content | `write-project-docs` (this skill) |
| Human-facing HTML docs (overview, detailed specs, diagrams) | `write-html-docs` |
| Technical decision records | `write-adr` |
| AGENTS.md / CLAUDE.md | `write-agent-instructions` |
| Verification after authoring | `review-docs` |

## Document Roles

| File | Audience | Content | Update Frequency |
|------|----------|---------|-----------------|
| AGENTS.md (+ CLAUDE.md bridge) | Coding agents | Commands, rules, pitfalls | On feature addition |
| README.md | Everyone | Project overview, setup | On release |
| CONTRIBUTING.md | Contributors | Dev environment, conventions, PR process | On dev environment change |
| docs/architecture.md | Developers | Directory structure, design principles, protocols | On architecture change |
| docs/roadmap.md | Everyone | Phases, TODOs, completion status | On feature completion |
| docs/security-design.md | Developers/Auditors | Threat model, API key management, endpoints | On security design change |
| docs/adr/ | Developers | Technical decision records | On significant decisions |
| llms.txt (if you publish a docs site) | Agents | A map to the primary documentation pages | On structural change |
| HTML docs under docs/ (**optional**) | Humans | Diagram-rich overview and HTML rendering of detailed specs, generated from the md canon. Follow `write-html-docs` if you build them | When the md canon changes (regenerate) |

## Your Readers Include Agents

Documentation is read by coding agents as well as humans. Agents need the **shortest path to a concrete answer**, not an overview.

- Headings should identify their content (avoid "Miscellaneous" or "Notes")
- Every procedure needs a copy-pasteable command
- Give each fact exactly one home and link to it from elsewhere — the same fact in two places becomes indistinguishable once one copy goes stale
- If you publish a docs site, add an `llms.txt` (an H1, a 1-3 sentence summary, and a link list in Markdown) as a map to the primary pages
- Open long reference documents (specs, protocols) with a "**What this document answers**" block
  (at most 5 bullets, listing only the questions the document can answer — no duplicated facts).
  It lets agents decide quickly whether to read on

## How to Write Each Document

### architecture.md

1. Describe directory structure in tree format (one-line comment per file)
2. State design principles as bullet points
3. Include code examples for protocols/interfaces
4. Document known constraints (DLL conflicts, licenses, etc.) in a dedicated section
5. **Update immediately when implementation diverges** — outdated documentation is harmful

### roadmap.md

1. Track progress with checkboxes per phase
2. Mark completed phases with a checkmark
3. Add notes to each item (technologies used, ADR references, etc.)
4. Separate undecided items under "Future Considerations"

### security-design.md

1. State the threat model upfront (what you protect and what you don't)
2. Describe risk levels honestly (avoid overclaiming safety)
3. Organize API keys, endpoints, and encryption methods in tables
4. **Transparent security** — document limitations too

### CONTRIBUTING.md

1. Setup instructions that work with copy-paste
2. OS-specific steps (Windows OCR language packs, etc.) in separate sections
3. Specify tool names and commands for coding conventions
4. PR process and review criteria

## Shared Principles

- **DRY**: Don't duplicate information across documents. Use links
- **Stay in sync**: Update documentation when code changes. Include in the same commit
- **Know your reader**: Consider "who" reads this and "when"
- **Be specific**: Not "configure appropriately" but "`keyring.set_password("grabtl", engine, key)` to store"
- **Don't write guesses**: never assert behavior or numbers you haven't confirmed. Write "unconfirmed" when you haven't

## Splitting a Document That Has Grown Too Large

A document that has lost skimmability past several hundred lines should be split into topic files
plus an index. A split is a **move of content, not a rewrite**. Prevent loss and broken references
mechanically:

1. **Split by mechanical line-range copy** (don't rewrite while splitting). Build a **coverage
   check** into the split script: every body line must land in exactly one destination file
2. Don't delete the original file — replace it with an **index that keeps the old headings as
   compatibility anchors** (so existing `file.md#anchor` links, including external ones, keep
   working; put a "moved to …" link under each old heading)
3. Grep the whole repository for prose references to section names ("the X section" style) and
   update them to deep links. Apply bulk replacements **while verifying the expected occurrence
   count** of each replacement
4. Fix relative links inside the split files (`../` depth changes) and cross-references between them
5. Finish with an exhaustive link/anchor check (`scripts/check-doc-links.py` from `review-docs`)

## Three-Layer Separation: Measurements, Canon, Bridge Map

For projects that depend on external system behavior, keeping these three layers in separate files
makes update responsibility clear.

| Layer | Content | Updated when |
|---|---|---|
| Measurement log | Raw data, repro steps, test environment, explicit "unconfirmed" markers | You measure something |
| Canon (spec) | Contracts for the countermeasures, invariants, exit codes | You change the implementation |
| Bridge map | "Observed behavior → countermeasure" table. **Holds no primary facts; links to both sides** | Either side changes |

The moment the bridge map starts stating facts, you have a third primary source and a breeding
ground for drift. Keep it to links and one-line summaries.

## Updating Multiple Documents

One change often ripples across several documents. Build a checklist before you start and track it.

```
To update:
- [ ] docs/architecture.md — reflect the directory structure change
- [ ] README.md — reflect the changed setup command
- [ ] docs/roadmap.md — check off Phase 2
- [ ] Verify cross-links resolve
- [ ] Verify with review-docs
```

The easiest thing to miss is **whatever links to the document you changed**. Search the repository for the file name you touched and check the referring side too.

## Definition of Done

After authoring or updating, **verify with the `review-docs` criteria.** Fix any must-fix findings before reporting completion.
