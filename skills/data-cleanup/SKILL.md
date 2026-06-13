---
name: data-cleanup
description: Tidy a messy Apple Numbers table — find duplicates, blanks, inconsistent labels, and stray text in number columns — then fix them safely with the user's sign-off. Use when the user says "clean up this data", "find duplicates", "this sheet is a mess", "normalize these categories", "fix the blanks", or "why won't this column sum".
---

# Data Cleanup (Apple Numbers)

Diagnose and repair common data-quality problems in a live Numbers table using
the Digits MCP tools (`numbers_*`). Cleanup is destructive by nature, so the
rule is: **diagnose fully, propose, get sign-off, then fix in one batch.**

## Workflow

1. **Locate the table.** `numbers_list_documents` → `numbers_list_sheets` →
   `numbers_list_tables`. Confirm which table to clean and its dimensions.

2. **Read everything.** `numbers_read_table` with `include_formulas: true`.
   A formula that returns an error or a blank looks the same as a typed blank
   until you check the formula grid.

3. **Profile and report problems — don't fix yet.** Scan for:
   - **Duplicate rows** (exact, or matching on a key column the user names).
   - **Blanks** in columns that should be complete.
   - **Inconsistent labels** — "NYC" / "nyc" / "New York City", trailing
     spaces, mixed casing — that fragment what should be one category.
   - **Text in number columns** — "$1,200", "1200 ", "N/A", "tbd" — the usual
     reason a `SUM` won't compute. (`numbers_read_table` returns these as
     strings rather than numbers, which is your tell.)
   - **Type mismatches** within a column (some cells numeric, some text).

   Present findings grouped by problem type, with cell references and counts,
   leading with what's already clean.

4. **Propose a fix plan and get explicit sign-off.** For each issue, say
   exactly what you'll do: which rows you'll delete, which labels you'll
   normalize to which canonical value, which strings you'll convert to numbers.
   Deleting rows and overwriting cells is not reversible except by Cmd+Z, so
   the user must approve the plan before you touch anything.

5. **Fix in the safest order, batched:**
   - **Value fixes first.** Normalize labels and convert text-numbers to real
     numbers in a single `numbers_set_cells` call (Digits has no transaction
     API, so one batched write is the closest thing to atomic — prefer it over
     many small writes that could half-apply).
   - **Row deletions last**, since deleting shifts indices. Delete from the
     **bottom up** (`numbers_delete_row` at the highest index first) so earlier
     indices stay valid as you go.

6. **Verify.** Re-read the table. Confirm duplicates are gone, the problem
   columns are now uniformly numeric, and any totals/`SUM`s compute. Report
   before/after counts.

7. **Save only with permission.** Edits are in-memory and undoable until the
   user saves. Ask before `numbers_save_document`.

## Rules

- Diagnose and propose before changing anything; never silently "fix" data.
- Deletions go bottom-up so row indices don't shift under you.
- Convert "$1,200" → 1200 as a plain number; formatting is the cell's job.
- Pick one canonical spelling per category and tell the user what you chose.
- Batch value edits into one `numbers_set_cells` call.
- When in doubt about whether two rows are "the same," ask — don't assume.
