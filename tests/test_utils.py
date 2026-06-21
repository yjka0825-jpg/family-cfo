from datetime import date

import pytest

from utils import calculate_position, cash_summary, goal_metrics


def test_partial_sale_uses_moving_average():
    trades = [
        {"id": 1, "trade_date": "2026-01-01", "trade_type": "매수", "quantity": 10, "total_amount_krw": 100_000},
        {"id": 2, "trade_date": "2026-02-01", "trade_type": "매수", "quantity": 10, "total_amount_krw": 200_000},
        {"id": 3, "trade_date": "2026-03-01", "trade_type": "매도", "quantity": 5, "total_amount_krw": 100_000},
    ]
    result = calculate_position(trades)
    assert result["quantity"] == 15
    assert result["cost_basis"] == pytest.approx(225_000)
    assert result["realized_profit"] == pytest.approx(25_000)


def test_cash_and_goal_edge_cases():
    summary = cash_summary(
        [{"tx_type": "입금", "amount": 700_000}, {"tx_type": "지출", "amount": 50_000}],
        [{"trade_type": "매수", "total_amount_krw": 200_000}, {"trade_type": "매도", "total_amount_krw": 80_000}],
    )
    assert summary["cash_balance"] == 530_000
    metrics = goal_metrics(1_000_000, 0, "2026-01-01", "2026-12-31", date(2026, 6, 1))
    assert metrics["expected_date"] is None


def test_oversell_is_rejected():
    with pytest.raises(ValueError):
        calculate_position([{"id": 1, "trade_date": "2026-01-01", "trade_type": "매도", "quantity": 1, "total_amount_krw": 10_000}])
