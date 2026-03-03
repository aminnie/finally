#!/usr/bin/env bash
set -euo pipefail

# Read-only validator for Cursor plugin repository structure/config.
# Usage:
#   bash scripts/validate-plugins-readonly.sh
# Optional:
#   ROOT=/path/to/repo bash scripts/validate-plugins-readonly.sh

fail() { echo "FAIL: $*" >&2; exit 1; }
warn() { echo "WARN: $*" >&2; }
ok() { echo "OK: $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

check_file() {
  local f="$1"
  [[ -f "$f" ]] || fail "Missing file: $f"
}

check_json() {
  local f="$1"
  jq empty "$f" >/dev/null 2>&1 || fail "Invalid JSON: $f"
}

need_cmd jq

has_description_key() {
  local f="$1"
  if command -v rg >/dev/null 2>&1; then
    rg -q '^description:' "$f"
  else
    grep -Eq '^description:' "$f"
  fi
}

if [[ -z "${ROOT:-}" ]]; then
  if git_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    ROOT="$git_root"
  else
    ROOT="$(pwd)"
  fi
fi

MKT="$ROOT/.cursor-plugin/marketplace.json"
check_file "$MKT"
check_json "$MKT"
ok "Marketplace manifest exists and is valid JSON: $MKT"

PLUGIN_SOURCES="$(jq -r '.plugins[]?.source // empty' "$MKT")"
[[ -n "$PLUGIN_SOURCES" ]] || fail "No plugins found in marketplace.json (.plugins[].source)"

while IFS= read -r src; do
  [[ -n "$src" ]] || continue
  rel="${src#./}"
  pdir="$ROOT/$rel"

  [[ -d "$pdir" ]] || fail "Plugin source directory does not exist: $src ($pdir)"
  ok "Plugin directory exists: $src"

  pjson="$pdir/.cursor-plugin/plugin.json"
  check_file "$pjson"
  check_json "$pjson"
  ok "plugin.json valid: $pjson"

  for field in name displayName version description license; do
    val="$(jq -r --arg f "$field" '.[$f] // empty' "$pjson")"
    [[ -n "$val" ]] || fail "Missing required field '$field' in $pjson"
  done
  aname="$(jq -r '.author.name // empty' "$pjson")"
  [[ -n "$aname" ]] || fail "Missing required field 'author.name' in $pjson"
  ok "Required plugin metadata fields present: $pjson"

  logo="$(jq -r '.logo // empty' "$pjson")"
  if [[ -n "$logo" ]]; then
    [[ -f "$pdir/$logo" ]] || fail "Logo referenced but not found: $pdir/$logo"
    ok "Logo reference resolves: $pdir/$logo"
  else
    warn "No logo field set in $pjson"
  fi

  if [[ -d "$pdir/skills" ]]; then
    while IFS= read -r skilldir; do
      [[ -f "$skilldir/SKILL.md" ]] || fail "Skill missing SKILL.md (singular): $skilldir"
      if [[ -f "$skilldir/SKILLS.md" ]]; then
        warn "Found non-standard SKILLS.md in $skilldir (expected SKILL.md)"
      fi
    done < <(find "$pdir/skills" -mindepth 1 -maxdepth 1 -type d | sort)
    ok "Skill file naming check passed under: $pdir/skills"
  fi

  if [[ -d "$pdir/rules" ]]; then
    while IFS= read -r rule; do
      first_line="$(sed -n '1p' "$rule")"
      [[ "$first_line" == "---" ]] || fail "Rule missing frontmatter start '---': $rule"
      has_description_key "$rule" || warn "Rule missing 'description:' in frontmatter/body: $rule"
    done < <(find "$pdir/rules" -type f -name '*.mdc' | sort)
    ok "Rule files frontmatter sanity check passed under: $pdir/rules"
  fi

  hjson="$pdir/hooks/hooks.json"
  if [[ -f "$hjson" ]]; then
    check_json "$hjson"
    ok "hooks.json valid: $hjson"

    while IFS= read -r cmd; do
      [[ -n "$cmd" ]] || continue
      c="${cmd#./}"
      target="$pdir/$c"
      [[ -f "$target" ]] || fail "Hook command target missing: $cmd ($target)"
      [[ -x "$target" ]] || fail "Hook command not executable: $target"
    done < <(jq -r '.. | objects | .command? // empty' "$hjson")
    ok "Hook command references resolve and are executable: $hjson"
  fi

  mcp="$pdir/mcp.json"
  if [[ -f "$mcp" ]]; then
    check_json "$mcp"
    ok "mcp.json valid: $mcp"

    servers_count="$(jq '.mcpServers | length // 0' "$mcp")"
    [[ "$servers_count" -gt 0 ]] || warn "mcp.json has no mcpServers entries: $mcp"

    while IFS= read -r key; do
      cmd="$(jq -r --arg k "$key" '.mcpServers[$k].command // empty' "$mcp")"
      [[ -n "$cmd" ]] || fail "mcpServers.$key missing 'command' in $mcp"
      has_args="$(jq -r --arg k "$key" '.mcpServers[$k] | has("args")' "$mcp")"
      [[ "$has_args" == "true" ]] || warn "mcpServers.$key has no 'args' in $mcp"
    done < <(jq -r '.mcpServers | keys[]?' "$mcp")
    ok "MCP server schema sanity check passed: $mcp"
  fi

  author_name="$(jq -r '.author.name // empty' "$pjson")"
  author_email="$(jq -r '.author.email // empty' "$pjson")"
  [[ "$author_name" != "Your Org" ]] || warn "Placeholder author name in $pjson"
  [[ "$author_email" != "plugins@example.com" ]] || warn "Placeholder author email in $pjson"
done <<< "$PLUGIN_SOURCES"

echo
ok "All required plugin checks completed."
