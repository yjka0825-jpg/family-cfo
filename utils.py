from __future__ import annotations

import calendar
import html
from datetime import date, datetime, timedelta
from typing import Any, Iterable


def format_won(value: float | int | None) -> str:
    return f"{round(value or 0):,}원"


def format_percent(value: float | int | None) -> str:
    return f"{(value or 0):+.1f}%"


def calculate_position(trades: Iterable[dict[str, Any]]) -> dict[str, float]:
    quantity = 0.0
    cost_basis = 0.0
    realized_profit = 0.0
    for trade in sorted(trades, key=lambda x: (str(x["trade_date"]), int(x.get("id", 0)))):
        qty = float(trade["quantity"])
        total = float(trade["total_amount_krw"])
        if trade["trade_type"] == "매수":
            quantity += qty
            cost_basis += total
        else:
            if qty > quantity + 1e-9:
                raise ValueError("보유수량보다 많이 매도할 수 없습니다.")
            average_cost = cost_basis / quantity if quantity else 0
            sold_cost = average_cost * qty
            realized_profit += total - sold_cost
            quantity -= qty
            cost_basis -= sold_cost
            if abs(quantity) < 1e-9:
                quantity = 0.0
                cost_basis = 0.0
    return {
        "quantity": quantity,
        "cost_basis": cost_basis,
        "average_cost_krw": cost_basis / quantity if quantity else 0.0,
        "realized_profit": realized_profit,
    }


def cash_summary(cash_transactions: Iterable[dict[str, Any]], investment_transactions: Iterable[dict[str, Any]]) -> dict[str, float]:
    deposits = sum(float(x["amount"]) for x in cash_transactions if x["tx_type"] == "입금")
    expenses = sum(float(x["amount"]) for x in cash_transactions if x["tx_type"] == "지출")
    buys = sum(float(x["total_amount_krw"]) for x in investment_transactions if x["trade_type"] == "매수")
    sells = sum(float(x["total_amount_krw"]) for x in investment_transactions if x["trade_type"] == "매도")
    return {"deposits": deposits, "expenses": expenses, "buys": buys, "sells": sells, "cash_balance": deposits - expenses - buys + sells}


def goal_metrics(target_amount: float, current_amount: float, start_date: date | str, target_date: date | str, today: date | None = None) -> dict[str, Any]:
    start = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
    target_day = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date
    now = today or date.today()
    remaining = max(float(target_amount) - float(current_amount), 0)
    progress = float(current_amount) / float(target_amount) * 100 if target_amount else 0
    months_left = max((target_day - now).days / 30.4375, 0)
    monthly_needed = remaining / months_left if months_left > 0 else (0 if remaining == 0 else None)
    elapsed_months = max((now - start).days / 30.4375, 0)
    monthly_pace = float(current_amount) / elapsed_months if elapsed_months > 0 and current_amount > 0 else None
    expected_date = None
    if remaining == 0:
        expected_date = now
    elif monthly_pace and monthly_pace > 0:
        expected_date = now + timedelta(days=round((remaining / monthly_pace) * 30.4375))
    return {"progress": progress, "remaining": remaining, "monthly_needed": monthly_needed, "monthly_pace": monthly_pace, "expected_date": expected_date}


def month_calendar_html(events: list[dict[str, Any]], year: int, month: int) -> str:
    by_day: dict[int, list[str]] = {}
    for event in events:
        event_date = date.fromisoformat(str(event["event_date"]))
        if event_date.year == year and event_date.month == month:
            by_day.setdefault(event_date.day, []).append(str(event["title"]))
    cal = calendar.Calendar(firstweekday=0)
    rows = []
    for week in cal.monthdayscalendar(year, month):
        cells = []
        for day in week:
            if day == 0:
                cells.append("<td class='empty'></td>")
            else:
                items = "".join(f"<div class='event-dot'>{html.escape(title)}</div>" for title in by_day.get(day, []))
                cells.append(f"<td><b>{day}</b>{items}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"""
    <style>
      .family-calendar {{width:100%; border-collapse:separate; border-spacing:4px; table-layout:fixed}}
      .family-calendar th {{color:#667085; font-size:.78rem; padding:5px}}
      .family-calendar td {{height:78px; vertical-align:top; padding:7px; border-radius:10px; background:#f7f8fa; font-size:.8rem}}
      .family-calendar .empty {{background:transparent}}
      .event-dot {{margin-top:4px; padding:3px 5px; border-radius:6px; background:#e8f1ff; color:#2356a8; overflow:hidden; white-space:nowrap; text-overflow:ellipsis}}
      @media(max-width:600px) {{.family-calendar td{{height:58px;padding:4px;font-size:.7rem}} .event-dot{{font-size:.62rem;padding:2px}}}}
    </style>
    <table class="family-calendar"><thead><tr>{''.join(f'<th>{d}</th>' for d in ['월','화','수','목','금','토','일'])}</tr></thead><tbody>{''.join(rows)}</tbody></table>
    """
