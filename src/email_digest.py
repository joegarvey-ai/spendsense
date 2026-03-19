"""Weekly email digest generator — 'Monday Money Brief'.

Queries SQLite for spending data, runs the alert engine, and renders
HTML email templates for primary (full) and secondary (summary) recipients.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.alerts import AlertEngine
from src.db import get_connection

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class WeeklyDigest:
    """Generate weekly spending digests for primary and secondary recipients."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self.conn = conn or get_connection()
        self.conn.row_factory = sqlite3.Row
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=True,
        )

    def generate(self, week_end: date | None = None) -> dict:
        """Generate digest data and render HTML for both recipients.

        Args:
            week_end: Sunday of the reporting week. Defaults to last Sunday.

        Returns:
            {
                "primary": {"subject": str, "html": str},
                "secondary": {"subject": str, "html": str},
                "data": dict  # Raw data for --preview
            }
        """
        if week_end is None:
            today = date.today()
            # Last Sunday
            week_end = today - timedelta(days=(today.weekday() + 1) % 7)
            if week_end == today:
                week_end -= timedelta(days=7)

        week_start = week_end - timedelta(days=6)  # Monday
        current_month = week_end.strftime("%Y-%m")

        data = self._build_data(week_start, week_end, current_month)

        # Render templates
        primary_tmpl = self.env.get_template("digest_primary.html")
        summary_tmpl = self.env.get_template("digest_summary.html")

        week_label = f"{week_start.strftime('%b %d')}-{week_end.strftime('%d, %Y')}"
        subject = f"Monday Money Brief — Week of {week_label}"

        return {
            "primary": {
                "subject": subject,
                "html": primary_tmpl.render(**data),
            },
            "secondary": {
                "subject": f"Family Spending Update — Week of {week_label}",
                "html": summary_tmpl.render(**data),
            },
            "data": data,
        }

    def _build_data(self, week_start: date, week_end: date, current_month: str) -> dict:
        """Query DB and compute all digest metrics."""
        # ── This week vs last week ──
        prev_start = week_start - timedelta(days=7)
        prev_end = week_end - timedelta(days=7)

        this_week_total = self._spending_total(week_start, week_end)
        last_week_total = self._spending_total(prev_start, prev_end)
        wow_delta = self._pct_change(last_week_total, this_week_total)

        # ── MTD vs same point last month ──
        first_of_month = week_end.replace(day=1)
        prev_month_end = first_of_month - timedelta(days=1)
        prev_month = prev_month_end.strftime("%Y-%m")

        mtd_spending = self._mtd_spending(current_month)
        prev_mtd = self._spending_total_by_month_cutoff(prev_month, week_end.day)
        mom_delta = self._pct_change(prev_mtd, mtd_spending)

        # ── Income & cash flow ──
        mtd_income = self._mtd_income(current_month)
        day_of_month = week_end.day
        days_in_month = 30
        if mtd_spending > 0 and day_of_month > 0:
            projected_spending = (mtd_spending / day_of_month) * days_in_month
        else:
            projected_spending = 0
        projected_surplus = mtd_income - projected_spending

        if projected_surplus > 500:
            verdict = "ON TRACK"
            verdict_color = "#2E7D32"
        elif projected_surplus >= 0:
            verdict = "WATCH IT"
            verdict_color = "#F57F17"
        else:
            verdict = "OVER BUDGET"
            verdict_color = "#C62828"

        # ── Category breakdown (this week) ──
        categories = self._spending_by_category(week_start, week_end)
        cat_mtd = {r["tier2"]: r["total"] for r in self._spending_by_category_month(current_month)}
        cat_prev = {r["tier2"]: r["total"] for r in self._spending_by_category_month(prev_month)}

        category_rows = []
        for row in categories:
            t2 = row["tier2"]
            this_wk = row["total"]
            mtd = cat_mtd.get(t2, 0)
            prev = cat_prev.get(t2, 0)
            if prev > 0:
                trend = "↑" if mtd > prev * 0.8 else ("↓" if mtd < prev * 0.5 else "→")
            else:
                trend = "🆕"
            category_rows.append({
                "name": t2,
                "this_week": this_wk,
                "mtd": mtd,
                "last_month": prev,
                "trend": trend,
            })

        # ── Alerts ──
        engine = AlertEngine(self.conn)
        alerts = engine.run(week_start, week_end)

        # ── Allocations ──
        alloc = self._allocations(current_month)
        ira_ytd = self._ira_ytd(week_end.year)

        # ── Top spending items this week ──
        top_items = self.conn.execute(
            """SELECT posted_at, vendor, description, ABS(amount) as amt, tier2
               FROM transactions
               WHERE posted_at BETWEEN ? AND ?
                 AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
               ORDER BY ABS(amount) DESC LIMIT 10""",
            (week_start.isoformat(), week_end.isoformat()),
        ).fetchall()

        # ── Portfolio & Market (Phase 4) ──
        portfolio_data = self._get_portfolio_data()

        return {
            "week_start": week_start,
            "week_end": week_end,
            "current_month": current_month,
            "current_month_name": week_end.strftime("%B"),
            "this_week_total": this_week_total,
            "last_week_total": last_week_total,
            "wow_delta": wow_delta,
            "mtd_spending": mtd_spending,
            "prev_mtd": prev_mtd,
            "mom_delta": mom_delta,
            "mtd_income": mtd_income,
            "projected_spending": projected_spending,
            "projected_surplus": projected_surplus,
            "verdict": verdict,
            "verdict_color": verdict_color,
            "categories": category_rows,
            "alerts": alerts,
            "allocations": alloc,
            "ira_ytd": ira_ytd,
            "top_items": [dict(r) for r in top_items],
            "portfolio": portfolio_data,
        }

    def _get_portfolio_data(self) -> dict | None:
        """Gather portfolio data for the digest. Returns None if no holdings."""
        try:
            # Check if holdings table exists and has data
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM holdings"
            ).fetchone()
            if not row or row["cnt"] == 0:
                return None

            from src.market_data import MarketDataService
            from src.portfolio_analyzer import PortfolioAnalyzer
            from src.strategy_advisor import StrategyAdvisor

            market = MarketDataService(self.conn)
            analyzer = PortfolioAnalyzer(self.conn, market)
            advisor = StrategyAdvisor(self.conn)

            summary = analyzer.get_portfolio_summary()
            perf = analyzer.get_performance_vs_benchmark()
            movers = analyzer.get_top_movers(3)
            alloc = analyzer.get_allocation_breakdown()
            ira = advisor.ira_contribution_tracker()
            market_summary = market.get_market_summary()
            strategy_note = advisor.generate_strategy_note()

            return {
                "summary": summary,
                "performance": perf,
                "movers": movers,
                "concentration_alerts": alloc["concentration_alerts"],
                "ira": ira,
                "market_summary": market_summary,
                "strategy_note": strategy_note,
            }
        except Exception as e:
            logger.warning("Portfolio data unavailable for digest: %s", e)
            return None

    # ── Query helpers ──

    def _spending_total(self, start: date, end: date) -> float:
        row = self.conn.execute(
            """SELECT SUM(ABS(amount)) as total
               FROM transactions
               WHERE posted_at BETWEEN ? AND ?
                 AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')""",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return row["total"] or 0

    def _mtd_spending(self, month: str) -> float:
        row = self.conn.execute(
            """SELECT SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')""",
            (month,),
        ).fetchone()
        return row["total"] or 0

    def _spending_total_by_month_cutoff(self, month: str, day: int) -> float:
        cutoff = f"{month}-{day:02d}"
        row = self.conn.execute(
            """SELECT SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND posted_at <= ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')""",
            (month, cutoff),
        ).fetchone()
        return row["total"] or 0

    def _mtd_income(self, month: str) -> float:
        row = self.conn.execute(
            """SELECT SUM(amount) as total
               FROM transactions
               WHERE month = ? AND tier1 = 'Income'""",
            (month,),
        ).fetchone()
        return row["total"] or 0

    def _spending_by_category(self, start: date, end: date) -> list:
        return self.conn.execute(
            """SELECT tier2, SUM(ABS(amount)) as total, COUNT(*) as cnt
               FROM transactions
               WHERE posted_at BETWEEN ? AND ?
                 AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
               GROUP BY tier2
               ORDER BY total DESC""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()

    def _spending_by_category_month(self, month: str) -> list:
        return self.conn.execute(
            """SELECT tier2, SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND amount < 0
                 AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')
               GROUP BY tier2""",
            (month,),
        ).fetchall()

    def _allocations(self, month: str) -> dict:
        rows = self.conn.execute(
            """SELECT tier2, SUM(ABS(amount)) as total
               FROM transactions
               WHERE month = ? AND tier1 = 'Allocation'
               GROUP BY tier2""",
            (month,),
        ).fetchall()
        return {r["tier2"]: r["total"] for r in rows}

    def _ira_ytd(self, year: int) -> float:
        row = self.conn.execute(
            """SELECT SUM(ABS(amount)) as total
               FROM transactions
               WHERE month LIKE ? AND tier1 = 'Allocation'
                 AND tier2 = 'IRA Contribution'""",
            (f"{year}-%",),
        ).fetchone()
        return row["total"] or 0

    @staticmethod
    def _pct_change(old: float, new: float) -> float:
        if old == 0:
            return 0.0
        return ((new - old) / old) * 100
