"""Portfolio analysis: summary, allocation, performance, dividends, risk."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, date

from config.loader import portfolio_config
from src.market_data import MarketDataService

logger = logging.getLogger(__name__)


class PortfolioAnalyzer:
    """Analyze investment portfolio from holdings + market data."""

    def __init__(self, conn: sqlite3.Connection, market: MarketDataService | None = None):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.market = market or MarketDataService(conn)

    def get_portfolio_summary(self, account: str | None = None) -> dict:
        """Full portfolio summary with per-holding details.

        Returns:
            {total_value, total_cost_basis, total_gain_loss, total_return_pct,
             holdings: [{ticker, shares, avg_cost, current_price, market_value, ...}]}
        """
        query = "SELECT * FROM holdings"
        params = ()
        if account:
            query += " WHERE account = ?"
            params = (account,)

        rows = self.conn.execute(query, params).fetchall()
        holdings = []
        total_value = 0
        total_cost = 0

        for r in rows:
            ticker = r["ticker"]
            shares = r["shares"]
            avg_cost = r["avg_cost_basis"]

            md = self.market.get_cached_market_data(ticker)
            price = md["current_price"] if md else 0
            sector = md["sector"] if md else ""
            div_yield = md["dividend_yield"] if md else 0

            market_value = shares * price
            cost_basis = shares * avg_cost
            gain_loss = market_value - cost_basis
            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis > 0 else 0

            total_value += market_value
            total_cost += cost_basis

            holdings.append({
                "ticker": ticker,
                "account": r["account"],
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": price,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "gain_loss": gain_loss,
                "gain_loss_pct": gain_loss_pct,
                "sector": sector,
                "dividend_yield": div_yield or 0,
                "estimated": bool(r["estimated"]),
            })

        total_gain = total_value - total_cost
        total_return = (total_gain / total_cost * 100) if total_cost > 0 else 0

        # Sort by market value descending
        holdings.sort(key=lambda h: h["market_value"], reverse=True)

        # Calculate weight percentages
        for h in holdings:
            h["weight_pct"] = (h["market_value"] / total_value * 100) if total_value > 0 else 0

        return {
            "total_value": total_value,
            "total_cost_basis": total_cost,
            "total_gain_loss": total_gain,
            "total_return_pct": total_return,
            "holdings": holdings,
            "has_estimates": any(h["estimated"] for h in holdings),
        }

    def get_allocation_breakdown(self) -> dict:
        """Sector and account allocation with concentration risk alerts."""
        summary = self.get_portfolio_summary()
        holdings = summary["holdings"]
        total = summary["total_value"]

        # By sector
        by_sector: dict[str, float] = {}
        for h in holdings:
            s = h["sector"] or "Unknown"
            by_sector[s] = by_sector.get(s, 0) + h["market_value"]
        sector_pcts = {s: (v / total * 100) if total > 0 else 0 for s, v in by_sector.items()}

        # By account
        by_account: dict[str, float] = {}
        for h in holdings:
            a = h["account"]
            by_account[a] = by_account.get(a, 0) + h["market_value"]
        account_pcts = {a: (v / total * 100) if total > 0 else 0 for a, v in by_account.items()}

        # Concentration risk
        concentration_alerts = []
        for h in holdings:
            if h["weight_pct"] > portfolio_config.CONCENTRATION_WARN_PCT * 100:
                concentration_alerts.append({
                    "ticker": h["ticker"],
                    "weight_pct": h["weight_pct"],
                    "risk": f"HIGH — single stock > {portfolio_config.CONCENTRATION_WARN_PCT*100:.0f}% of portfolio",
                })

        return {
            "by_sector": dict(sorted(sector_pcts.items(), key=lambda x: x[1], reverse=True)),
            "by_account": account_pcts,
            "concentration_alerts": concentration_alerts,
            "total_value": total,
        }

    def get_performance_vs_benchmark(self) -> dict:
        """Compare portfolio return vs S&P 500.

        Uses cost basis as the 'start' and current value as 'end' for
        portfolio return. Compares to S&P 500 return over cached period.
        """
        summary = self.get_portfolio_summary()
        portfolio_return = summary["total_return_pct"]

        spy_return = self.market.get_benchmark_return("^GSPC", period_days=90)

        return {
            "portfolio_return_pct": portfolio_return,
            "spy_return_pct": spy_return or 0,
            "alpha": portfolio_return - (spy_return or 0),
            "note": "Portfolio return is total since purchase; S&P is last 3 months" if spy_return else "Benchmark data not available — run 'portfolio refresh' first",
        }

    def get_dividend_summary(self) -> dict:
        """Estimate annual dividend income from current holdings."""
        holdings = self.get_portfolio_summary()["holdings"]

        annual_total = 0
        top_payers = []

        for h in holdings:
            dy = h["dividend_yield"] or 0
            annual_div = h["market_value"] * dy
            annual_total += annual_div
            if annual_div > 0:
                top_payers.append({"ticker": h["ticker"], "annual": annual_div, "yield": dy * 100})

        top_payers.sort(key=lambda x: x["annual"], reverse=True)
        total_cost = holdings[0]["cost_basis"] if holdings else 0  # Just for yield calc
        total_value = sum(h["market_value"] for h in holdings)

        return {
            "annual_estimate": annual_total,
            "monthly_average": annual_total / 12,
            "yield_on_cost": (annual_total / total_value * 100) if total_value > 0 else 0,
            "top_payers": top_payers[:10],
        }

    def get_top_movers(self, n: int = 5) -> dict:
        """Get top gainers and losers by day change percent."""
        rows = self.conn.execute(
            """SELECT m.ticker, m.day_change_pct, m.current_price, h.shares
               FROM market_data m
               JOIN holdings h ON h.ticker = m.ticker
               WHERE m.day_change_pct IS NOT NULL
               ORDER BY m.day_change_pct DESC"""
        ).fetchall()

        all_movers = [dict(r) for r in rows]
        return {
            "gainers": all_movers[:n],
            "losers": list(reversed(all_movers[-n:])) if len(all_movers) >= n else [],
        }

    def snapshot_portfolio(self) -> None:
        """Save a daily portfolio snapshot for tracking over time."""
        today = date.today().isoformat()

        accounts = self.conn.execute("SELECT DISTINCT account FROM holdings").fetchall()
        for (acct_row,) in [(r["account"],) for r in accounts]:
            summary = self.get_portfolio_summary(account=acct_row)
            self.conn.execute(
                """INSERT INTO portfolio_snapshots
                   (snapshot_date, account, total_value, total_cost_basis, total_gain_loss, gain_loss_pct)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(snapshot_date, account) DO UPDATE SET
                       total_value = excluded.total_value,
                       total_cost_basis = excluded.total_cost_basis,
                       total_gain_loss = excluded.total_gain_loss,
                       gain_loss_pct = excluded.gain_loss_pct""",
                (today, acct_row, summary["total_value"], summary["total_cost_basis"],
                 summary["total_gain_loss"], summary["total_return_pct"]),
            )
        self.conn.commit()
        logger.info("Portfolio snapshot saved for %s", today)
