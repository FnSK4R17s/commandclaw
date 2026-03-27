#!/usr/bin/env bash
set -euo pipefail

# migrate-from-openclaw.sh
# Converts an OpenClaw workspace into a CommandClaw vault.
#
# Usage:
#   ./scripts/migrate-from-openclaw.sh <openclaw-workspace> [commandclaw-vault]
#
# If <commandclaw-vault> is omitted, migration happens in-place.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[migrate]${NC} $1"; }
warn()  { echo -e "${YELLOW}[migrate]${NC} $1"; }
error() { echo -e "${RED}[migrate]${NC} $1" >&2; }

usage() {
    echo "Usage: $0 <openclaw-workspace> [commandclaw-vault]"
    echo ""
    echo "  <openclaw-workspace>  Path to an existing OpenClaw workspace"
    echo "  [commandclaw-vault]   Destination path (default: migrate in-place)"
    echo ""
    echo "What this script does:"
    echo "  1. Copies workspace to destination (if provided)"
    echo "  2. Renames .openclaw/ → .commandclaw/"
    echo "  3. Moves skills/ → .agents/skills/ (if at workspace root)"
    echo "  4. Adds .obsidian/ config from commandclaw-vault template"
    echo "  5. Creates missing directories (_templates, _fileClasses, Attachments)"
    echo "  6. Initializes as Git repo if not already one"
    echo "  7. Validates vault structure"
    exit 1
}

# --- Args ---

if [[ $# -lt 1 ]]; then
    usage
fi

SOURCE="$1"
DEST="${2:-$SOURCE}"

if [[ ! -d "$SOURCE" ]]; then
    error "Source directory does not exist: $SOURCE"
    exit 1
fi

# Check it looks like an OpenClaw workspace
if [[ ! -f "$SOURCE/AGENTS.md" ]]; then
    error "Not an OpenClaw workspace (missing AGENTS.md): $SOURCE"
    exit 1
fi

# --- Copy if destination differs ---

if [[ "$DEST" != "$SOURCE" ]]; then
    if [[ -d "$DEST" ]] && [[ "$(ls -A "$DEST" 2>/dev/null)" ]]; then
        error "Destination already exists and is not empty: $DEST"
        exit 1
    fi
    info "Copying workspace to $DEST"
    cp -r "$SOURCE" "$DEST"
fi

info "Migrating: $DEST"

# --- Step 1: Rename .openclaw/ → .commandclaw/ ---

if [[ -d "$DEST/.openclaw" ]]; then
    if [[ -d "$DEST/.commandclaw" ]]; then
        warn ".commandclaw/ already exists — skipping rename"
    else
        info "Renaming .openclaw/ → .commandclaw/"
        mv "$DEST/.openclaw" "$DEST/.commandclaw"
    fi
else
    info "No .openclaw/ found — creating .commandclaw/"
    mkdir -p "$DEST/.commandclaw"
fi

# Ensure workspace-state.json exists
if [[ ! -f "$DEST/.commandclaw/workspace-state.json" ]]; then
    echo '{"version": 1, "bootstrapSeededAt": null, "onboardingCompletedAt": null}' \
        > "$DEST/.commandclaw/workspace-state.json"
fi

# --- Step 2: Move skills/ → .agents/skills/ ---

if [[ -d "$DEST/skills" ]] && [[ ! -d "$DEST/.agents/skills" ]]; then
    info "Moving skills/ → .agents/skills/"
    mkdir -p "$DEST/.agents"
    mv "$DEST/skills" "$DEST/.agents/skills"
elif [[ -d "$DEST/skills" ]] && [[ -d "$DEST/.agents/skills" ]]; then
    warn "Both skills/ and .agents/skills/ exist — merging (skills/ takes precedence for conflicts)"
    mkdir -p "$DEST/.agents/skills"
    for skill_dir in "$DEST/skills"/*/; do
        skill_name="$(basename "$skill_dir")"
        if [[ -d "$DEST/.agents/skills/$skill_name" ]]; then
            warn "  Skipping $skill_name (already exists in .agents/skills/)"
        else
            mv "$skill_dir" "$DEST/.agents/skills/"
            info "  Moved $skill_name"
        fi
    done
    # Remove skills/ if empty
    rmdir "$DEST/skills" 2>/dev/null || warn "  skills/ not empty after merge — leaving in place"
elif [[ ! -d "$DEST/.agents/skills" ]]; then
    info "No skills found — creating empty .agents/skills/"
    mkdir -p "$DEST/.agents/skills"
fi

# --- Step 3: Create missing directories ---

for dir in _templates _fileClasses Attachments memory; do
    if [[ ! -d "$DEST/$dir" ]]; then
        info "Creating $dir/"
        mkdir -p "$DEST/$dir"
    fi
done

# Add .gitkeep to empty dirs
for dir in _fileClasses Attachments memory; do
    if [[ -z "$(ls -A "$DEST/$dir" 2>/dev/null)" ]]; then
        touch "$DEST/$dir/.gitkeep"
    fi
done

# Add DailyNote template if missing
if [[ ! -f "$DEST/_templates/DailyNote.md" ]]; then
    info "Creating _templates/DailyNote.md"
    cat > "$DEST/_templates/DailyNote.md" << 'TEMPLATE'
---
date: <% tp.date.now("YYYY-MM-DD") %>
created: <% tp.date.now("YYYY-MM-DD") %>
updated: <% tp.date.now("YYYY-MM-DD") %>
---

# <% tp.date.now("YYYY-MM-DD") %>

## Notes

## Decisions

## Follow-ups
TEMPLATE
fi

# --- Step 4: Add .obsidian/ config if missing ---

if [[ ! -d "$DEST/.obsidian" ]]; then
    info "Adding .obsidian/ configuration"
    mkdir -p "$DEST/.obsidian/plugins/obsidian-git"
    mkdir -p "$DEST/.obsidian/plugins/templater-obsidian"
    mkdir -p "$DEST/.obsidian/plugins/metadata-menu"
    mkdir -p "$DEST/.obsidian/plugins/obsidian-linter"

    cat > "$DEST/.obsidian/app.json" << 'JSON'
{
  "useMarkdownLinks": false,
  "newLinkFormat": "shortest",
  "attachmentFolderPath": "Attachments",
  "defaultViewMode": "source",
  "showFrontmatter": true,
  "alwaysUpdateLinks": true
}
JSON

    cat > "$DEST/.obsidian/appearance.json" << 'JSON'
{"theme": "obsidian"}
JSON

    cat > "$DEST/.obsidian/community-plugins.json" << 'JSON'
["obsidian-git", "templater-obsidian", "metadata-menu", "obsidian-linter"]
JSON

    cat > "$DEST/.obsidian/core-plugins.json" << 'JSON'
{
  "file-explorer": true, "global-search": true, "switcher": true,
  "graph": true, "backlink": true, "outgoing-link": true, "tag-pane": true,
  "properties": true, "page-preview": true, "daily-notes": true,
  "templates": true, "note-composer": true, "command-palette": true,
  "editor-status": true, "bookmarks": true, "outline": true,
  "word-count": true, "file-recovery": true,
  "canvas": false, "slash-command": false, "footnotes": false,
  "markdown-importer": false, "zk-prefixer": false, "random-note": false,
  "slides": false, "audio-recorder": false, "workspaces": false,
  "publish": false, "sync": false, "webviewer": false
}
JSON

    echo '{}' > "$DEST/.obsidian/graph.json"
    echo '{}' > "$DEST/.obsidian/backlink.json"

    cat > "$DEST/.obsidian/plugins/obsidian-git/data.json" << 'JSON'
{
  "commitMessage": "vault backup: {{date}}",
  "autoCommitMessage": "vault backup: {{date}}",
  "commitDateFormat": "YYYY-MM-DD HH:mm:ss",
  "autoPush": true, "autoSaveInterval": 5, "autoPullInterval": 10,
  "autoPullOnBoot": true, "pullBeforePush": true, "syncMethod": "merge",
  "disablePush": false, "disablePopups": false,
  "showStatusBar": true, "showBranchStatusBar": true,
  "listChangedFilesInMessageBody": false,
  "customMessageOnAutoBackup": false,
  "autoBackupAfterFileChange": false, "diffStyle": "split"
}
JSON

    cat > "$DEST/.obsidian/plugins/templater-obsidian/data.json" << 'JSON'
{
  "command_timeout": 5, "templates_folder": "_templates",
  "templates_pairs": [["", ""]], "trigger_on_file_creation": true,
  "auto_jump_to_cursor": true, "enable_system_commands": false,
  "shell_path": "", "user_scripts_folder": "",
  "enable_folder_templates": true,
  "folder_templates": [{"folder": "memory", "template": "_templates/DailyNote.md"}],
  "enable_file_templates": false, "file_templates": [],
  "syntax_highlighting": true, "syntax_highlighting_mobile": false,
  "enabled_templates_hotkeys": [""], "startup_templates": [""]
}
JSON

    cat > "$DEST/.obsidian/plugins/metadata-menu/data.json" << 'JSON'
{
  "presetFields": [], "fileClassQueries": [],
  "displayFieldsInContextMenu": true, "globallyIgnoredFields": [],
  "classFilesPath": "_fileClasses", "isAutosuggestEnabled": true,
  "fileClassAlias": "fileClass", "settingsVersion": "5.0",
  "firstDayOfWeek": 1, "enableLinks": true, "enableTabHeader": true,
  "enableEditor": true, "enableBacklinks": true, "enableStarred": true,
  "enableFileExplorer": true, "enableSearch": true, "enableProperties": true,
  "tableViewMaxRecords": 20, "frontmatterListDisplay": "asArray",
  "fileClassExcludedFolders": [], "showIndexingStatusInStatusBar": true,
  "fileIndexingExcludedFolders": [],
  "fileIndexingExcludedExtensions": [".excalidraw.md"],
  "fileIndexingExcludedRegex": [], "frontmatterOnly": false,
  "showFileClassSelectInModal": true, "chooseFileClassAtFileCreation": false
}
JSON

    cat > "$DEST/.obsidian/plugins/obsidian-linter/data.json" << 'JSON'
{
  "ruleConfigs": {
    "yaml-key-sort": {
      "enabled": true,
      "yamlKeyPrioritySortOrder": "name\ndescription\ntype\ndate\ntags\ncreated\nupdated",
      "priorityKeysAtStartOfYaml": true,
      "yamlSortOrderForOtherKeys": "Ascending Alphabetical"
    },
    "yaml-timestamp": {
      "enabled": true, "dateCreated": true, "dateCreatedKey": "created",
      "dateModified": true, "dateModifiedKey": "updated", "format": "YYYY-MM-DD"
    },
    "format-tags-in-yaml": {"enabled": true}
  },
  "lintOnSave": true, "displayChanged": true,
  "foldersToIgnore": [".obsidian", ".commandclaw", ".agents"]
}
JSON

else
    warn ".obsidian/ already exists — skipping"
fi

# --- Step 5: Remove OpenClaw-specific artifacts ---

# Clean up files that don't belong in CommandClaw
for file in skills-lock.json; do
    if [[ -f "$DEST/$file" ]]; then
        info "Removing OpenClaw artifact: $file"
        rm "$DEST/$file"
    fi
done

# Remove .tools/ (OpenClaw-specific)
if [[ -d "$DEST/.tools" ]]; then
    info "Removing OpenClaw artifact: .tools/"
    rm -rf "$DEST/.tools"
fi

# --- Step 6: Initialize Git if needed ---

if [[ ! -d "$DEST/.git" ]]; then
    info "Initializing Git repository"
    git -C "$DEST" init -b main
    git -C "$DEST" add -A
    git -C "$DEST" commit -m "Migrated from OpenClaw workspace"
else
    info "Git repository already initialized"
fi

# --- Step 7: Validate ---

ERRORS=0

for file in AGENTS.md SOUL.md IDENTITY.md USER.md TOOLS.md; do
    if [[ ! -f "$DEST/$file" ]]; then
        error "Missing required file: $file"
        ERRORS=$((ERRORS + 1))
    fi
done

for dir in memory .commandclaw .agents/skills; do
    if [[ ! -d "$DEST/$dir" ]]; then
        error "Missing required directory: $dir/"
        ERRORS=$((ERRORS + 1))
    fi
done

if [[ -d "$DEST/.openclaw" ]]; then
    error ".openclaw/ still exists — rename failed"
    ERRORS=$((ERRORS + 1))
fi

echo ""
if [[ $ERRORS -gt 0 ]]; then
    error "Migration completed with $ERRORS error(s). Review above."
    exit 1
else
    info "Migration complete! ✅"
    echo ""
    echo "  Vault: $DEST"
    echo ""
    echo "  Next steps:"
    echo "    1. cd $DEST"
    echo "    2. npx skills add FnSK4R17s/commandclaw-skills"
    echo "    3. Open in Obsidian"
    echo ""
fi
