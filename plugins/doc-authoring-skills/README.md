# doc-authoring-skills

Skills for authoring and reviewing technical documents. They follow the [Agent Skills open standard](https://agentskills.io), so they work with agents other than Claude Code.

## Skills

| Skill | Description |
|-------|-------------|
| `write-adr` | Create Architecture Decision Records with structured format |
| `write-agent-instructions` | Create or update agent instruction files (AGENTS.md as source of truth, CLAUDE.md as a bridge) |
| `write-project-docs` | Standards for project documentation (architecture.md, roadmap.md, etc.) |
| `write-html-docs` | Standards for human-facing HTML docs (diagram-rich overviews, rendered specs) generated from the md canon. **Optional** — skip when Markdown alone is enough |
| `review-docs` | Independent review that produces verified findings and derives the verdict mechanically. Bundles an exhaustive link checker |

## Design Philosophy

Inspired by the Generator-Evaluator pattern from [Anthropic's harness design research](https://www.anthropic.com/engineering/harness-design-long-running-apps), this plugin separates document **creation** (write-*) from **evaluation** (review-docs). The independent reviewer provides critical feedback that a generator agent cannot give to its own output.

`review-docs` is designed to resist plausible-sounding evaluation in two ways:

- **Findings first, verdict second**: it lists findings verified against the implementation, then computes the verdict mechanically from their severities — rather than picking a grade and backfilling justification
- **Unverified is not "fine"**: verification items it could not perform are reported explicitly as unverified

Each `write-*` skill includes verification by `review-docs` in its definition of done.

Documentation readers come in two tiers: **agents read the Markdown canon; humans read HTML when
it exists**. HTML docs are an optional deliverable — when you build them, follow `write-html-docs`
and treat them as generated output of the md canon (no hand-maintained duplicates; freshness is
machine-checked at the verification gate).

## Install

The skills use the standard `skills/<name>/SKILL.md` layout, so copying or symlinking them into a tool's skills directory is enough.

### Claude Code (as a plugin)

```bash
# From GitHub marketplace
/plugin marketplace add naokami3/ai_dotfiles
/plugin install doc-authoring-skills@ai-dotfiles

# Or test locally
claude --plugin-dir ./plugins/doc-authoring-skills
```

### Other agents (as skills)

| Tool | Location | Invocation |
|---|---|---|
| Claude Code | `.claude/skills/` or `~/.claude/skills/` | `/write-adr` |
| Codex CLI | `.agents/skills/` or `~/.agents/skills/` | `$write-adr` |
| GitHub Copilot | `.github/skills/` | Automatic |
| Cursor | `.cursor/skills/` | Automatic |
| Gemini CLI | `.gemini/skills/` | Automatic |

```bash
# Example: install into a repository for Codex CLI
mkdir -p .agents/skills
cp -R plugins/doc-authoring-skills/skills/* .agents/skills/
```

Every skill relies only on the standard frontmatter (`name` / `description`) and its body — no tool-specific frontmatter.

## Usage

When installed as a Claude Code plugin:

```
/doc-authoring-skills:write-adr
/doc-authoring-skills:write-agent-instructions
/doc-authoring-skills:write-project-docs
/doc-authoring-skills:write-html-docs
/doc-authoring-skills:review-docs
```

Each `description` carries its trigger conditions, so the skills are selected automatically during relevant work without being invoked explicitly.

## Japanese Version

A Japanese version is available as a separate plugin: `doc-authoring-skills-ja`

## Changelog

### 2.1.0

- New skill `write-html-docs`: standards for human-facing HTML docs (diagram-rich overviews,
  rendered detailed specs) generated from the Markdown canon. Defines the two-tier model
  (humans read HTML / agents read md), fail-closed generator requirements, a non-mutating
  freshness check for generated output, and diagram standards (diagrams assert facts; SVG
  accessibility; light/dark support; fragment injection for generated pages). **Building HTML
  is optional**; other skills only reference it
- `write-project-docs`: added a procedure for splitting oversized documents (line-range copy +
  coverage check + compatibility-anchor index), the measurement/canon/bridge three-layer
  separation pattern, the "What this document answers" opening block for long reference docs,
  and an optional HTML-docs row in the document-roles table
- `review-docs`: bundled `scripts/check-doc-links.py` for exhaustive link/anchor checking;
  added HTML-specific verification items (tag balance, light/dark rendering, fact-checking of
  diagram content, SVG accessibility) and guidance for the "canon is stale" case (use the
  implementation as the third point of comparison)
- Added `write-html-docs` to every skill's routing table

### 2.0.0

- **Breaking:** renamed `write-claude-md` to `write-agent-instructions`. AGENTS.md is now the primary file and CLAUDE.md is a bridge. (The rename also fixes the name: the Agent Skills spec disallows the reserved word `claude` in `name`.)
- Redesigned `review-docs` around findings-first evaluation with a mechanically computed verdict, and explicit handling of unverified items
- Added verification by `review-docs` to every `write-*` skill's definition of done
- Bundled `scripts/next-adr-number.sh` with `write-adr`, plus rules preventing fabricated decision content
- Added a routing table to every skill
- Added install instructions for agents other than Claude Code

## License

MIT
