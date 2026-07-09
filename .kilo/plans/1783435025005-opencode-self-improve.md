# Self-Improve: Update opencode to latest version

## Completed task
User asked to update the `opencode` CLI to the latest version. Discovered it is
distributed via npm as the package **`opencode-ai`** (the `opencode` name is a
thin wrapper stub), updated with `npm update -g opencode-ai`, and hit npm
`allow-scripts` gating on its postinstall.

## Audit (Phase 0)
- Repo `AGENTS.md` and global `~/.agents/AGENTS.md` both present and declare `.agents/`.
- Existing global skill `npm-native-binary-not-installed` already covers:
  - npm `allow-scripts` blocks postinstall → binary stays a stub
  - global `npm approve-scripts` fails (ENOMATCH / EGLOBAL) → use `--force` or manual copy
  - AGENTS.md gotcha already links to it.
- Global memory has a `lessons/` category with an `INDEX.md`.

## Lesson extraction & classification

| # | Lesson | Action | Type | Scope | Target | Reason |
|---|--------|--------|------|-------|--------|--------|
| 1 | OpenCode CLI is published on npm as `opencode-ai`; `opencode` is a wrapper stub. Update: `npm view opencode-ai version` → `npm update -g opencode-ai`. npm `allow-scripts` may gate postinstall; verify with `opencode --version`, and for global installs use `npm install -g opencode-ai --force` / `npm rebuild opencode-ai` (not `npm approve-scripts`). | create | memory (lesson) | global | `~/.agents/memory/lessons/opencode-npm-package.md` + `INDEX.md` row | Not documented anywhere; recurring env fact needed next time opencode is updated. |
| 2 | npm `allow-scripts` gates global package postinstall; `npm approve-scripts` fails for globals. | skip | — | — | — | Already documented in skill `npm-native-binary-not-installed` + AGENTS.md gotcha. |

## Landing actions (Phase 6)
1. Create `~/.agents/memory/lessons/opencode-npm-package.md` with frontmatter
   (`id`, `category: lessons`, `type: lesson`, `tags`, `confidence: high`,
   `status: active`, `created`/`updated: 2026-07-07`) and body per draft below.
2. Add one row to `~/.agents/memory/INDEX.md` under **Active Memories**.
3. No AGENTS.md change needed (memory is soft/evolving, not a non-obvious rule).

## Memory file draft
```
---
id: opencode-npm-package
category: lessons
type: lesson
tags:
  - opencode
  - npm
  - cli
  - update
confidence: high
status: active
created: 2026-07-07
updated: 2026-07-07
---
# OpenCode is published on npm as `opencode-ai`

OpenCode CLI is distributed via npm as the package **`opencode-ai`**. The
`opencode` package name (what the `opencode` command resolves to) is a thin
wrapper/stub around it.

- Check latest version: `npm view opencode-ai version`
- Update: `npm update -g opencode-ai`
- Do not update the `opencode` wrapper directly; npm manages it.

Gotcha: npm `allow-scripts` may gate `opencode-ai`'s postinstall (fetches the
native binary). After `npm update`, verify with `opencode --version`. If the
binary is missing/stubbed, follow the diagnostic skill
`npm-native-binary-not-installed` — for global installs `npm approve-scripts`
fails (ENOMATCH/EGLOBAL), so use `npm install -g opencode-ai --force` or
`npm rebuild opencode-ai` instead.
```

## Validation
- `opencode --version` still reports `1.17.14` (already verified during task).
- After landing, `grep -ril "opencode-ai"` across `~/.agents/memory` returns the
  new file, and `INDEX.md` contains the new row.

## Notes
- Nothing to commit at repo level (all changes are global, home-local).
