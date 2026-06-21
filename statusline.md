---
name: claude-code-context-cost-statusline
description: Use this skill when the user wants a Claude Code status line (the bar at the bottom of the terminal) that shows context window usage and/or session cost/spend. Triggers include requests like "show my context window in the status bar", "track how much I'm spending in Claude Code", "set up a statusline with cost and context", or any mention of the Claude Code status line combined with usage/budget/token/context tracking. This skill produces a ready-to-install bash script plus the settings.json snippet needed to activate it. Not applicable to claude.ai (web/app chat) or generic API usage questions — Claude Code only.
---

# Claude Code Context & Cost Status Line

## What this skill does

Generates a **status line script** for Claude Code — a persistent bar at the
bottom of the terminal — that displays:

1. **Context window usage**: percentage used (and a visual progress bar)
2. **Session cost**: estimated USD spent so far in the current session

This is a Claude Code feature, not a generic "skill" capability. Claude Code
itself runs the script repeatedly (on every assistant turn, roughly debounced
to 300ms) and pipes session JSON into it via stdin. The script reads that
JSON and prints a formatted line to stdout, which becomes the status bar.

**This does not apply to claude.ai or the Claude app.** Those interfaces have
no statusline concept and no exposed token/cost metering. Confirm the user
means Claude Code before proceeding.

## Key facts to get right

- The script receives a **JSON blob on stdin**, not as arguments or env vars.
- Relevant fields:
  - `context_window.used_percentage` — 0-100, pre-calculated, input-tokens-only
    (excludes output tokens). May be `null` before the first API response or
    right after `/compact`.
  - `context_window.context_window_size` — usually 200000, or 1000000 for
    extended-context models.
  - `cost.total_cost_usd` — estimated session spend, **computed client-side**.
    This is an estimate and may not exactly match the actual bill.
  - `cost.total_duration_ms` / `cost.total_api_duration_ms` — wall-clock vs.
    API-wait time, useful for an optional duration readout.
  - `model.display_name` — nice to include for context.
- **`cost.total_cost_usd` reads as `0` (not absent) on Claude.ai Pro/Max
  subscription seats**, since token usage isn't billed per-call under a
  subscription. Only metered API-key billing produces a meaningful nonzero
  value. Tell the user this plainly rather than letting them think the
  script is broken — show $0.00 as "n/a (subscription plan)" if you can
  detect it's not worth showing, or just note it in the README.
- Always handle `null`/missing fields with fallbacks (`// 0` in `jq`, `or 0`
  in Python) — these fields are genuinely null early in a session.
- Keep the script **fast**. It reruns on every turn; slow scripts (e.g.
  unthrottled `git` calls) visibly lag the UI. Nothing here needs `git`, so
  this is naturally fast, but don't add slow operations later without
  caching.
- The first line of stdout becomes the status line. Multiple `echo`/`print`
  statements produce multiple status-line rows if the user wants both
  context and cost on separate lines.

## Workflow

1. **Confirm environment.** If not already clear, confirm the user is asking
   about Claude Code (not claude.ai web chat).
2. **Ask format preference** if not specified: single line vs. two lines,
   and whether they want a visual bar (▓░ blocks) or just a percentage
   number.
3. **Generate the script** (prefer bash + `jq`, since that's the documented
   default and most portable across macOS/Linux; offer Python/Node only if
   the user says they don't have `jq` or prefers those languages).
4. **Generate the settings.json snippet** to activate it.
5. **Give exact install steps**: save path, `chmod +x`, where to put the
   settings snippet, and how to test with mock stdin input before trusting
   it live.
6. **Caveat the cost number** if the user appears to be on a subscription
   plan rather than metered API billing — set expectations that it will
   show $0.00 / negligible.

## Reference script (bash + jq)

This is the canonical version this skill should adapt. It shows model name,
a 10-block context-usage bar with color thresholds, the percentage, and
session cost.

```bash
#!/bin/bash
# Read all of stdin (Claude Code pipes session JSON here)
input=$(cat)

MODEL=$(echo "$input" | jq -r '.model.display_name')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')

# Color thresholds: green <70%, yellow 70-89%, red 90%+
GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
if [ "$PCT" -ge 90 ]; then COLOR="$RED"
elif [ "$PCT" -ge 70 ]; then COLOR="$YELLOW"
else COLOR="$GREEN"; fi

# Build a 10-segment progress bar
BAR_WIDTH=10
FILLED=$((PCT * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
[ "$FILLED" -gt 0 ] && printf -v FILL "%${FILLED}s" && BAR="${FILL// /▓}"
[ "$EMPTY" -gt 0 ] && printf -v PAD "%${EMPTY}s" && BAR="${BAR}${PAD// /░}"

COST_FMT=$(printf '$%.2f' "$COST")

echo -e "[$MODEL] ${COLOR}${BAR}${RESET} ${PCT}% ctx | 💰 ${COST_FMT}"
```

## Install steps to give the user

1. Save the script to `~/.claude/statusline.sh`.
2. Make it executable: `chmod +x ~/.claude/statusline.sh`
3. Add to `~/.claude/settings.json` (create the file if it doesn't exist):
   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "~/.claude/statusline.sh",
       "padding": 0
     }
   }
   ```
4. Test it manually before trusting live output:
   ```bash
   echo '{"model":{"display_name":"Sonnet"},"context_window":{"used_percentage":42},"cost":{"total_cost_usd":1.23}}' | ~/.claude/statusline.sh
   ```
5. Restart Claude Code (or trigger any message) — settings reload
   automatically but the statusline only refreshes on the next interaction.
6. If nothing appears: check the script is executable, check it prints to
   stdout (not stderr), and confirm workspace trust has been accepted for
   the current directory (the statusline command requires the same trust
   gate as hooks).

## Alternative: let Claude Code generate it interactively

Mention this as a shortcut the user can take instead of hand-installing a
file: running `/statusline show context window percentage and session cost`
inside Claude Code asks Claude Code itself to write and wire up the script
automatically. This skill's manual script is useful when the user wants to
review/customize the exact logic themselves, or wants it included in a repo
or dotfiles setup rather than generated ad hoc.

## Common pitfalls to flag for the user

- Expecting "money spent" to reflect their actual bill: `total_cost_usd` is
  a client-side estimate and may diverge from the real invoice.
- Expecting a nonzero cost on a Pro/Max subscription seat — it won't show
  meaningful spend because subscription usage isn't metered per-token.
- Confusing `used_percentage` (input-tokens-only) with a full token count;
  if they want raw token counts instead of/alongside percentage, use
  `context_window.total_input_tokens` and `context_window.total_output_tokens`.
- Forgetting `chmod +x`, which causes the status line to silently stay
  blank.
