#!/usr/bin/env bash
# Push an archived meeting's notes into Tana, from the [hooks] on_archive_change hook.
#
# A shell hook cannot call an MCP tool itself, so this delegates to headless
# `claude -p` -- the same Claude Code CLI the notes step already requires, which
# does have MCP access. Nothing here talks to Tana's cloud API: no token, no
# secret, no network beyond localhost. The writes go through the tana-local MCP
# server, which lives inside the Tana Outliner desktop app, so that app must be
# running. When it is not, this exits quietly: the hook is best-effort by design
# and a missed push must never look like a failed archive.
#
# Wire it up in ${XDG_CONFIG_HOME:-~/.config}/ddv-meeting-notes/config.toml:
#
#   [hooks]
#   on_archive_change = "/path/to/ddv-meeting-notes/contrib/tana-push.sh"
#
# Optional environment, set inline in that same command string, e.g.
# on_archive_change = "TANA_SUPERTAG=meetingNote /path/to/contrib/tana-push.sh":
#
#   TANA_WORKSPACE_ID  target workspace id (NOT the workspace's home-node id).
#                      In practice you want to set this: most Tana accounts have
#                      several workspaces, and with more than one loaded the push
#                      refuses to guess and changes nothing. List them from any
#                      Claude Code session with the tana-local list_workspaces tool.
#   TANA_SUPERTAG      supertag applied to the meeting node, by name ("meetingNote")
#                      or by id ("^AbCdEf12"). Omit for an untagged node.
#   TANA_LOCAL_URL     tana-local MCP endpoint. Default http://127.0.0.1:8262/mcp.
#
# Requires the tana-local MCP server to be configured in your Claude Code setup
# (that is what makes the mcp__tana-local__* tools exist at all).
set -uo pipefail

notes="${MEETING_NOTES_PATH:-}"
name="${MEETING_NAME:-meeting}"
tana_url="${TANA_LOCAL_URL:-http://127.0.0.1:8262/mcp}"
workspace="${TANA_WORKSPACE_ID:-}"
supertag="${TANA_SUPERTAG:-}"

if [[ -z "$notes" || ! -f "$notes" ]]; then
    echo "tana-push: no notes file at '${notes:-<unset>}' (MEETING_NOTES_PATH)" >&2
    exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
    echo "tana-push: claude not found on PATH" >&2
    exit 1
fi

# Preflight, so a closed Tana desktop costs a 2 s connection attempt instead of a
# full model round-trip that then has no tools to call. Judge by curl's exit
# status, not by the HTTP status: the endpoint answers 401 to an unauthenticated
# plain GET, which still proves the app is up and listening.
if command -v curl >/dev/null 2>&1; then
    if ! curl -s -o /dev/null -m 2 "$tana_url"; then
        echo "tana-push: no tana-local at $tana_url (Tana Outliner not running?) -- skipped" >&2
        exit 0
    fi
fi

today="$(date +%Y-%m-%d)"

workspace_rule="Use workspace id \"$workspace\"."
if [[ -z "$workspace" ]]; then
    workspace_rule="No workspace id was configured: call list_workspaces and use the only workspace it returns. If it returns more than one, stop and print which ids are available, changing nothing."
fi

supertag_rule="Do not apply any supertag."
if [[ -n "$supertag" ]]; then
    supertag_rule="Apply the supertag \"$supertag\" to the meeting node, in the paste itself (\"#tagname\", or \"#[[^id]]\" when the value starts with ^)."
fi

# `read -d ''` always ends on EOF, i.e. returns non-zero even though it read the
# whole heredoc; the `|| true` keeps that from reading as a failure.
read -r -d '' prompt <<PROMPT || true
You are pushing one already-written set of meeting notes into Tana. The notes are on stdin, in Markdown. Today is $today.

Do exactly this, and nothing else:

1. Call get_or_create_calendar_node with date "$today" and granularity "day" to get today's calendar node. $workspace_rule
2. Call import_tana_paste once, with that calendar node as parentNodeId, to create a single node titled "$name" with the notes below it.

Rules for the paste:
- Reproduce the notes. Do not summarize, rewrite, translate, add or drop anything: this content was already generated and reviewed, you are only moving it.
- Each Markdown "## Heading" becomes one child bullet of the meeting node, keeping its own bullets as its children. Drop the top-level "# " title line; the meeting node is the title.
- $supertag_rule
- Set no fields. In particular, never write an option field as plain text, and never guess a value for one: leave every field unset for the user to fill in Tana.
- Create nothing else: no tasks, no extra nodes, no other parents.

Then reply with one line: the created node's id, or what went wrong. Do not ask for clarification or confirmation. If a step is ambiguous, pick the most conservative interpretation and execute it. Complete all steps sequentially and terminate.
PROMPT

claude -p "$prompt" \
    --allowedTools "mcp__tana-local__get_or_create_calendar_node,mcp__tana-local__import_tana_paste,mcp__tana-local__list_workspaces" \
    <"$notes"
