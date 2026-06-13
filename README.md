# Digits — connect Claude to Apple Numbers

![Digits demo — asking Claude to fill in a budget, watching the Numbers sheet populate live]

Talk to your spreadsheets. Digits is a **zero-dependency** MCP server that
lets Claude read and edit live Apple Numbers documents — cells, formulas,
rows, sheets — packaged as a Claude plugin with a bundled **budget-review**
skill.

No pip. No uv. No node. One Python file, standard library only. If your Mac
can run `python3`, you can install Digits in under a minute.

## What it feels like

> **You:** review my budget
> **Claude:** *reads your open Budget spreadsheet* — "Rent, utilities and
> insurance are filled in. Groceries, subscriptions and gym are blank, and
> your Total row is a typed number, not a formula. Want me to fix that?"
> **You:** groceries 400, gym 45, subs 60
> **Claude:** *writes all amounts + live `=SUM()` totals in one batch* —
> undoable with Cmd+Z, saved only when you say so.

## Why AppleScript instead of parsing .numbers files?

- **Live documents.** Edits appear instantly in the open window, are
  undoable with Cmd+Z, and nothing touches disk until you save.
- **Real formula results.** Reading a formula cell returns what Numbers
  actually computed — no reimplementing the formula engine.
- **Zero file-format risk.** No reverse-engineered parser to break when
  Apple changes the format.

The trade-off: macOS only, and Numbers must be installed. (That's the
point.)

## Tools

| Tool | What it does |
|---|---|
| `numbers_list_documents` | Names of open spreadsheets |
| `numbers_open_document` | Open a `.numbers` file by path |
| `numbers_list_sheets` | Sheet tabs in a document |
| `numbers_list_tables` | Tables on a sheet, with dimensions |
| `numbers_read_table` | Full table as a 2D grid, optionally with formulas |
| `numbers_set_cells` | Batch-write values and formulas (`"=SUM(F4:F14)"`) |
| `numbers_add_row` / `numbers_add_column` | Append rows/columns |
| `numbers_save_document` | Save to disk (edits are in-memory until then) |
| `numbers_create_document` | New blank spreadsheet from nothing |
| `numbers_import_csv` | CSV file or raw text → new Numbers document, parsed natively |
| `numbers_export_csv` | Any table → CSV text or file |
| `numbers_health_check` | Diagnose setup: Numbers present, automation permission, etc. |

All tools default to the front document / active sheet / first table, so
they work on whatever is on screen without ceremony.

## Install

**As a Claude plugin (Cowork / Claude Code):** install the `.plugin` file, or
add this repo as a marketplace and install from there:

```
/plugin marketplace add apeabody007/digits
/plugin install digits@digits
```

**As a bare MCP server** (Claude Desktop or any MCP client):

```json
{
  "mcpServers": {
    "digits": {
      "command": "python3",
      "args": ["/path/to/server/digits_server.py"]
    }
  }
}
```

First run only: macOS will ask you to allow your MCP client to control
Numbers — approve it (System Settings → Privacy & Security → Automation if
you missed the prompt). If `python3` says "command line developer tools",
run `xcode-select --install` once.

## Bundled skill: budget-review

Say "review my budget" and Claude finds the budget document, reads the
current month's sheet, flags missing amounts and hard-coded totals, collects
numbers conversationally, writes everything back in one batch with live
formulas, and asks before saving.

## Implementation notes

- **Zero dependencies**: `server/digits_server.py` implements MCP's JSON-RPC
  stdio protocol directly in ~450 lines of stdlib Python. Nothing to
  install, nothing to break.
- Table serialization uses ASCII unit/record separators (0x1F/0x1E) between
  cells/rows, so commas, quotes, and newlines inside cells can never corrupt
  parsing.
- Strings starting with `=` are entered as formulas — same convention as
  typing into Numbers.
- Errors are mapped to actionable messages (automation permission missing,
  bad sheet/table name, modal dialog blocking AppleScript).

## Limitations / roadmap

- No cell formatting (currency styles, colors) — Numbers' AppleScript
  dictionary barely exposes styling. Planned via UI scripting.
- Rows/columns append at the end only (insert-at-index not yet implemented).
- No chart creation.
- Tested on Numbers 15.x / macOS 15.

## License

MIT
