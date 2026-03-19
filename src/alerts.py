"""Alert detection engine for SpendSense.

Checks for anomalies: large transactions, category spikes, new vendors,
over-budget pace, unusual spending days, and missing categories.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Severity levels (higher = more urgent)
RED = 3
YELLOW = 2
INFO = 1

SEVERITY_EMOJI = {RED: "🔴", YELLOW: "🟡", INFO: "ℹ️"}
SEVERITY_LABEL = {RED: "RED", YELLOW: "YELLOW", INFO: "INFO"}


@dataclass
class Alert:
    severity: int
    alert_type: str
    message: str
    details: Optional[str] = None

    @property
    def emoji(self) -> str:
        return SEVERITY_EMOJI.get(self.severity, "")

    @property
    def label(self) -> str:
        return SEVERITY_LABEL.get(self.severity, "")


# ── Default thresholds (overridable via config) ──
DEFAULT_THRESHOLDS = {
    "large_transaction": 500,
    "category_spike_pct": 1.3,
    "new_vendor_min_amount": 50,
    "budget_pace_warning_pct": 0.9,
    "unusual_day_multiplier": 2.0,
}


class AlertEngine:
    """Detect spending anomalies and generate alerts."""

    def __init__(self, conn: sqlite3.Connection, thresholds: dict | None = None):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    def run(self, week_start: date, week_end: date) -> list[Alert]:
        """Run all alert checks and return sorted by severity (highest first)."""
        alerts: list[Alert] = []
        alerts += self._large_transactions(week_start, week_end)
        alerts += self._category_spikes(week_end)
        alerts += self._new_vendors(week_start, week_end)
        alerts += self._budget_pace(week_end)
        alerts += self._unusual_days(week_start, week_end)
        alerts += self._missing_categories(week_end)
        return sorted(alerts, key=lambda a: a.severity, reverse=True)

    # ── Alert: Large single transactions ──
    def _large_transactions(self, start: date, end: date) -> list[Alert]:
        threshold = self.thresholds["large_transaction"]
        rows = self.conn.execute(
            """SELECT posted_at, amount, vendor, description, tier2
               FROM transactions
               WHERE posted_at BETWEEN ? AND ?
                 AND tier1 NOT IN ('Transfer', 'Income')
                 AND ABS(amount) > ?
               ORDER BY ABS(amount) DESC""",
            (start.isoformat(), end.isoformat(), threshold),
        ).fetchall()

        alerts = []
        for r in rows:
            vendor = r["vendor"] or r["description"][:30]
            alerts.append(Alert(
                severity=RED,
                alert_type="LARGE TRANSACTION",
                message=f"${abs(r['amount']):,.2f} at {vendor} on {r['posted_at']}",
                details=r["tier2"],
            ))
        return alerts

    # ── Alert: Category spending spikes (MTD vs last month pace) ──
    def _category_spikes(self, week_end: date) -> list[Alert]:
        current_month = week_end.strftime("%Y-%m")
        day_of_month = week_end.day

        # Previous month
        first_of_month = week_end.replace(day=1)
        prev_month_end = first_of_month - timedelta(days=1)
        prev_month = prev_month_end.strftime("%Y-%m")

        # MTD spending by tier2 (current month)
        mtd = self.conn.execute(
            """SELECT tier2, SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
               GROUP BY tier2""",
            (current_month,),
        ).fetchall()

        # Same period last month (up to same day)
        prev_cutoff = f"{prev_month}-{day_of_month:02d}"
        prev_pace = {}
        for row in self.conn.execute(
            """SELECT tier2, SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND posted_at <= ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
               GROUP BY tier2""",
            (prev_month, prev_cutoff),
        ).fetchall():
            prev_pace[row["tier2"]] = row["total"]

        spike_pct = self.thresholds["category_spike_pct"]
        alerts = []
        for row in mtd:
            t2 = row["tier2"]
            current = row["total"]
            prev = prev_pace.get(t2, 0)
            if prev > 50 and current > prev * spike_pct:
                pct_over = ((current / prev) - 1) * 100
                alerts.append(Alert(
                    severity=YELLOW,
                    alert_type="CATEGORY SPIKE",
                    message=f"{t2} is {pct_over:.0f}% above last month's pace",
                    details=f"MTD: ${current:,.0f} vs ${prev:,.0f} same point last month",
                ))
        return alerts

    # ── Alert: New vendors (first time seeing this merchant) ──
    def _new_vendors(self, start: date, end: date) -> list[Alert]:
        min_amount = self.thresholds["new_vendor_min_amount"]
        rows = self.conn.execute(
            """SELECT vendor, amount, posted_at
               FROM transactions
               WHERE posted_at BETWEEN ? AND ?
                 AND tier1 NOT IN ('Transfer', 'Income')
                 AND vendor IS NOT NULL
                 AND ABS(amount) >= ?
                 AND vendor NOT IN (
                     SELECT DISTINCT vendor FROM transactions
                     WHERE posted_at < ? AND vendor IS NOT NULL
                 )
               ORDER BY ABS(amount) DESC""",
            (start.isoformat(), end.isoformat(), min_amount, start.isoformat()),
        ).fetchall()

        alerts = []
        for r in rows:
            alerts.append(Alert(
                severity=YELLOW,
                alert_type="NEW VENDOR",
                message=f'First time: "{r["vendor"]}" (${abs(r["amount"]):,.2f})',
                details=r["posted_at"],
            ))
        return alerts

    # ── Alert: Over-budget pace ──
    def _budget_pace(self, week_end: date) -> list[Alert]:
        current_month = week_end.strftime("%Y-%m")
        day_of_month = week_end.day
        days_in_month = 30  # Approximate

        # MTD spending
        mtd_row = self.conn.execute(
            """SELECT SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')""",
            (current_month,),
        ).fetchone()
        mtd_spending = mtd_row["total"] or 0

        # MTD income
        income_row = self.conn.execute(
            """SELECT SUM(amount) as total
               FROM transactions
               WHERE month = ? AND tier1 = 'Income'""",
            (current_month,),
        ).fetchone()
        mtd_income = income_row["total"] or 0

        if mtd_income <= 0 or day_of_month < 7:
            return []

        # Project spending for full month
        daily_rate = mtd_spending / day_of_month
        projected = daily_rate * days_in_month
        warn_pct = self.thresholds["budget_pace_warning_pct"]

        alerts = []
        if projected > mtd_income:
            alerts.append(Alert(
                severity=RED,
                alert_type="OVER BUDGET PACE",
                message=f"Spending on pace for ${projected:,.0f} vs ${mtd_income:,.0f} income",
                details=f"Daily avg: ${daily_rate:,.0f}/day × {days_in_month} days",
            ))
        elif projected > mtd_income * warn_pct:
            alerts.append(Alert(
                severity=YELLOW,
                alert_type="BUDGET WARNING",
                message=f"Spending at {projected / mtd_income * 100:.0f}% of income pace",
                details=f"Projected: ${projected:,.0f}, Income: ${mtd_income:,.0f}",
            ))
        return alerts

    # ── Alert: Unusual spending days ──
    def _unusual_days(self, start: date, end: date) -> list[Alert]:
        multiplier = self.thresholds["unusual_day_multiplier"]

        # Average daily spend over last 60 days
        lookback = start - timedelta(days=60)
        avg_row = self.conn.execute(
            """SELECT AVG(daily_total) as avg_daily FROM (
                 SELECT posted_at, SUM(ABS(amount)) as daily_total
                 FROM transactions
                 WHERE posted_at BETWEEN ? AND ?
                   AND amount < 0
                   AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
                 GROUP BY posted_at
               )""",
            (lookback.isoformat(), start.isoformat()),
        ).fetchone()
        avg_daily = avg_row["avg_daily"] or 0
        if avg_daily < 50:
            return []

        # Check each day this week
        daily = self.conn.execute(
            """SELECT posted_at, SUM(ABS(amount)) as daily_total
               FROM transactions
               WHERE posted_at BETWEEN ? AND ?
                 AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
               GROUP BY posted_at
               HAVING daily_total > ?""",
            (start.isoformat(), end.isoformat(), avg_daily * multiplier),
        ).fetchall()

        alerts = []
        for r in daily:
            alerts.append(Alert(
                severity=YELLOW,
                alert_type="HIGH SPENDING DAY",
                message=f"{r['posted_at']}: ${r['daily_total']:,.0f} spent (avg: ${avg_daily:,.0f}/day)",
            ))
        return alerts

    # ── Alert: Missing categories (had activity last month, zero this month) ──
    def _missing_categories(self, week_end: date) -> list[Alert]:
        if week_end.day < 20:
            return []  # Too early in the month to flag

        current_month = week_end.strftime("%Y-%m")
        first_of_month = week_end.replace(day=1)
        prev_month = (first_of_month - timedelta(days=1)).strftime("%Y-%m")

        # Categories active last month but not this month
        rows = self.conn.execute(
            """SELECT tier2, SUM(ABS(amount)) as prev_total
               FROM transactions
               WHERE month = ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
                 AND tier2 NOT IN (
                     SELECT DISTINCT tier2 FROM transactions
                     WHERE month = ? AND amount < 0
                       AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
                 )
               GROUP BY tier2
               HAVING prev_total > 30
               ORDER BY prev_total DESC""",
            (prev_month, current_month),
        ).fetchall()

        alerts = []
        for r in rows:
            alerts.append(Alert(
                severity=INFO,
                alert_type="MISSING CATEGORY",
                message=f"No {r['tier2']} purchases this month (was ${r['prev_total']:,.0f} last month)",
            ))
        return alerts
