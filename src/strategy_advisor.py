"""Debt vs invest optimizer and strategy advisor."""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import date

from config.portfolio_config import (
    CAR_BALANCE,
    CAR_LOAN_RATE,
    CAR_MONTHLY,
    CAR_TERM_REMAINING,
    IRA_ANNUAL_LIMIT,
    IRA_ACCOUNT,
    MORTGAGE_BALANCE,
    MORTGAGE_MONTHLY,
    MORTGAGE_RATE,
    MORTGAGE_TERM_REMAINING,
    ASSUMED_MARKET_RETURN,
)

logger = logging.getLogger(__name__)


class StrategyAdvisor:
    """Optimal allocation modeling for extra monthly cash."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def optimal_allocation(self, extra_monthly: float) -> dict:
        """Given $X extra per month, recommend priority allocation.

        Priority ladder:
        1. IRA max (tax advantage + market return > both loan rates)
        2. Car payoff (5.49% guaranteed > mortgage 3.625%)
        3. Taxable investing (~10% expected)
        4. Extra mortgage (3.625% guaranteed, lowest priority)

        Returns both the math-optimal and "sleep well" recommendations.
        """
        ira_ytd = self._ira_ytd()
        ira_remaining = max(0, IRA_ANNUAL_LIMIT - ira_ytd)
        months_left = 12 - date.today().month + 1
        ira_monthly_needed = ira_remaining / months_left if months_left > 0 else 0

        remaining = extra_monthly
        allocations = []

        # 1. IRA
        ira_alloc = min(remaining, ira_monthly_needed)
        if ira_alloc > 0:
            allocations.append({
                "destination": "Traditional IRA",
                "amount": ira_alloc,
                "reason": f"Tax-advantaged; ${ira_remaining:,.0f} left to max ${IRA_ANNUAL_LIMIT:,} limit",
                "effective_rate": f"~{ASSUMED_MARKET_RETURN*100:.0f}% expected + tax deferral",
                "priority": 1,
            })
            remaining -= ira_alloc

        # 2. Car payoff
        if remaining > 0 and CAR_BALANCE > 0:
            car_alloc = min(remaining, CAR_BALANCE / 12)  # Don't over-allocate
            allocations.append({
                "destination": "Extra car payment",
                "amount": car_alloc,
                "reason": f"5.49% guaranteed return; ${CAR_BALANCE:,.0f} remaining",
                "effective_rate": f"{CAR_LOAN_RATE*100:.2f}% guaranteed",
                "priority": 2,
            })
            remaining -= car_alloc

        # 3. Taxable investing
        if remaining > 0:
            invest_alloc = remaining * 0.8  # 80% to market
            mortgage_alloc = remaining * 0.2  # 20% to mortgage

            allocations.append({
                "destination": "Index fund investing",
                "amount": invest_alloc,
                "reason": f"Expected ~{ASSUMED_MARKET_RETURN*100:.0f}% long-term return",
                "effective_rate": f"~{ASSUMED_MARKET_RETURN*100:.0f}% expected (variable)",
                "priority": 3,
            })

            # 4. Extra mortgage
            if mortgage_alloc > 10:
                allocations.append({
                    "destination": "Extra mortgage principal",
                    "amount": mortgage_alloc,
                    "reason": f"3.625% guaranteed; ${MORTGAGE_BALANCE:,.0f} remaining",
                    "effective_rate": f"{MORTGAGE_RATE*100:.3f}% guaranteed",
                    "priority": 4,
                })

        # "Sleep well" alternative: pay off car aggressively
        sleep_well = []
        sw_remaining = extra_monthly
        if ira_alloc > 0:
            sleep_well.append({"destination": "Traditional IRA", "amount": ira_alloc})
            sw_remaining -= ira_alloc
        if sw_remaining > 0 and CAR_BALANCE > 0:
            sleep_well.append({"destination": "Extra car payment", "amount": sw_remaining})
        elif sw_remaining > 0:
            sleep_well.append({"destination": "Extra mortgage principal", "amount": sw_remaining})

        return {
            "extra_monthly": extra_monthly,
            "math_optimal": allocations,
            "sleep_well": sleep_well,
            "ira_ytd": ira_ytd,
            "ira_remaining": ira_remaining,
            "ira_monthly_needed": ira_monthly_needed,
        }

    def debt_freedom_projection(self) -> dict:
        """Project payoff dates for car and mortgage."""
        # Car payoff
        car_months_base = self._months_to_payoff(CAR_BALANCE, CAR_LOAN_RATE / 12, CAR_MONTHLY)

        # What if we add $500/mo extra?
        car_months_extra = self._months_to_payoff(CAR_BALANCE, CAR_LOAN_RATE / 12, CAR_MONTHLY + 500)

        # Mortgage payoff
        mort_months_base = self._months_to_payoff(MORTGAGE_BALANCE, MORTGAGE_RATE / 12, MORTGAGE_MONTHLY)
        mort_months_extra = self._months_to_payoff(MORTGAGE_BALANCE, MORTGAGE_RATE / 12, MORTGAGE_MONTHLY + 500)

        # Total interest saved
        car_interest_base = (CAR_MONTHLY * car_months_base) - CAR_BALANCE if car_months_base else 0
        car_interest_extra = ((CAR_MONTHLY + 500) * car_months_extra) - CAR_BALANCE if car_months_extra else 0
        car_interest_saved = car_interest_base - car_interest_extra

        return {
            "car": {
                "balance": CAR_BALANCE,
                "rate": CAR_LOAN_RATE,
                "monthly_payment": CAR_MONTHLY,
                "months_remaining": car_months_base,
                "months_with_extra_500": car_months_extra,
                "interest_saved_with_extra": car_interest_saved,
            },
            "mortgage": {
                "balance": MORTGAGE_BALANCE,
                "rate": MORTGAGE_RATE,
                "monthly_payment": MORTGAGE_MONTHLY,
                "months_remaining": mort_months_base,
                "months_with_extra_500": mort_months_extra,
            },
        }

    def ira_contribution_tracker(self) -> dict:
        """YTD IRA contributions vs annual limit."""
        ira_ytd = self._ira_ytd()
        remaining = max(0, IRA_ANNUAL_LIMIT - ira_ytd)
        months_left = 12 - date.today().month + 1
        monthly_needed = remaining / months_left if months_left > 0 else 0
        pct_complete = (ira_ytd / IRA_ANNUAL_LIMIT * 100) if IRA_ANNUAL_LIMIT > 0 else 0

        return {
            "ytd_contributions": ira_ytd,
            "annual_limit": IRA_ANNUAL_LIMIT,
            "remaining": remaining,
            "pct_complete": pct_complete,
            "months_left": months_left,
            "monthly_needed": monthly_needed,
        }

    def generate_strategy_note(self, surplus: float | None = None) -> str:
        """Plain-English recommendation for the current month."""
        if surplus is None:
            # Calculate from DB
            month = date.today().strftime("%Y-%m")
            income_row = self.conn.execute(
                "SELECT SUM(amount) as t FROM transactions WHERE month = ? AND tier1 = 'Income'",
                (month,),
            ).fetchone()
            spend_row = self.conn.execute(
                """SELECT SUM(ABS(amount)) as t FROM transactions
                   WHERE month = ? AND amount < 0
                     AND tier1 NOT IN ('Transfer', 'Income', 'Allocation')""",
                (month,),
            ).fetchone()
            income = income_row["t"] or 0
            spending = spend_row["t"] or 0
            surplus = income - spending

        if surplus <= 0:
            return f"No surplus this month (deficit: ${abs(surplus):,.0f}). Focus on reducing non-essential spending."

        alloc = self.optimal_allocation(surplus)
        parts = []
        for a in alloc["math_optimal"]:
            parts.append(f"${a['amount']:,.0f} → {a['destination']}")

        ira = alloc["ira_remaining"]
        car_proj = self.debt_freedom_projection()["car"]

        note = f"With ${surplus:,.0f} surplus: {', '.join(parts)}."
        if ira > 0:
            note += f" IRA: ${ira:,.0f} remaining to max."
        if car_proj["months_remaining"]:
            base_mo = car_proj["months_remaining"]
            note += f" Car payoff: {base_mo:.0f} months at current pace."

        return note

    def _ira_ytd(self) -> float:
        """Get YTD IRA contributions from transactions."""
        year = date.today().year
        row = self.conn.execute(
            """SELECT SUM(ABS(amount)) as total
               FROM transactions
               WHERE month LIKE ? AND tier1 = 'Allocation'
                 AND tier2 = 'IRA Contribution'""",
            (f"{year}-%",),
        ).fetchone()
        return row["total"] or 0

    @staticmethod
    def _months_to_payoff(balance: float, monthly_rate: float, monthly_payment: float) -> float | None:
        """Calculate months to pay off a loan."""
        if monthly_payment <= balance * monthly_rate:
            return None  # Payment doesn't cover interest
        if monthly_rate == 0:
            return balance / monthly_payment
        return -math.log(1 - (balance * monthly_rate / monthly_payment)) / math.log(1 + monthly_rate)
