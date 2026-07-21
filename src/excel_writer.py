"""Update the Excel dashboard and Transaction Log from SQLite data.

Architecture: The Transaction Log is the data layer (every transaction).
The Dashboard is a pure formula layer — all values are SUMIFS aggregating
from the Transaction Log. No hardcoded dollar amounts.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config.settings import EXCEL_PATH

logger = logging.getLogger(__name__)

# ── Styling ──
AUTO_FONT = Font(color="1F4E79")
AUTO_FILL = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
HEADER_FONT = Font(bold=True, size=11)
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT_WHITE = Font(bold=True, color="FFFFFF", size=11)
OVERRIDE_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
RED_FONT = Font(color="C00000", bold=True)
RED_FILL = PatternFill(start_color="FDE8E8", end_color="FDE8E8", fill_type="solid")
THIN_BORDER = Border(bottom=Side(style="thin", color="D9D9D9"))
MONEY_FORMAT = '#,##0.00'
ACCOUNTING_FORMAT = '#,##0;(#,##0)'
PCT_FORMAT = '0.0%'

# ── Month column mapping ──
MONTH_COLUMNS = {
    "2026-01": "C", "2026-02": "D", "2026-03": "E", "2026-04": "F",
    "2026-05": "G", "2026-06": "H", "2026-07": "I", "2026-08": "J",
    "2026-09": "K", "2026-10": "L", "2026-11": "M", "2026-12": "N",
}
MONTH_KEYS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06",
              "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"]

# ── SUMIFS building blocks ──
TL = "'Transaction Log'"
AMT = f"{TL}!$C:$C"
T1 = f"{TL}!$E:$E"
T2 = f"{TL}!$F:$F"
MO = f"{TL}!$G:$G"

# ──────────────────────────────────────────────────────────────────────────────
# Dashboard specification (row numbers AFTER 4-row insertion at position 45)
#
# Each entry: row → (label, formula_spec)
# formula_spec types:
#   "income"       → SUMIFS where tier1=Income, tier2=Payroll
#   "income_other" → SUMIFS where tier1=Income, tier2≠Payroll
#   "spend"        → -SUMIFS on tier2 list (negative amounts become positive)
#   "alloc"        → -SUMIFS where tier1=Allocation on tier2 list
#   "sum"          → SUM(first:last)
#   "ref"          → =cell reference
#   "formula"      → raw formula template with {col} placeholder
# ──────────────────────────────────────────────────────────────────────────────

DASHBOARD_SPEC: dict[int, tuple[str, dict]] = {
    # ── INCOME ──
    6:  ("Primary Income (Take-Home Pay)",
         {"type": "income"}),
    7:  ("Secondary Income (eBay, Airbnb, etc.)",
         {"type": "income_other"}),
    8:  ("TOTAL INCOME",
         {"type": "sum", "first": 6, "last": 7}),

    # ── FIXED EXPENSES ──
    12: ("Mortgage / Rent",
         {"type": "spend", "tier2s": ["Mortgage", "Rent"]}),
    13: ("Auto Loan",
         {"type": "spend", "tier2s": ["Auto Loan", "Installment Payment"]}),
    14: ("AI Tools",
         {"type": "spend", "tier2s": ["AI Tools"]}),
    15: ("Software",
         {"type": "spend", "tier2s": ["Software"]}),
    16: ("Gym",
         {"type": "spend", "tier2s": ["Gym"]}),
    17: ("Internet",
         {"type": "spend", "tier2s": ["Internet"]}),
    18: ("TOTAL FIXED",
         {"type": "sum", "first": 12, "last": 17}),

    # ── ESSENTIAL SPENDING ──
    22: ("Groceries",
         {"type": "spend", "tier2s": ["Groceries"]}),
    23: ("Auto — Fuel",
         {"type": "spend", "tier2s": ["Auto — Fuel"]}),
    24: ("Auto — Maintenance",
         {"type": "spend", "tier2s": ["Auto — Maintenance", "Auto — Purchase", "Auto — Wash"]}),
    25: ("Shipping",
         {"type": "spend", "tier2s": ["Shipping"]}),
    26: ("Utilities",
         {"type": "spend", "tier2s": ["Utilities"]}),
    27: ("Medical / Vet",
         {"type": "spend", "tier2s": ["Pet — Vet"]}),
    28: ("Insurance (Home/Life)",
         {"type": "spend", "tier2s": ["Life Insurance"]}),
    29: ("Taxes (State/Local)",
         {"type": "spend", "tier2s": ["Taxes"]}),
    30: ("Childcare/Kids — Activities",
         {"type": "spend", "tier2s": []}),
    31: ("Donations (Church/Charity)",
         {"type": "spend", "tier2s": ["Donations"]}),
    32: ("Home Maintenance / Garden",
         {"type": "spend", "tier2s": ["Home & Garden"]}),
    33: ("TOTAL ESSENTIAL",
         {"type": "sum", "first": 22, "last": 32}),

    # ── NON-ESSENTIAL SPENDING (rows 37-48, +4 inserted) ──
    37: ("Dining Out",
         {"type": "spend", "tier2s": ["Dining Out"]}),
    38: ("Food Delivery (DoorDash/UberEats)",
         {"type": "spend", "tier2s": ["Food Delivery"]}),
    39: ("Clothing / Shopping",
         {"type": "spend", "tier2s": ["Clothing", "Shopping"]}),
    40: ("Entertainment",
         {"type": "spend", "tier2s": ["Entertainment", "Recreation"]}),
    41: ("Travel",
         {"type": "spend", "tier2s": ["Travel"]}),
    42: ("Pets",
         {"type": "spend", "tier2s": ["Pet", "Pet — Care"]}),
    43: ("Subscriptions (non-fixed)",
         {"type": "spend", "tier2s": ["Subscriptions", "iPhone Payment", "Web Hosting",
                                      "Annual Fees", "Clear Plus"]}),
    44: ("Amazon (General)",
         {"type": "spend", "tier2s": ["Amazon"]}),
    45: ("Rideshare",
         {"type": "spend", "tier2s": ["Rideshare"]}),
    46: ("Personal Care",
         {"type": "spend", "tier2s": ["Personal Care"]}),
    47: ("Parking",
         {"type": "spend", "tier2s": ["Parking"]}),
    48: ("Vending / Misc NE",
         {"type": "spend", "tier2s": ["Vending", "Venmo", "PayPal", "Cash"]}),
    49: ("TOTAL NON-ESSENTIAL",
         {"type": "sum", "first": 37, "last": 48}),

    # ── DISCRETIONARY SPENDING (shifted +4) ──
    53: ("Electronics/Devices",
         {"type": "spend", "tier2s": ["Electronics/Devices", "Apple Services"]}),
    54: ("Hobbies / Lessons",
         {"type": "spend", "tier2s": ["Lessons"]}),
    55: ("Collectibles",
         {"type": "spend", "tier2s": ["Collectibles"]}),
    56: ("Misc / Uncategorized",
         {"type": "spend", "tier2s": ["Misc / Uncategorized", "Misc"]}),
    57: ("TOTAL DISCRETIONARY",
         {"type": "sum", "first": 53, "last": 56}),

    # ── ALLOCATIONS (shifted +4) ──
    61: ("Savings",
         {"type": "alloc", "tier2s": ["Savings"]}),
    62: ("Investments (Stocks)",
         {"type": "alloc", "tier2s": ["Investments", "Interest", "Dividends"]}),
    63: ("IRA Contribution",
         {"type": "alloc", "tier2s": ["IRA Contribution"]}),
    64: ("Shared Savings — Partner",
         {"type": "alloc", "tier2s": ["Shared Savings"]}),
    65: ("Extra Mortgage Principal",
         {"type": "alloc", "tier2s": ["Extra Mortgage"]}),
    66: ("Extra Car Principal",
         {"type": "alloc", "tier2s": ["Extra Car"]}),
    67: ("TOTAL ALLOCATIONS",
         {"type": "sum", "first": 61, "last": 66}),

    # ── MONTHLY SUMMARY (shifted +4) ──
    71: ("Total Income",
         {"type": "ref", "row": 8}),
    72: ("Less: Fixed Expenses",
         {"type": "ref", "row": 18}),
    73: ("Less: Essential Spending",
         {"type": "ref", "row": 33}),
    74: ("Less: Non-Essential Spending",
         {"type": "ref", "row": 49}),
    75: ("Less: Discretionary Spending",
         {"type": "ref", "row": 57}),
    76: ("Less: Allocations",
         {"type": "ref", "row": 67}),
    77: ("NET CASH FLOW (Surplus / Deficit)",
         {"type": "formula", "template": "={col}71-{col}72-{col}73-{col}74-{col}75-{col}76"}),
    78: ("Savings Rate (Allocations / Income)",
         {"type": "formula", "template": "=IFERROR({col}67/{col}8,0)"}),

    # ── FOOD TOTAL (shifted +4) ──
    80: ("FOOD TOTAL (Groceries + Dining + Delivery)",
         {"type": "formula", "template": "={col}22+{col}37+{col}38"}),
}

# Rows that get red formatting (Less: items)
ROWS_LESS = [72, 73, 74, 75, 76]
ROW_NET_CASH_FLOW = 77
ROW_SAVINGS_RATE = 78

# ── Transaction Log columns ──
TXN_LOG_HEADERS = [
    "Date", "Vendor / Merchant", "Amount", "Account Source",
    "Tier 1 Category", "Tier 2 Subcategory", "Month",
    "Notes / Override Reason", "Override?", "Transaction ID",
]
TXN_LOG_START_ROW = 4


# ──────────────────────────────────────────────────────────────────────────────
# Formula generators
# ──────────────────────────────────────────────────────────────────────────────

def _sumifs_spend(tier2s: list[str], col: str) -> str:
    """Generate =-SUMIFS(... tier2, month) for spending rows.

    Spending amounts are negative in the Transaction Log, so we negate
    to display as positive dollars in the Dashboard.
    """
    if not tier2s:
        return "=0"
    parts = []
    for t2 in tier2s:
        parts.append(f'SUMIFS({AMT},{T2},"{t2}",{MO},{col}$3)')
    return "=-" + "-".join(parts)


def _sumifs_alloc(tier2s: list[str], col: str) -> str:
    """Generate =-SUMIFS(... tier1=Allocation, tier2, month) for allocation rows.

    Only sums negative amounts (outflows), negated to show positive.
    """
    if not tier2s:
        return "=0"
    parts = []
    for t2 in tier2s:
        parts.append(
            f'SUMIFS({AMT},{T1},"Allocation",{T2},"{t2}",{MO},{col}$3)'
        )
    return "=-" + "-".join(parts)


def _sumifs_income(col: str) -> str:
    """Primary Income = SUMIFS where tier1=Income AND tier2=Payroll."""
    return f'=SUMIFS({AMT},{T1},"Income",{T2},"Payroll",{MO},{col}$3)'


def _sumifs_income_other(col: str) -> str:
    """Secondary Income = all Income minus Payroll."""
    return (
        f'=SUMIFS({AMT},{T1},"Income",{MO},{col}$3)'
        f'-SUMIFS({AMT},{T1},"Income",{T2},"Payroll",{MO},{col}$3)'
    )


def _build_formula(spec: dict, col: str) -> str:
    """Build the Excel formula string for a given spec and column letter."""
    t = spec["type"]
    if t == "income":
        return _sumifs_income(col)
    if t == "income_other":
        return _sumifs_income_other(col)
    if t == "spend":
        return _sumifs_spend(spec["tier2s"], col)
    if t == "alloc":
        return _sumifs_alloc(spec["tier2s"], col)
    if t == "sum":
        return f"=SUM({col}{spec['first']}:{col}{spec['last']})"
    if t == "ref":
        return f"={col}{spec['row']}"
    if t == "formula":
        return spec["template"].replace("{col}", col)
    raise ValueError(f"Unknown formula type: {t}")


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard setup
# ──────────────────────────────────────────────────────────────────────────────

def _needs_row_insertion(ws) -> bool:
    """Check if the 4 Non-Essential rows have already been inserted."""
    val = ws.cell(row=45, column=2).value
    return val != "Rideshare"


def _insert_non_essential_rows(ws) -> None:
    """Insert 4 new rows after row 44 (Amazon) in the Non-Essential section.

    This shifts everything from row 45 onward down by 4.
    """
    ws.insert_rows(45, 4)
    logger.info("Inserted 4 new rows (45-48) in Non-Essential section")


def _write_month_reference_row(ws) -> None:
    """Write month keys in row 3 (hidden reference for SUMIFS)."""
    for month_key, col_letter in MONTH_COLUMNS.items():
        cell = ws[f"{col_letter}3"]
        cell.value = month_key
        cell.font = Font(color="FFFFFF", size=1)  # Invisible
        cell.number_format = "@"  # Text format


def _write_labels(ws) -> None:
    """Write/update all Dashboard labels in column B."""
    for row, (label, _spec) in DASHBOARD_SPEC.items():
        ws.cell(row=row, column=2).value = label


def _write_all_formulas(ws) -> None:
    """Write SUMIFS and structural formulas into all Dashboard data cells."""
    cells_written = 0
    for row, (_label, spec) in DASHBOARD_SPEC.items():
        for col_letter in MONTH_COLUMNS.values():
            formula = _build_formula(spec, col_letter)
            cell = ws[f"{col_letter}{row}"]
            cell.value = formula

            # Apply number format
            t = spec["type"]
            if t in ("income", "income_other", "spend", "alloc", "sum", "ref"):
                cell.number_format = MONEY_FORMAT
            elif row == ROW_NET_CASH_FLOW:
                cell.number_format = ACCOUNTING_FORMAT
            elif row == ROW_SAVINGS_RATE:
                cell.number_format = PCT_FORMAT

            # Apply auto-fill styling for data rows
            if t in ("income", "income_other", "spend", "alloc"):
                cell.font = AUTO_FONT
                cell.fill = AUTO_FILL

            cells_written += 1

    # Also write YTD formula in column O for each row
    for row, (_label, spec) in DASHBOARD_SPEC.items():
        t = spec["type"]
        if t == "sum":
            ws[f"O{row}"] = f"=SUM(C{row}:N{row})"
            ws[f"O{row}"].number_format = MONEY_FORMAT
            ws[f"O{row}"].font = Font(bold=True)
        elif t in ("income", "income_other", "spend", "alloc"):
            ws[f"O{row}"] = f"=SUM(C{row}:N{row})"
            ws[f"O{row}"].number_format = MONEY_FORMAT

    logger.info("Wrote %d SUMIFS/formula cells across Dashboard", cells_written)


def _clear_hardcoded_values(ws) -> None:
    """Clear any remaining hardcoded dollar amounts in data rows.

    After writing formulas, some cells might have old values in columns
    that we didn't write to (e.g., column O from Phase 1).
    """
    # Clear row 3 label if set
    ws.cell(row=3, column=2).value = None


def _apply_formatting(ws) -> None:
    """Apply formatting: red for Less: rows, accounting for Net Cash Flow."""
    # "Less:" rows
    for row in ROWS_LESS:
        for col in range(3, 15):
            cell = ws.cell(row=row, column=col)
            cell.font = RED_FONT
            cell.fill = RED_FILL

    # Net Cash Flow
    for col in range(3, 15):
        ws.cell(row=ROW_NET_CASH_FLOW, column=col).number_format = ACCOUNTING_FORMAT

    # Savings Rate
    for col in range(3, 15):
        ws.cell(row=ROW_SAVINGS_RATE, column=col).number_format = PCT_FORMAT

    # Section headers (row 5 "Category" and month names)
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    for header_row in [5, 11, 21, 36, 52, 60, 70]:
        ws.cell(row=header_row, column=2).value = "Category"
        for i, name in enumerate(month_names):
            ws.cell(row=header_row, column=3 + i).value = name
        ws.cell(row=header_row, column=15).value = "YTD"

    # Section title rows
    section_titles = {
        4: "INCOME", 10: "FIXED EXPENSES", 20: "ESSENTIAL SPENDING",
        35: "NON-ESSENTIAL SPENDING", 51: "DISCRETIONARY SPENDING",
        59: "ALLOCATIONS (Money to Yourself)", 69: "MONTHLY SUMMARY",
    }
    for row, title in section_titles.items():
        ws.cell(row=row, column=2).value = title

    # Food total detail rows
    ws.cell(row=81, column=2).value = "  of which: Groceries (Essential, row 22)"
    ws.cell(row=82, column=2).value = "  of which: Dining Out (Non-Essential, row 37)"
    ws.cell(row=83, column=2).value = "  of which: Food Delivery (Non-Essential, row 38)"


# ──────────────────────────────────────────────────────────────────────────────
# Transaction Log
# ──────────────────────────────────────────────────────────────────────────────

def _write_transaction_log(wb, conn: sqlite3.Connection) -> int:
    """Populate the Transaction Log sheet with all transactions."""
    if "Transaction Log" not in wb.sheetnames:
        wb.create_sheet("Transaction Log")

    ws = wb["Transaction Log"]

    # Clear existing data (keep rows 1-3 as intro, row 4 as headers)
    if ws.max_row >= 5:
        ws.delete_rows(5, ws.max_row - 4)

    # Write headers at row 4
    for col_idx, header in enumerate(TXN_LOG_HEADERS, start=1):
        cell = ws.cell(row=TXN_LOG_START_ROW, column=col_idx)
        cell.value = header
        cell.font = HEADER_FONT_WHITE
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    # Set column widths
    col_widths = [12, 45, 12, 35, 18, 25, 10, 30, 10, 50]
    for i, width in enumerate(col_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # Query all transactions ordered by date desc
    rows = conn.execute(
        """SELECT posted_at, vendor, amount, account_id, tier1, tier2,
                  month, id, auto_categorized, description
           FROM transactions
           ORDER BY posted_at DESC, amount"""
    ).fetchall()

    # Load account names
    from config.settings import ACCOUNT_MAP
    accounts_db = {}
    for row in conn.execute("SELECT id, institution, name FROM accounts").fetchall():
        accounts_db[row["id"]] = f"{row['institution']} — {row['name']}"

    count = 0
    for row_data in rows:
        excel_row = TXN_LOG_START_ROW + 1 + count
        posted = row_data["posted_at"]
        vendor = row_data["vendor"] or row_data["description"]
        amount = row_data["amount"]
        account_id = row_data["account_id"]
        tier1 = row_data["tier1"]
        tier2 = row_data["tier2"]
        month = row_data["month"]
        txn_id = row_data["id"]
        auto_cat = row_data["auto_categorized"]

        acct_name = ACCOUNT_MAP.get(account_id, {}).get("name", "")
        if not acct_name:
            acct_name = accounts_db.get(account_id, account_id[:30])

        ws.cell(row=excel_row, column=1, value=posted)
        ws.cell(row=excel_row, column=2, value=vendor[:80])
        c_amt = ws.cell(row=excel_row, column=3, value=amount)
        c_amt.number_format = MONEY_FORMAT
        ws.cell(row=excel_row, column=4, value=acct_name)
        ws.cell(row=excel_row, column=5, value=tier1)
        ws.cell(row=excel_row, column=6, value=tier2)
        ws.cell(row=excel_row, column=7, value=month)
        ws.cell(row=excel_row, column=8, value="")
        ws.cell(row=excel_row, column=9, value="")
        ws.cell(row=excel_row, column=10, value=txn_id)

        # Style override rows
        if not auto_cat:
            for col in range(1, 10):
                ws.cell(row=excel_row, column=col).fill = OVERRIDE_FILL

        # Alternate row shading
        if count % 2 == 1:
            for col in range(1, 11):
                cell = ws.cell(row=excel_row, column=col)
                if not cell.fill or cell.fill.start_color.rgb == "00000000":
                    cell.fill = PatternFill(
                        start_color="F2F2F2", end_color="F2F2F2", fill_type="solid"
                    )

        for col in range(1, 11):
            ws.cell(row=excel_row, column=col).border = THIN_BORDER

        count += 1

    ws.auto_filter.ref = f"A{TXN_LOG_START_ROW}:J{TXN_LOG_START_ROW + count}"
    ws.freeze_panes = f"A{TXN_LOG_START_ROW + 1}"

    logger.info("Transaction Log: wrote %d transactions", count)
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Override reader
# ──────────────────────────────────────────────────────────────────────────────

def read_overrides_from_excel(
    conn: sqlite3.Connection,
    excel_path: Path = None,
) -> int:
    """Read overrides from the Transaction Log sheet.

    Looks for rows where column I (Override?) = 'Y'.
    Reads Tier 1 (col E), Tier 2 (col F), and Notes (col H).
    Applies them to the DB via the overrides table.
    """
    from src.db import apply_override

    path = excel_path or EXCEL_PATH
    if not path.exists():
        return 0

    wb = load_workbook(str(path), data_only=True)
    if "Transaction Log" not in wb.sheetnames:
        wb.close()
        return 0

    ws = wb["Transaction Log"]
    applied = 0

    for row in range(TXN_LOG_START_ROW + 1, ws.max_row + 1):
        override_flag = ws.cell(row=row, column=9).value
        if not override_flag or str(override_flag).strip().upper() != "Y":
            continue

        txn_id = ws.cell(row=row, column=10).value
        tier1 = ws.cell(row=row, column=5).value
        tier2 = ws.cell(row=row, column=6).value
        reason = ws.cell(row=row, column=8).value

        if not txn_id or not tier1 or not tier2:
            logger.warning("Override row %d missing txn_id/tier1/tier2 — skipping", row)
            continue

        apply_override(conn, str(txn_id), str(tier1), str(tier2), reason=str(reason or "Excel override"))
        applied += 1
        logger.info("Applied Excel override: %s → %s / %s", txn_id[:40], tier1, tier2)

    wb.close()
    logger.info("Read %d overrides from Excel Transaction Log", applied)
    return applied


# ──────────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────────

def update_dashboard(
    conn: sqlite3.Connection,
    excel_path: Path = None,
) -> None:
    """Update the Excel dashboard and Transaction Log.

    1. Insert new rows if needed (one-time structural change)
    2. Write month reference row
    3. Write/update all Dashboard labels
    4. Write SUMIFS formulas for every data cell
    5. Apply formatting
    6. Populate Transaction Log with all transactions
    """
    path = excel_path or EXCEL_PATH
    if not path.exists():
        logger.warning("Excel file not found at %s — skipping dashboard update", path)
        return

    wb = load_workbook(str(path))

    # Find Dashboard sheet
    sheet_name = None
    for name in ["Dashboard", "Monthly", "Summary", "Sheet1"]:
        if name in wb.sheetnames:
            sheet_name = name
            break
    if sheet_name is None:
        sheet_name = wb.sheetnames[0]
    ws = wb[sheet_name]

    # ── Insert rows if needed (one-time) ──
    if _needs_row_insertion(ws):
        _insert_non_essential_rows(ws)

    # ── Month reference row ──
    _write_month_reference_row(ws)

    # ── Labels ──
    _write_labels(ws)

    # ── SUMIFS formulas ──
    _write_all_formulas(ws)

    # ── Formatting ──
    _apply_formatting(ws)

    # ── Transaction Log ──
    txn_count = _write_transaction_log(wb, conn)

    wb.save(str(path))
    wb.close()
    logger.info("Dashboard updated: SUMIFS formulas written, %d transactions logged", txn_count)
