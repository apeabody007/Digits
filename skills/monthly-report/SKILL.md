---
name: monthly-report
description: Turn raw rows in an Apple Numbers spreadsheet into a clean monthly summary — totals, category breakdowns, month-over-month deltas — and optionally export it as PDF or Excel. Use when the user says "summarize this month", "build a monthly report", "roll this up", "give me the totals by category", "compare to last month", or "export the report".
---

# Monthly Report (Apple Numbers)

Build a readable monthly summary on top of a live Numbers spreadsheet using
the Digits MCP tools (`numbers_*`). The source data is whatever rows the user
already has (transactions, sales, hours, etc.); your job is to aggregate it
faithfully — never invent numbers, always read before writing.

## Workflow

1. **Locate the data.** Call `numbers_list_documents`. If empty, ask for the
   file path and `numbers_open_document`. Use `numbers_list_sheets` and
   `numbers_list_tables` to find the source table and confirm its dimensions.

2. **Read the source.** Call `numbers_read_table` with `include_formulas: true`
   so you don't mistake a formula cell for a typed constant. Identify the
   key columns: a date/period column, one or more category/label columns, and
   the numeric column(s) to aggregate.

3. **Aggregate in your head, not in guesses.** Compute the rollups you intend
   to write (per-category totals, grand total, count, average, and — if a
   prior period is present — the month-over-month delta and % change). Do the
   arithmetic from the values you actually read.

4. **Decide where the summary lives.** Prefer a dedicated summary sheet so you
   never clobber source rows. If one doesn't exist, offer to create it with
   `numbers_add_sheet` (new sheets start blank — see Limitations). Lay out a
   small table: a header row, one row per category, then a Total row.

5. **Write the summary in one batch.** Use a single `numbers_set_cells` call
   for the whole summary. For the Total row and any derived figures, write
   **formulas** (`=SUM(B2:B9)`), not pre-computed constants, so the report
   stays live if the user edits a number later. (Digits has no transaction
   API — one batched call is the closest thing to atomic, so build the whole
   block at once rather than dribbling cells in.)

6. **Verify.** Re-read the summary table and confirm the formula results match
   the totals you computed in step 3. If they disagree, the cell references
   are wrong — fix them before reporting success.

7. **Export only with permission.** If the user wants a shareable artifact,
   confirm the path and format, then `numbers_export` (`pdf`, `excel`, or
   `csv`). Saving the .numbers file itself is a separate, explicit step
   (`numbers_save_document` / `numbers_save_as`) — ask first.

## Rules

- Read before you write; the source rows may have changed since last time.
- Aggregate only the values you read — no estimates, no "roughly."
- Put the summary on its own sheet/table; never overwrite source data.
- Derived cells are formulas, not constants, so the report recomputes.
- One `numbers_set_cells` batch per summary block, not many small writes.
- Numbers are plain (1234.5), never formatted strings ("$1,234.50").
- State your assumptions about which column is the period and which is the
  amount, and let the user correct you before you write.
