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

## Your Readers Include Agents

Documentation is read by coding agents as well as humans. Agents need the **shortest path to a concrete answer**, not an overview.

- Headings should identify their content (avoid "Miscellaneous" or "Notes")
- Every procedure needs a copy-pasteable command
- Give each fact exactly one home and link to it from elsewhere — the same fact in two places becomes indistinguishable once one copy goes stale
- If you publish a docs site, add an `llms.txt` (an H1, a 1-3 sentence summary, and a link list in Markdown) as a map to the primary pages

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
