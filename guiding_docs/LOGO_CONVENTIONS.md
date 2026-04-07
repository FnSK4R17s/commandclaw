# Logo Conventions

## Design System

All CommandClaw repos use the same logo pattern: **Microsoft Fluent 3D emoji** rendered as PNG at display size ~180px in READMEs.

### Base Mark

Every repo starts with the same two-emoji base — the **CommandClaw signature**:

| Emoji | Name | Role |
|-------|------|------|
| ⚓ | Anchor | Stability, control, "anchored to the vault" |
| 🦞 | Lobster | The Claw — core brand identity |

### Repo Suffix

Each repo appends a third (or third + fourth) emoji that represents its purpose:

| Repo | Suffix | Emoji | Reasoning |
|------|--------|-------|-----------|
| **commandclaw** | _(none)_ | ⚓🦞 | Core — no suffix needed |
| **commandclaw-vault** | House | ⚓🦞🏠 | Vault = home, where the agent lives |
| **commandclaw-mcp** | Lock | ⚓🦞🔐 | Security gateway, credential isolation |
| **commandclaw-skills** | Flexed Bicep | ⚓🦞💪 | Skills = capabilities, strength |
| **commandclaw-observe** | Telescope | ⚓🦞🔭 | Observability, looking into agent runs |
| **commandclaw-wiki** | Books | ⚓🦞📚 | The shared library — stacked pages of accumulated knowledge |
| **commandclaw-memory** | Brain | ⚓🦞🧠 | The recall machinery — distillation, retrieval, remembering |

## How to Generate

1. **Source font**: Microsoft Fluent Emoji 3D — [GitHub repo](https://github.com/microsoft/fluentui-emoji)
2. **Render**: Composite the individual emoji PNGs side-by-side at equal height
3. **Background**: Transparent PNG
4. **Output**: `logo.png` at repo root, constrained by **height** in the README

### Display sizes

| Emoji count | Height | Example |
|-------------|--------|---------|
| 2 (base only) | `height="97"` | commandclaw |
| 3 (base + suffix) | `height="88"` | vault, mcp, skills, observe |

### README usage

```html
<!-- 2-emoji (core) -->
<p align="center">
  <img src="logo.png" alt="Command Claw" height="97">
</p>

<!-- 3-emoji (sub-repos) -->
<p align="center">
  <img src="logo.png" alt="Command Claw Observe" height="88">
</p>
```

## Rules

- **Always include the base mark** (⚓🦞) — it's the brand anchor (pun intended)
- **One to two suffix emojis max** — keep it clean
- **Use Fluent 3D style only** — no Twemoji, no Apple emoji, no flat icons
- **Transparent background** — works on light and dark themes
- **No text in the logo** — the repo name goes in the `<h1>` below it
