---
name: write-agent-instructions
description: >
  Create or update coding agent instruction files (AGENTS.md, CLAUDE.md).
  Treats AGENTS.md as the source of truth and tool-specific files as bridges.
  TRIGGER when: creating or updating AGENTS.md, CLAUDE.md, or similar agent instruction files,
  or adding new entries to sections like mandatory rules, known pitfalls, or commands.
  DO NOT TRIGGER when: general docs under docs/ (use write-project-docs),
  ADRs (use write-adr), code-only changes.
---

# Agent Instruction File Authoring Guide

## Related Skills

| Target | Skill |
|---|---|
| AGENTS.md / CLAUDE.md and other agent instruction files | `write-agent-instructions` (this skill) |
| Technical decision records | `write-adr` |
| architecture.md / roadmap.md and other docs/ content | `write-project-docs` |
| Human-facing HTML docs (overview, detailed specs, diagrams) | `write-html-docs` |
| Verification after authoring | `review-docs` |

## Which File to Write

**Treat AGENTS.md as the project's source of truth.** Codex, Cursor, GitHub Copilot, Gemini CLI, Zed, Aider, and many other agents read this file directly.

Claude Code does not read AGENTS.md, so add one bridge:

```markdown
<!-- CLAUDE.md -->
@AGENTS.md

## Claude Code specifics

(Instructions that apply only to Claude Code. Drop this section entirely if there are none.)
```

If no Claude-specific additions are needed, a symlink works:

```bash
ln -s AGENTS.md CLAUDE.md
```

Creating a symlink on Windows requires Administrator privileges or Developer Mode, so choose the `@AGENTS.md` import if your team includes Windows environments.

**Never duplicate the same content into both files.** Duplicates drift when only one side gets updated, leaving agents to pick between contradicting instructions.

## Structure (in this order)

1. **Project overview** — 1-2 sentences. Include the tech stack
2. **Commands** — Build, test, lint, run commands. Prioritize what an agent cannot guess
3. **Coding conventions** — Only rules that differ from defaults. Don't duplicate linter/formatter rules
4. **Mandatory rules** — Constraints that cause breakage if violated. Use numbered lists
5. **Known pitfalls** — Non-obvious issues that aren't apparent from reading code alone
6. **Related documentation** — Links to docs/, CONTRIBUTING.md, etc.

## What to Include

- Project-specific information an agent cannot infer
- Rules that immediately cause bugs if violated
- Past pitfalls (DLL conflicts, license restrictions, etc.)
- Build/test/deploy commands
- Anything you have typed into chat as a correction more than once

## What NOT to Include

- Anything derivable from reading the code (file structure, function listings, dependency lists)
- Style rules enforced by linters/formatters
- General knowledge the model already has (standard framework usage, etc.)
- Long explanations or tutorials (split to docs/)
- Marketing copy or differentiators (belongs in README)
- Obvious practices ("write clean code")

## Size, and Where Overflow Goes

**Target under 200 lines.** Instruction files load in full at the start of every session, so length costs tokens permanently and reduces adherence to each individual instruction.

"If I remove this, will the agent make a mistake?" — If no, remove it.

When you can't fit under 200 lines, **relocate before you delete**:

| Overflowing content | Where it goes |
|---|---|
| Rules that apply only to certain directories or file types | Path-scoped rule files (Claude Code: `.claude/rules/*.md` with `paths` frontmatter; Cursor: `.cursor/rules/`; Copilot: `.github/copilot-instructions.md` and friends) |
| A section that grew into a procedure (multi-step work) | A skill (`SKILL.md`), loaded only when invoked |
| Content specific to one package in a monorepo | An AGENTS.md in that directory — agents use the one closest to the file being edited |
| Long reference material | docs/, linked from the instruction file |

**Note: `@path` imports do not reduce context.** Imported files are expanded and loaded at startup. If your goal is smaller context, move content to path-scoped rules or skills instead of importing it.

## Rule Patterns

```markdown
## Mandatory Rules

1. **What not to do** — Why (one line)
2. **What to do** — In which file/module
```

- **Add a one-line reason.** A rule with a reason generalizes to situations you didn't anticipate. A bare "MUST" stops being followed the moment conditions shift slightly
- Include specific file paths
- Use "must not" for prohibitions, "define in" for requirements
- Write at a specificity you can verify ("indent with 2 spaces", not "format properly")

## Pitfall Patterns

```markdown
## Known Pitfalls

- **Problem name**: Workaround. Details at [link]
```

- Bold the name for scannability
- Write the workaround in one line, link to ADR or docs for details

## Check for Contradictions

When multiple instruction files (root AGENTS.md, subdirectory AGENTS.md, rule files, personal user settings) contradict each other, the agent picks one arbitrarily. When updating, read every existing instruction file and check for conflicting statements.

## How to Create

1. Review all existing instruction files (AGENTS.md, CLAUDE.md, `.cursor/rules/`, `.github/copilot-instructions.md`, etc.)
2. Create or update AGENTS.md
3. Verify a Claude Code bridge exists (`@AGENTS.md` import or symlink); create it if missing
4. Check the file is under 200 lines; relocate per the table above if not
5. **Verify with the `review-docs` criteria.** Fix any must-fix findings before reporting completion
