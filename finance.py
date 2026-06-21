from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st
import yfinance as yf

import database


@dataclass
class QuoteResult:
    price: float | None
    currency: str
    source: str
    fetched_at: str | None = None
    error: str | None = None


@st.cache_data(ttl=300, show_spinner=False)
def _download_quote(symbol: str) -> tuple[float, str]:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="5d", interval="1d", auto_adjust=False)
    if history.empty or history["Close"].dropna().empty:
        raise ValueError("가격 데이터가 없습니다.")
    price = float(history["Close"].dropna().iloc[-1])
    currency = "USD" if symbol.upper() == "KRW=X" else str(ticker.fast_info.get("currency") or ("KRW" if symbol.upper().endswith((".KS", ".KQ")) else "USD"))
    return price, currency


def fetch_market_price(symbol: str, manual_price: float | None = None, db_path: str | Path | None = None) -> QuoteResult:
    symbol = symbol.strip().upper()
    if not symbol:
        return QuoteResult(manual_price, "KRW", "수동 입력", error=None if manual_price else "티커가 없습니다.")
    try:
        price, currency = _download_quote(symbol)
        database.upsert_price_cache(symbol, price, currency, db_path=db_path)
        return QuoteResult(price, currency, "Yahoo Finance")
    except Exception as exc:
        cached = database.get_cached_price(symbol, db_path)
        if cached:
            return QuoteResult(float(cached["price"]), str(cached["currency"]), "마지막 저장 가격", str(cached["fetched_at"]), str(exc))
        if manual_price is not None and manual_price > 0:
            currency = "KRW" if symbol.endswith((".KS", ".KQ")) else "USD"
            return QuoteResult(float(manual_price), currency, "수동 입력 가격", error=str(exc))
        return QuoteResult(None, "KRW", "조회 실패", error=str(exc))


def fetch_usd_krw(manual_rate: float | None = None, db_path: str | Path | None = None) -> QuoteResult:
    result = fetch_market_price("KRW=X", manual_rate, db_path)
    result.currency = "KRW/USD"
    return result
