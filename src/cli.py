"""CLI commands: sync, backfill, recategorize, status, uncategorized, override, export, digest, alerts."""

import csv
import logging
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import click

# Add project root to path so config/src imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import DB_PATH, DEFAULT_SYNC_DAYS, EXCEL_PATH
from src.categorize import TransactionCategorizer
from src.db import (
    apply_override,
    get_all_accounts,
    get_connection,
    get_last_sync,
    get_monthly_summary,
    get_transaction_count,
    get_uncategorized,
    init_db,
    upsert_transaction,
)
from src.excel_writer import update_dashboard
from src.sync import run_daily_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """SpendSense — CLI tools."""
    pass


@cli.command()
@click.option("--days", default=DEFAULT_SYNC_DAYS, help="Days of history to fetch (max 90).")
@click.option("--no-excel", is_flag=True, help="Skip Excel dashboard update.")
def sync(days, no_excel):
    """Pull transactions from SimpleFIN, categorize, and store."""
    click.echo(f"Starting sync (last {days} days)...")
    try:
        result = run_daily_sync(days_back=days, update_excel=not no_excel)
        click.echo(
            f"Sync complete: {result['fetched']} fetched, "
            f"{result['new']} new, {result['updated']} updated"
        )
        if result["errors"]:
            click.echo(f"Warnings: {result['errors']}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Sync failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--file", "csv_file", required=True, type=click.Path(exists=True), help="CSV file to import.")
@click.option("--account", required=True, help="Account friendly name (e.g. 'Primary Checking').")
@click.option("--account-id", default=None, help="SimpleFIN account ID (auto-generated if not provided).")
def backfill(csv_file, account, account_id):
    """Import historical transactions from a CSV file."""
    init_db()
    conn = get_connection()
    categorizer = TransactionCategorizer()

    aid = account_id or f"csv-import:{account.lower().replace(' ', '-')}"
    new_count = 0

    click.echo(f"Importing from {csv_file} into account '{account}'...")

    with open(csv_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try common CSV column names
            date_str = row.get("Date") or row.get("date") or row.get("Posted Date", "")
            desc = row.get("Description") or row.get("description") or row.get("Memo", "")
            amount_str = row.get("Amount") or row.get("amount") or "0"

            if not date_str or not desc:
                continue

            # Parse date (try common formats)
            posted_date = None
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y"):
                try:
                    posted_date = datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            if not posted_date:
                logger.warning("Could not parse date: %s", date_str)
                continue

            amount = float(Decimal(amount_str.replace(",", "").replace("$", "").strip()))
            month = posted_date[:7]
            txn_id = f"{aid}:{posted_date}:{desc[:30]}:{amount}"

            category = categorizer.categorize(desc, amount)

            result = upsert_transaction(conn, {
                "id": txn_id,
                "account_id": aid,
                "posted_at": posted_date,
                "amount": amount,
                "description": desc,
                "pending": 0,
                "tier1": category["tier1"],
                "tier2": category["tier2"],
                "vendor": category["vendor"],
                "auto_categorized": 1,
                "month": month,
            })
            if result == "new":
                new_count += 1

    conn.commit()
    conn.close()
    click.echo(f"Imported {new_count} new transactions.")


@cli.command()
def recategorize():
    """Re-run categorization rules on all auto-categorized transactions."""
    init_db()
    conn = get_connection()
    categorizer = TransactionCategorizer()

    click.echo("Re-categorizing transactions...")
    result = categorizer.recategorize_all(conn)
    conn.close()
    click.echo(f"Updated {result['updated']} transactions ({result['skipped']} overrides skipped).")


@cli.command()
def status():
    """Show sync status, account info, and transaction counts."""
    init_db()
    conn = get_connection()

    # Last sync
    last = get_last_sync(conn)
    if last:
        click.echo(f"Last sync: {last['completed_at'] or last['started_at']} ({last['status']})")
        click.echo(
            f"  Fetched: {last['transactions_fetched']}, "
            f"New: {last['transactions_new']}, "
            f"Updated: {last['transactions_updated']}"
        )
    else:
        click.echo("No syncs recorded yet.")

    # Transaction counts
    total = get_transaction_count(conn)
    uncat = get_uncategorized(conn)
    click.echo(f"\nTotal transactions: {total}")
    click.echo(f"Uncategorized: {len(uncat)}")

    # Accounts
    accounts = get_all_accounts(conn)
    if accounts:
        click.echo(f"\nAccounts ({len(accounts)}):")
        for acct in accounts:
            friendly = acct["friendly_name"] or acct["name"]
            click.echo(f"  {acct['institution']} — {friendly} [{acct['id'][:20]}...]")
    else:
        click.echo("\nNo accounts synced yet.")

    # DB info
    click.echo(f"\nDatabase: {DB_PATH}")
    click.echo(f"Excel: {EXCEL_PATH}")

    conn.close()


@cli.command()
def uncategorized():
    """Show uncategorized transactions for manual review."""
    init_db()
    conn = get_connection()
    items = get_uncategorized(conn)
    conn.close()

    if not items:
        click.echo("All transactions are categorized!")
        return

    click.echo(f"Uncategorized transactions ({len(items)}):\n")
    for txn in items:
        click.echo(
            f"  {txn['posted_at']}  ${abs(txn['amount']):>9.2f}  "
            f"{txn['description'][:50]:<50}  [{txn['id'][:20]}...]"
        )


@cli.command()
@click.option("--txn-id", required=True, help="Transaction ID to override.")
@click.option("--tier1", required=True, help="Category tier 1.")
@click.option("--tier2", required=True, help="Category tier 2.")
@click.option("--vendor", default=None, help="Vendor name.")
@click.option("--reason", default=None, help="Reason for override.")
def override(txn_id, tier1, tier2, vendor, reason):
    """Apply a manual category override to a transaction."""
    init_db()
    conn = get_connection()
    apply_override(conn, txn_id, tier1, tier2, vendor, reason)
    conn.close()
    click.echo(f"Override applied: {txn_id} → {tier1} / {tier2}")


@cli.command(name="export")
@click.option("--month", default=None, help="Month to export (YYYY-MM). Defaults to current month.")
def export_cmd(month):
    """Export data to the Excel dashboard."""
    if month is None:
        month = datetime.now().strftime("%Y-%m")

    init_db()
    conn = get_connection()

    # Show summary
    summary = get_monthly_summary(conn, month)
    if not summary:
        click.echo(f"No data for {month}.")
        conn.close()
        return

    click.echo(f"Monthly summary for {month}:\n")
    click.echo(f"  {'Category':<30} {'Count':>5} {'Total':>10}")
    click.echo(f"  {'-' * 47}")
    for row in summary:
        t1 = row["tier1"] or "?"
        t2 = row["tier2"] or "?"
        click.echo(f"  {t1 + ' / ' + t2:<30} {row['count']:>5} ${row['total']:>9.2f}")

    # Update Excel
    click.echo(f"\nUpdating Excel dashboard at {EXCEL_PATH}...")
    update_dashboard(conn)
    click.echo("Done.")

    conn.close()


@cli.command()
@click.option("--month", default=None, help="Month to summarize (YYYY-MM). Defaults to current month.")
def summary(month):
    """Show monthly spending summary by category."""
    if month is None:
        month = datetime.now().strftime("%Y-%m")

    init_db()
    conn = get_connection()
    data = get_monthly_summary(conn, month)
    conn.close()

    if not data:
        click.echo(f"No data for {month}.")
        return

    click.echo(f"Summary for {month}:\n")
    current_tier1 = None
    tier1_total = 0.0

    for row in data:
        if row["tier1"] != current_tier1:
            if current_tier1 is not None:
                click.echo(f"  {'SUBTOTAL':<26} ${tier1_total:>9.2f}")
                click.echo()
            current_tier1 = row["tier1"]
            tier1_total = 0.0
            click.echo(f"  [{current_tier1}]")

        tier1_total += row["total"]
        click.echo(f"    {row['tier2']:<24} ${row['total']:>9.2f}  ({row['count']} txns)")

    if current_tier1 is not None:
        click.echo(f"  {'SUBTOTAL':<26} ${tier1_total:>9.2f}")


@cli.command()
@click.option("--week-end", default=None, help="Week ending date (YYYY-MM-DD, Sunday). Defaults to last Sunday.")
@click.option("--preview", is_flag=True, help="Preview digest in terminal without sending email.")
def digest(week_end, preview):
    """Generate and send the weekly Monday Money Brief digest."""
    from src.email_digest import WeeklyDigest
    from src.email_sender import send_digest

    init_db()
    conn = get_connection()

    we = None
    if week_end:
        we = date.fromisoformat(week_end)

    digest_gen = WeeklyDigest(conn)
    result = digest_gen.generate(week_end=we)
    data = result["data"]

    if preview:
        click.echo(f"\n{'━' * 60}")
        click.echo(f"  MONDAY MONEY BRIEF — Week of {data['week_start']} to {data['week_end']}")
        click.echo(f"{'━' * 60}")

        click.echo(f"\n  WEEKLY SNAPSHOT")
        click.echo(f"  Spent this week:    ${data['this_week_total']:>10,.2f}")
        click.echo(f"  Spent last week:    ${data['last_week_total']:>10,.2f}")
        click.echo(f"  WoW change:         {data['wow_delta']:>+9.0f}%")
        click.echo(f"  MTD spending:       ${data['mtd_spending']:>10,.2f}")
        click.echo(f"  Same point prev mo: ${data['prev_mtd']:>10,.2f}")
        click.echo(f"  MoM pace change:    {data['mom_delta']:>+9.0f}%")

        click.echo(f"\n  CASH FLOW CHECK")
        click.echo(f"  {data['current_month_name']} income:     ${data['mtd_income']:>10,.2f}")
        click.echo(f"  {data['current_month_name']} spending:   ${data['mtd_spending']:>10,.2f}")
        click.echo(f"  Projected surplus:  ${data['projected_surplus']:>10,.2f}")
        click.echo(f"  Verdict:            {data['verdict']}")

        if data["categories"]:
            click.echo(f"\n  SPENDING BY CATEGORY (this week)")
            click.echo(f"  {'Category':<25} {'Week':>8} {'MTD':>8} {'Prev Mo':>8} {'Trend':>5}")
            click.echo(f"  {'─' * 56}")
            for cat in data["categories"]:
                click.echo(
                    f"  {cat['name']:<25} ${cat['this_week']:>7,.0f} "
                    f"${cat['mtd']:>7,.0f} ${cat['last_month']:>7,.0f}   {cat['trend']}"
                )

        if data["alerts"]:
            click.echo(f"\n  ⚠️  ALERTS ({len(data['alerts'])})")
            for alert in data["alerts"]:
                click.echo(f"  {alert.emoji} {alert.alert_type}: {alert.message}")
                if alert.details:
                    click.echo(f"     {alert.details}")

        if data["allocations"]:
            click.echo(f"\n  ALLOCATIONS")
            for name, total in data["allocations"].items():
                click.echo(f"  {name:<25} ${total:>8,.0f}")
            click.echo(f"  IRA YTD:               ${data['ira_ytd']:>8,.0f} / $7,000")

        click.echo(f"\n{'━' * 60}")
        click.echo(f"  Primary subject: {result['primary']['subject']}")
        click.echo(f"  Secondary subject: {result['secondary']['subject']}")
        click.echo(f"  (Preview mode — no emails sent)")
        click.echo(f"{'━' * 60}\n")

        # Save HTML previews to logs/
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        for who in ["primary", "secondary"]:
            path = log_dir / f"digest_preview_{who}.html"
            path.write_text(result[who]["html"])
            click.echo(f"  HTML preview saved: {path}")

    else:
        primary_email = os.getenv("EMAIL_PRIMARY")
        secondary_email = os.getenv("EMAIL_SECONDARY")
        if not primary_email or not secondary_email:
            click.echo("Error: EMAIL_PRIMARY and EMAIL_SECONDARY must be set in .env", err=True)
            sys.exit(1)

        click.echo(f"Sending digest for week ending {data['week_end']}...")
        results = send_digest(primary_email, secondary_email, result["primary"], result["secondary"])
        for who, ok in results.items():
            status = "✓ sent" if ok else "✗ FAILED"
            click.echo(f"  {who}: {status}")

    conn.close()


@cli.command()
@click.option("--week-end", default=None, help="Week ending date (YYYY-MM-DD). Defaults to last Sunday.")
def alerts(week_end):
    """Run the alert engine and display results (no email)."""
    from src.alerts import AlertEngine

    init_db()
    conn = get_connection()

    if week_end:
        we = date.fromisoformat(week_end)
    else:
        today = date.today()
        we = today - timedelta(days=(today.weekday() + 1) % 7)
        if we == today:
            we -= timedelta(days=7)

    ws = we - timedelta(days=6)

    engine = AlertEngine(conn)
    result = engine.run(ws, we)

    if not result:
        click.echo("No alerts for this period.")
    else:
        click.echo(f"\n⚠️  {len(result)} alert(s) for {ws} to {we}:\n")
        for alert in result:
            click.echo(f"  {alert.emoji} [{alert.label}] {alert.alert_type}: {alert.message}")
            if alert.details:
                click.echo(f"     {alert.details}")

    conn.close()


@cli.group()
def portfolio():
    """Investment portfolio commands."""
    pass


@portfolio.command(name="import")
@click.option("--file", "csv_file", required=True, type=click.Path(exists=True), help="Brokerage CSV export.")
def portfolio_import(csv_file):
    """Import holdings from a brokerage CSV export."""
    from src.brokerage_import import import_brokerage_csv

    init_db()
    conn = get_connection()
    result = import_brokerage_csv(conn, csv_file)
    conn.close()
    click.echo(f"Imported {result['imported']} holdings ({result['skipped']} skipped)")
    if result["errors"]:
        for e in result["errors"]:
            click.echo(f"  ⚠ {e}")


@portfolio.command(name="init-from-dividends")
def portfolio_init_dividends():
    """Build preliminary holdings from dividend transaction history."""
    from config.portfolio_config import KNOWN_TICKERS
    from src.brokerage_import import build_holdings_from_dividends

    init_db()
    conn = get_connection()
    result = build_holdings_from_dividends(conn, KNOWN_TICKERS)
    conn.close()
    click.echo(f"Created {result['created']} holdings from dividend history ({result['already_exists']} already existed)")
    click.echo("⚠ Share counts are 0 — update manually or import CSV when available")


@portfolio.command(name="refresh")
def portfolio_refresh():
    """Refresh market prices for all holdings + benchmarks."""
    from src.brokerage_import import init_portfolio_schema
    from src.market_data import MarketDataService

    init_db()
    conn = get_connection()
    init_portfolio_schema(conn)
    market = MarketDataService(conn)

    click.echo("Refreshing market prices...")
    updated = market.refresh_holdings_prices()
    click.echo(f"  Updated {updated} ticker prices")

    click.echo("Refreshing benchmarks...")
    points = market.refresh_benchmarks()
    click.echo(f"  Stored {points} benchmark data points")

    conn.close()


@portfolio.command(name="summary")
@click.option("--account", default=None, help="Filter by account name.")
def portfolio_summary(account):
    """Show portfolio summary with holdings detail."""
    from src.brokerage_import import init_portfolio_schema
    from src.market_data import MarketDataService
    from src.portfolio_analyzer import PortfolioAnalyzer

    init_db()
    conn = get_connection()
    init_portfolio_schema(conn)
    analyzer = PortfolioAnalyzer(conn)
    s = analyzer.get_portfolio_summary(account=account)

    if s["has_estimates"]:
        click.echo("⚠ Some holdings have estimated data (shares=0). Import CSV or update manually.\n")

    click.echo(f"{'PORTFOLIO SUMMARY':^60}")
    click.echo(f"{'─' * 60}")
    click.echo(f"  Total Value:      ${s['total_value']:>12,.2f}")
    click.echo(f"  Cost Basis:       ${s['total_cost_basis']:>12,.2f}")
    click.echo(f"  Gain/Loss:        ${s['total_gain_loss']:>12,.2f} ({s['total_return_pct']:+.1f}%)")
    click.echo(f"\n  {'Ticker':<8} {'Shares':>8} {'Price':>8} {'Value':>10} {'G/L':>10} {'G/L%':>7} {'Wt%':>6} {'Sector'}")
    click.echo(f"  {'─' * 75}")

    for h in s["holdings"]:
        est = "*" if h["estimated"] else " "
        click.echo(
            f"  {h['ticker']:<7}{est} {h['shares']:>8.2f} ${h['current_price']:>7.2f} "
            f"${h['market_value']:>9,.2f} ${h['gain_loss']:>9,.2f} {h['gain_loss_pct']:>+6.1f}% "
            f"{h['weight_pct']:>5.1f}% {h['sector'][:15]}"
        )

    conn.close()


@portfolio.command(name="allocation")
def portfolio_allocation():
    """Show sector and account allocation breakdown."""
    from src.brokerage_import import init_portfolio_schema
    from src.portfolio_analyzer import PortfolioAnalyzer

    init_db()
    conn = get_connection()
    init_portfolio_schema(conn)
    analyzer = PortfolioAnalyzer(conn)
    alloc = analyzer.get_allocation_breakdown()

    click.echo(f"\n  ALLOCATION BY SECTOR (${alloc['total_value']:,.0f} total)")
    click.echo(f"  {'─' * 40}")
    for sector, pct in alloc["by_sector"].items():
        bar = "█" * int(pct / 2)
        click.echo(f"  {sector:<20} {pct:>5.1f}% {bar}")

    click.echo(f"\n  ALLOCATION BY ACCOUNT")
    click.echo(f"  {'─' * 40}")
    for acct, pct in alloc["by_account"].items():
        click.echo(f"  {acct:<30} {pct:>5.1f}%")

    if alloc["concentration_alerts"]:
        click.echo(f"\n  ⚠ CONCENTRATION RISK")
        for a in alloc["concentration_alerts"]:
            click.echo(f"  {a['ticker']}: {a['weight_pct']:.1f}% — {a['risk']}")

    conn.close()


@portfolio.command(name="ira")
def portfolio_ira():
    """Show IRA contribution progress."""
    from src.strategy_advisor import StrategyAdvisor

    init_db()
    conn = get_connection()
    advisor = StrategyAdvisor(conn)
    ira = advisor.ira_contribution_tracker()
    conn.close()

    bar_len = 30
    filled = int(ira["pct_complete"] / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    click.echo(f"\n  IRA CONTRIBUTION TRACKER — {date.today().year}")
    click.echo(f"  {'─' * 45}")
    click.echo(f"  [{bar}] {ira['pct_complete']:.1f}%")
    click.echo(f"  YTD:           ${ira['ytd_contributions']:>8,.0f}")
    click.echo(f"  Limit:         ${ira['annual_limit']:>8,}")
    click.echo(f"  Remaining:     ${ira['remaining']:>8,.0f}")
    click.echo(f"  Months left:   {ira['months_left']}")
    click.echo(f"  Need/month:    ${ira['monthly_needed']:>8,.0f}")


@portfolio.command(name="report")
def portfolio_report():
    """Full portfolio + strategy report."""
    from src.brokerage_import import init_portfolio_schema
    from src.portfolio_analyzer import PortfolioAnalyzer
    from src.strategy_advisor import StrategyAdvisor

    init_db()
    conn = get_connection()
    init_portfolio_schema(conn)
    analyzer = PortfolioAnalyzer(conn)
    advisor = StrategyAdvisor(conn)

    # Summary
    s = analyzer.get_portfolio_summary()
    click.echo(f"\n{'═' * 60}")
    click.echo(f"  PORTFOLIO REPORT — {date.today().strftime('%B %d, %Y')}")
    click.echo(f"{'═' * 60}")
    click.echo(f"  Total Value: ${s['total_value']:,.2f}  |  Return: {s['total_return_pct']:+.1f}%")

    # Performance vs benchmark
    perf = analyzer.get_performance_vs_benchmark()
    click.echo(f"\n  VS BENCHMARK")
    click.echo(f"  Portfolio: {perf['portfolio_return_pct']:+.1f}%  |  S&P 500: {perf['spy_return_pct']:+.1f}%  |  Alpha: {perf['alpha']:+.1f}%")

    # Dividends
    divs = analyzer.get_dividend_summary()
    click.echo(f"\n  DIVIDEND INCOME")
    click.echo(f"  Annual estimate: ${divs['annual_estimate']:,.0f}  |  Monthly: ${divs['monthly_average']:,.0f}  |  Yield: {divs['yield_on_cost']:.1f}%")

    # IRA
    ira = advisor.ira_contribution_tracker()
    click.echo(f"\n  IRA: ${ira['ytd_contributions']:,.0f} / ${ira['annual_limit']:,} ({ira['pct_complete']:.0f}%) — ${ira['monthly_needed']:,.0f}/mo to max")

    # Debt projection
    debt = advisor.debt_freedom_projection()
    car = debt["car"]
    if car["months_remaining"]:
        click.echo(f"\n  CAR PAYOFF: {car['months_remaining']:.0f} months at ${car['monthly_payment']}/mo | +$500/mo → {car['months_with_extra_500']:.0f} months")

    # Strategy note
    note = advisor.generate_strategy_note()
    click.echo(f"\n  STRATEGY: {note}")
    click.echo(f"{'═' * 60}\n")

    conn.close()


@cli.command()
@click.option("--extra", required=True, type=float, help="Extra monthly dollars to allocate.")
def strategy(extra):
    """Run the debt vs invest optimizer for a given monthly surplus."""
    from src.strategy_advisor import StrategyAdvisor

    init_db()
    conn = get_connection()
    advisor = StrategyAdvisor(conn)
    result = advisor.optimal_allocation(extra)

    click.echo(f"\n  STRATEGY ADVISOR — ${extra:,.0f}/month extra")
    click.echo(f"  {'─' * 50}")

    click.echo(f"\n  📊 MATH-OPTIMAL ALLOCATION:")
    for a in result["math_optimal"]:
        click.echo(f"  {a['priority']}. ${a['amount']:>8,.0f} → {a['destination']}")
        click.echo(f"     {a['reason']}")
        click.echo(f"     Rate: {a['effective_rate']}")

    click.echo(f"\n  😴 SLEEP-WELL ALTERNATIVE:")
    for a in result["sleep_well"]:
        click.echo(f"     ${a['amount']:>8,.0f} → {a['destination']}")

    click.echo(f"\n  IRA: ${result['ira_ytd']:,.0f} contributed YTD, ${result['ira_remaining']:,.0f} remaining")
    if result["ira_monthly_needed"] > 0:
        click.echo(f"       Need ${result['ira_monthly_needed']:,.0f}/mo to max by December")

    conn.close()


if __name__ == "__main__":
    cli()
