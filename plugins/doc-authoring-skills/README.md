# doc-authoring-skills

Skills for authoring and reviewing technical documents. They follow the [Agent Skills open standard](https://agentskills.io), so they work with agents other than Claude Code.

## Skills

| Skill | Description |
|-------|-------------|
| `write-adr` | Create Architecture Decision Records with structured format |
| `write-agent-instructions` | Create or update agent instruction files (AGENTS.md as source of truth, CLAUDE.md as a bridge) |
| `write-project-docs` | Standards for project documentation (architecture.md, roadmap.md, etc.) |
| `review-docs` | Independent review that produces verified findings and derives the verdict mechanically |

## Design Philosophy

Inspired by the Generator-Evaluator pattern from [Anthropic's harness design research](https://www.anthropic.com/engineering/harness-design-long-running-apps), this plugin separates document **creation** (write-*) from **evaluation** (review-docs). The independent reviewer provides critical feedback that a generator agent cannot give to its own output.

`review-docs` is designed to resist plausible-sounding evaluation in two ways:

- **Findings first, verdict second**: it lists findings verified against the implementation, then computes the verdict mechanically from their severities — rather than picking a grade and backfilling justification
- **Unverified is not "fine"**: verification items it could not perform are reported explicitly as unverified

Each `write-*` skill includes verification by `review-docs` in its definition of done.

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
/doc-authoring-skills:review-docs
```

Each `description` carries its trigger conditions, so the skills are selected automatically during relevant work without being invoked explicitly.

## Japanese Version

A Japanese version is available as a separate plugin: `doc-authoring-skills-ja`

## Changelog

### 2.0.0

- **Breaking:** renamed `write-claude-md` to `write-agent-instructions`. AGENTS.md is now the primary file and CLAUDE.md is a bridge. (The rename also fixes the name: the Agent Skills spec disallows the reserved word `claude` in `name`.)
- Redesigned `review-docs` around findings-first evaluation with a mechanically computed verdict, and explicit handling of unverified items
- Added verification by `review-docs` to every `write-*` skill's definition of done
- Bundled `scripts/next-adr-number.sh` with `write-adr`, plus rules preventing fabricated decision content
- Added a routing table to every skill
- Added install instructions for agents other than Claude Code

## License

MIT
