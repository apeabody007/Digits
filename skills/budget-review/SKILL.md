---
name: budget-review
description: Review, fill in, and balance a monthly budget kept in Apple Numbers using the Digits MCP tools. Use when the user says "review my budget", "update my budget", "fill in my budget", "balance my budget", "how am I doing this month", or asks to add expenses, income, or totals to a Numbers budget spreadsheet.
---

# Budget Review (Apple Numbers)

Drive a monthly-budget workflow against a live Numbers spreadsheet using the
Digits MCP tools (`numbers_*`). Never guess at the spreadsheet's contents —
always read before writing.

## Workflow

1. **Locate the budget.** Call `numbers_list_documents`. If empty, ask the
   user for the file path and call `numbers_open_document`. If multiple
   documents are open, ask which one is the budget.

2. **Orient.** Call `numbers_list_sheets` (budgets are often one sheet per
   month — pick the current month unless told otherwise) and
   `numbers_list_tables` to get table names and dimensions.

3. **Read the current state.** Call `numbers_read_table` with
   `include_formulas: true`. Build a mental model: where income lines are,
   where expense lines are, which cells hold amounts, which hold totals.

4. **Gap analysis.** Report to the user, leading with what's already in good
   shape, then:
   - expense/income lines with no amount filled in
   - totals that are typed constants instead of formulas
   - missing common categories (savings, debt payments, emergency fund)
   - arithmetic that doesn't add up

5. **Collect amounts conversationally.** Ask for missing numbers in one
   batch, not one question at a time. Accept approximations.

6. **Write in one batch.** Use a single `numbers_set_cells` call with all
   updates. Use formulas, not computed constants, for derived cells — e.g.
   `=SUM(F4:F14)` for a total — so the sheet stays live when the user edits
   it by hand later.

7. **Verify.** Re-read the table and confirm the totals computed correctly.
   Show the user income − expenses = surplus/deficit.

8. **Save only with permission.** `numbers_set_cells` edits are in-memory
   and undoable. Ask before calling `numbers_save_document`.

## Rules

- Read before every write session; the user may have edited the sheet.
- Never overwrite a non-empty cell without telling the user first.
- Prefer one large `numbers_set_cells` batch over many small ones.
- Money amounts: write plain numbers (2515.50), never formatted strings
  ("$2,515.50") — formatting belongs to the cell, not the value.
- If a target sheet for the current month doesn't exist, offer to build it
  by copying the structure of the most recent month's sheet.
