"""Market data service using yfinance with SQLite caching."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, date

import yfinance as yf

from config.portfolio_config import BENCHMARKS

logger = logging.getLogger(__name__)


class MarketDataService:
    """Fetch and cache market data from Yahoo Finance."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def refresh_holdings_prices(self) -> int:
        """Fetch current prices + metadata for all tickers in holdings table.

        Returns number of tickers updated.
        """
        rows = self.conn.execute("SELECT DISTINCT ticker FROM holdings").fetchall()
        tickers = [r["ticker"] for r in rows]
        if not tickers:
            logger.info("No holdings to refresh")
            return 0

        logger.info("Refreshing prices for %d tickers: %s", len(tickers), ", ".join(tickers))
        updated = 0
        now = datetime.now().isoformat()

        # Batch fetch
        try:
            data = yf.Tickers(" ".join(tickers))
        except Exception as e:
            logger.error("yfinance batch fetch failed: %s", e)
            return 0

        for ticker in tickers:
            try:
                info = data.tickers[ticker].info
                if not info or "currentPrice" not in info and "regularMarketPrice" not in info:
                    logger.warning("No price data for %s", ticker)
                    continue

                price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
                day_change = info.get("regularMarketChangePercent", 0)

                self.conn.execute(
                    """INSERT INTO market_data
                       (ticker, name, sector, industry, current_price, day_change_pct,
                        market_cap, pe_ratio, dividend_yield, beta,
                        fifty_two_week_high, fifty_two_week_low, last_fetched)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(ticker) DO UPDATE SET
                           name = excluded.name,
                           sector = excluded.sector,
                           industry = excluded.industry,
                           current_price = excluded.current_price,
                           day_change_pct = excluded.day_change_pct,
                           market_cap = excluded.market_cap,
                           pe_ratio = excluded.pe_ratio,
                           dividend_yield = excluded.dividend_yield,
                           beta = excluded.beta,
                           fifty_two_week_high = excluded.fifty_two_week_high,
                           fifty_two_week_low = excluded.fifty_two_week_low,
                           last_fetched = excluded.last_fetched""",
                    (
                        ticker,
                        info.get("shortName", ""),
                        info.get("sector", ""),
                        info.get("industry", ""),
                        price,
                        day_change,
                        info.get("marketCap"),
                        info.get("trailingPE"),
                        info.get("dividendYield"),
                        info.get("beta"),
                        info.get("fiftyTwoWeekHigh"),
                        info.get("fiftyTwoWeekLow"),
                        now,
                    ),
                )
                updated += 1

            except Exception as e:
                logger.warning("Failed to fetch %s: %s", ticker, e)

        self.conn.commit()
        logger.info("Updated prices for %d/%d tickers", updated, len(tickers))
        return updated

    def refresh_benchmarks(self, period: str = "3mo") -> int:
        """Fetch benchmark index history and store in benchmark_data table.

        Returns number of data points stored.
        """
        total = 0
        for name, ticker in BENCHMARKS.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period=period)
                for idx, row in hist.iterrows():
                    d = idx.strftime("%Y-%m-%d")
                    self.conn.execute(
                        """INSERT INTO benchmark_data (ticker, date, close_price)
                           VALUES (?, ?, ?)
                           ON CONFLICT(ticker, date) DO UPDATE SET
                               close_price = excluded.close_price""",
                        (ticker, d, row["Close"]),
                    )
                    total += 1
            except Exception as e:
                logger.warning("Failed to fetch benchmark %s (%s): %s", name, ticker, e)

        self.conn.commit()
        logger.info("Stored %d benchmark data points", total)
        return total

    def get_market_summary(self) -> list[dict]:
        """Get latest benchmark prices for the weekly digest.

        Returns list of {name, ticker, price, change_pct} for major indices.
        """
        results = []
        tickers_to_fetch = list(BENCHMARKS.values())

        try:
            data = yf.Tickers(" ".join(tickers_to_fetch))
        except Exception as e:
            logger.error("Market summary fetch failed: %s", e)
            return results

        for name, ticker in BENCHMARKS.items():
            try:
                info = data.tickers[ticker].info
                price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
                change = info.get("regularMarketChangePercent", 0)
                results.append({
                    "name": name,
                    "ticker": ticker,
                    "price": price,
                    "change_pct": change,
                })
            except Exception:
                pass

        return results

    def get_cached_price(self, ticker: str) -> float | None:
        """Get the most recently cached price for a ticker."""
        row = self.conn.execute(
            "SELECT current_price FROM market_data WHERE ticker = ?", (ticker,)
        ).fetchone()
        return row["current_price"] if row else None

    def get_cached_market_data(self, ticker: str) -> dict | None:
        """Get all cached market data for a ticker."""
        row = self.conn.execute(
            "SELECT * FROM market_data WHERE ticker = ?", (ticker,)
        ).fetchone()
        return dict(row) if row else None

    def get_benchmark_return(self, ticker: str = "^GSPC", period_days: int = 365) -> float | None:
        """Calculate benchmark return over a period from cached data."""
        rows = self.conn.execute(
            """SELECT close_price, date FROM benchmark_data
               WHERE ticker = ?
               ORDER BY date DESC LIMIT ?""",
            (ticker, period_days),
        ).fetchall()

        if len(rows) < 2:
            return None

        latest = rows[0]["close_price"]
        earliest = rows[-1]["close_price"]
        if earliest == 0:
            return None
        return ((latest - earliest) / earliest) * 100
