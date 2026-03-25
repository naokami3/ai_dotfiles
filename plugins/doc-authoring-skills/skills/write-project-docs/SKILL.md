---
name: write-project-docs
description: Standards for creating and updating project documentation (architecture.md, roadmap.md, security-design.md, etc.).
---

# Project Documentation Guide

## Document Roles

| File | Audience | Content | Update Frequency |
|------|----------|---------|-----------------|
| CLAUDE.md | Claude Code | Commands, rules, pitfalls | On feature addition |
| README.md | Everyone | Project overview, setup | On release |
| CONTRIBUTING.md | Contributors | Dev environment, conventions, PR process | On dev environment change |
| docs/architecture.md | Developers | Directory structure, design principles, protocols | On architecture change |
| docs/roadmap.md | Everyone | Phases, TODOs, completion status | On feature completion |
| docs/security-design.md | Developers/Auditors | Threat model, API key management, endpoints | On security design change |
| docs/adr/ | Developers | Technical decision records | On significant decisions |

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
