from __future__ import annotations

import hmac
import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

import database as db
from finance import fetch_market_price, fetch_usd_krw
from utils import calculate_position, cash_summary, format_percent, format_won, goal_metrics, month_calendar_html


st.set_page_config(page_title="Family CFO", page_icon="🏡", layout="wide", initial_sidebar_state="collapsed")


def require_family_password() -> None:
    try:
        expected_password = str(st.secrets["APP_PASSWORD"])
    except (FileNotFoundError, KeyError):
        expected_password = os.getenv("APP_PASSWORD", "")

    if not expected_password:
        st.error("앱 비밀번호가 설정되지 않았습니다. 관리자에게 알려주세요.")
        st.stop()
    if st.session_state.get("family_authenticated"):
        return

    st.title("🔒 Family CFO")
    st.caption("우리 가족 전용 앱입니다")
    with st.form("family_login"):
        entered_password = st.text_input("가족 비밀번호", type="password", placeholder="비밀번호 4자리")
        submitted = st.form_submit_button("들어가기", use_container_width=True)
    if submitted:
        if hmac.compare_digest(entered_password, expected_password):
            st.session_state["family_authenticated"] = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    st.stop()


require_family_password()
db.initialize_database()
db.remove_initial_demo_data()

MEMBERS = db.MEMBERS
DEPOSIT_CATEGORIES = ["가족여행", "부모님 지원", "경조사", "투자금", "기타"]
EXPENSE_CATEGORIES = ["식사", "여행", "병원", "선물", "경조사", "생활비", "기타"]
MARKETS = ["한국주식", "미국주식", "ETF", "예금", "채권", "기타"]
MANUAL_MARKETS = {"예금", "채권", "기타"}


st.markdown(
    """
    <style>
      .block-container {max-width: 1180px; padding-top: 1.3rem; padding-bottom: 4rem}
      h1 {font-size: 1.75rem !important; letter-spacing: -.04em}
      h2, h3 {letter-spacing: -.03em}
      [data-testid="stMetric"] {background:#fff; border:1px solid #edf0f4; padding:16px; border-radius:16px; box-shadow:0 3px 14px rgba(28,39,60,.04)}
      [data-testid="stMetricLabel"] {font-size:.88rem}
      [data-testid="stMetricValue"] {font-size:1.45rem}
      .soft-card {background:#f7f8fa; border-radius:16px; padding:15px 17px; margin:8px 0}
      .eyebrow {color:#667085; font-size:.82rem; margin-bottom:3px}
      .big-number {font-size:1.55rem; font-weight:750; letter-spacing:-.04em}
      .positive {color:#e5484d}.negative {color:#2563eb}
      div[data-testid="stForm"] {border:1px solid #edf0f4; border-radius:16px; padding:16px}
      .stButton button, .stFormSubmitButton button {border-radius:12px; font-weight:650; min-height:42px}
      @media(max-width: 640px) {
        .block-container {padding: .9rem .85rem 4rem}
        h1 {font-size:1.5rem !important}
        [data-testid="stMetric"] {padding:12px}
        [data-testid="stMetricValue"] {font-size:1.18rem}
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def records(name: str, order_by: str = "id DESC") -> list[dict]:
    return db.table(name, order_by)


def all_financials() -> tuple[list[dict], list[dict], dict]:
    cash = records("cash_transactions", "tx_date DESC, id DESC")
    trades = records("investment_transactions", "trade_date DESC, id DESC")
    return cash, trades, cash_summary(cash, trades)


def portfolio_data() -> tuple[pd.DataFrame, list[str], object | None]:
    assets = records("investment_assets", "id ASC")
    trades = records("investment_transactions", "trade_date ASC, id ASC")
    trade_map: dict[int, list[dict]] = {}
    for trade in trades:
        trade_map.setdefault(int(trade["asset_id"]), []).append(trade)
    needs_fx = any(a["currency"] == "USD" for a in assets)
    fx_result = fetch_usd_krw(1_400) if needs_fx else None
    fx = float(fx_result.price) if fx_result and fx_result.price else 1_400.0
    warnings: list[str] = []
    rows = []
    for asset in assets:
        position = calculate_position(trade_map.get(int(asset["id"]), []))
        quantity = position["quantity"]
        price = None
        price_source = "수동 평가"
        if asset["market_type"] in MANUAL_MARKETS:
            current_value = float(asset["manual_current_value"] or position["cost_basis"])
        else:
            quote = fetch_market_price(str(asset["ticker"]), asset["manual_current_price"])
            price = quote.price
            price_source = quote.source
            if quote.error:
                warnings.append(f'{asset["asset_name"]}: 실시간 조회 실패, {quote.source} 사용')
            rate = fx if asset["currency"] == "USD" else 1.0
            current_value = quantity * float(price or 0) * rate
        principal = position["cost_basis"]
        profit = current_value - principal
        return_rate = profit / principal * 100 if principal else 0
        rows.append(
            {
                "asset_id": int(asset["id"]), "상품명": asset["asset_name"], "티커": asset["ticker"],
                "시장": asset["market_type"], "통화": asset["currency"], "보유수량": quantity,
                "현재가": price, "투자원금": principal, "평가금액": current_value,
                "평가손익": profit, "수익률": return_rate, "가격기준": price_source,
                "실현손익": position["realized_profit"],
            }
        )
    return pd.DataFrame(rows), list(dict.fromkeys(warnings)), fx_result


def top_title(title: str, subtitle: str) -> None:
    st.title(title)
    st.caption(subtitle)


def render_home() -> None:
    top_title("🏡 우리 가족 CFO", "가족의 돈과 중요한 일을 한눈에 확인하세요")
    cash, _, summary = all_financials()
    portfolio, warnings, _ = portfolio_data()
    invested = float(portfolio["투자원금"].sum()) if not portfolio.empty else 0
    evaluated = float(portfolio["평가금액"].sum()) if not portfolio.empty else 0
    profit = evaluated - invested
    total_assets = summary["cash_balance"] + evaluated
    goals = records("goals", "target_date ASC")
    target_sum = sum(float(g["target_amount"]) for g in goals)
    current_sum = sum(float(g["current_amount"]) for g in goals)
    goal_rate = current_sum / target_sum * 100 if target_sum else 0
    month_prefix = date.today().strftime("%Y-%m")
    month_deposit = sum(float(x["amount"]) for x in cash if x["tx_type"] == "입금" and str(x["tx_date"]).startswith(month_prefix))
    month_expense = sum(float(x["amount"]) for x in cash if x["tx_type"] == "지출" and str(x["tx_date"]).startswith(month_prefix))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 가족자산", format_won(total_assets))
    c2.metric("쓸 수 있는 현금", format_won(summary["cash_balance"]))
    c3.metric("투자 결과", format_won(profit), format_percent(profit / invested * 100 if invested else 0))
    c4.metric("목표 달성률", f"{goal_rate:.1f}%")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("투자 원금", format_won(invested))
    c2.metric("현재 투자금", format_won(evaluated))
    c3.metric("이번 달 입금", format_won(month_deposit))
    c4.metric("이번 달 지출", format_won(month_expense))
    for message in warnings:
        st.warning(message, icon="⚠️")

    left, right = st.columns([1.05, .95])
    with left:
        st.subheader("다가오는 가족 일정")
        today = date.today().isoformat()
        events = db.fetch_all("SELECT * FROM events WHERE event_date >= ? ORDER BY event_date, event_time LIMIT 5", (today,))
        if not events:
            st.info("예정된 일정이 없어요.")
        for event in events:
            st.markdown(f'<div class="soft-card"><div class="eyebrow">{event["event_date"]} {event["event_time"]} · {event["event_type"]}</div><b>{event["title"]}</b><br><small>{event["participants"]}</small></div>', unsafe_allow_html=True)
    with right:
        st.subheader("최근 거래")
        if not cash:
            st.info("아직 거래가 없어요.")
        for tx in cash[:5]:
            sign = "+" if tx["tx_type"] == "입금" else "−"
            st.markdown(f'<div class="soft-card"><div class="eyebrow">{tx["tx_date"]} · {tx["member_name"]}</div><b>{tx["category"]}</b><span style="float:right;font-weight:700">{sign}{format_won(tx["amount"])}</span></div>', unsafe_allow_html=True)

    st.subheader("최근 투자 변동")
    trades = db.fetch_all("""SELECT t.*, a.asset_name FROM investment_transactions t JOIN investment_assets a ON a.id=t.asset_id ORDER BY t.trade_date DESC, t.id DESC LIMIT 5""")
    if trades:
        st.dataframe(pd.DataFrame(trades)[["trade_date", "asset_name", "trade_type", "quantity", "total_amount_krw"]].rename(columns={"trade_date":"날짜","asset_name":"상품","trade_type":"구분","quantity":"수량","total_amount_krw":"원화금액"}), use_container_width=True, hide_index=True)


def render_cash() -> None:
    top_title("💰 공동자금", "입금과 가족 지출을 간단하게 기록하세요")
    cash, trades, summary = all_financials()
    c1, c2, c3 = st.columns(3)
    c1.metric("총 입금", format_won(summary["deposits"]))
    c2.metric("총 지출", format_won(summary["expenses"]))
    c3.metric("현재 현금", format_won(summary["cash_balance"]))
    deposit_tab, expense_tab = st.tabs(["입금 기록", "지출 기록"])
    with deposit_tab:
        with st.form("deposit_form", clear_on_submit=True):
            cols = st.columns(2)
            tx_date = cols[0].date_input("날짜", date.today(), key="deposit_date")
            member = cols[1].selectbox("입금자", MEMBERS, key="deposit_member")
            amount = st.number_input("금액", min_value=1_000, step=10_000, value=100_000, key="deposit_amount")
            category = st.selectbox("목적", DEPOSIT_CATEGORIES, key="deposit_category")
            memo = st.text_input("메모 (선택)", key="deposit_memo")
            if st.form_submit_button("입금 저장", use_container_width=True):
                db.add_cash_transaction(tx_date.isoformat(), "입금", member, amount, category, memo)
                st.success("입금을 저장했습니다.")
                st.rerun()
    with expense_tab:
        with st.form("expense_form", clear_on_submit=True):
            cols = st.columns(2)
            tx_date = cols[0].date_input("날짜", date.today(), key="expense_date")
            member = cols[1].selectbox("지출자", MEMBERS, key="expense_member")
            amount = st.number_input("금액", min_value=1_000, step=10_000, value=50_000, key="expense_amount")
            category = st.selectbox("분류", EXPENSE_CATEGORIES, key="expense_category")
            memo = st.text_input("메모 (선택)", key="expense_memo")
            if st.form_submit_button("지출 저장", use_container_width=True):
                db.add_cash_transaction(tx_date.isoformat(), "지출", member, amount, category, memo)
                st.success("지출을 저장했습니다.")
                st.rerun()

    left, right = st.columns(2)
    cash_df = pd.DataFrame(cash)
    with left:
        st.subheader("구성원별 기여금")
        deposits = cash_df[cash_df["tx_type"] == "입금"].groupby("member_name", as_index=False)["amount"].sum() if not cash_df.empty else pd.DataFrame()
        if not deposits.empty:
            st.plotly_chart(px.bar(deposits, x="member_name", y="amount", text_auto=",.0f", labels={"member_name":"가족","amount":"금액"}, color_discrete_sequence=["#4f8df7"]), use_container_width=True)
    with right:
        st.subheader("지출 비중")
        expenses = cash_df[cash_df["tx_type"] == "지출"].groupby("category", as_index=False)["amount"].sum() if not cash_df.empty else pd.DataFrame()
        if expenses.empty:
            st.info("지출을 기록하면 차트가 보여요.")
        else:
            st.plotly_chart(px.pie(expenses, names="category", values="amount", hole=.55), use_container_width=True)
    st.subheader("전체 거래 내역")
    if not cash_df.empty:
        display = cash_df[["tx_date", "tx_type", "member_name", "amount", "category", "memo"]].rename(columns={"tx_date":"날짜","tx_type":"구분","member_name":"가족","amount":"금액","category":"분류","memo":"메모"})
        st.dataframe(display, use_container_width=True, hide_index=True)
        with st.expander("거래 수정·삭제", expanded=False):
            choices = {f'{tx["tx_date"]} · {tx["tx_type"]} · {tx["member_name"]} · {format_won(tx["amount"])} (#{tx["id"]})': tx for tx in cash}
            selected_label = st.selectbox("수정할 거래", list(choices), key="cash_edit_select")
            selected_tx = choices[selected_label]
            all_categories = list(dict.fromkeys(DEPOSIT_CATEGORIES + EXPENSE_CATEGORIES))
            with st.form("cash_edit_form"):
                edit_type = st.radio("구분", ["입금", "지출"], index=["입금", "지출"].index(selected_tx["tx_type"]), horizontal=True)
                cols = st.columns(2)
                edit_date = cols[0].date_input("날짜", date.fromisoformat(selected_tx["tx_date"]))
                edit_member = cols[1].selectbox("가족", MEMBERS, index=MEMBERS.index(selected_tx["member_name"]))
                edit_amount = st.number_input("금액", min_value=1.0, value=float(selected_tx["amount"]), step=10_000.0)
                edit_category = st.selectbox("분류", all_categories, index=all_categories.index(selected_tx["category"]) if selected_tx["category"] in all_categories else 0)
                edit_memo = st.text_input("메모", value=selected_tx["memo"])
                confirm_delete = st.checkbox("이 거래를 삭제합니다")
                c1, c2, c3 = st.columns(3)
                save = c1.form_submit_button("수정 저장", use_container_width=True)
                delete = c2.form_submit_button("삭제", use_container_width=True)
                cancel = c3.form_submit_button("취소", use_container_width=True)
                if save:
                    db.update_cash_transaction(int(selected_tx["id"]), edit_date.isoformat(), edit_type, edit_member, edit_amount, edit_category, edit_memo)
                    st.rerun()
                if delete:
                    if confirm_delete:
                        db.delete_record("cash_transactions", int(selected_tx["id"]))
                        st.rerun()
                    else:
                        st.warning("삭제 확인에 체크해 주세요.")
                if cancel:
                    st.info("변경하지 않았습니다.")


def render_investments() -> None:
    top_title("📈 가족 투자", "현재 가치와 수익을 쉬운 숫자로 확인하세요")
    portfolio, warnings, fx_result = portfolio_data()
    principal = float(portfolio["투자원금"].sum()) if not portfolio.empty else 0
    value = float(portfolio["평가금액"].sum()) if not portfolio.empty else 0
    profit = value - principal
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("투자 원금", format_won(principal))
    c2.metric("현재 가치", format_won(value))
    c3.metric("평가손익", format_won(profit))
    c4.metric("총 수익률", format_percent(profit / principal * 100 if principal else 0))
    if fx_result:
        st.caption(f"USD/KRW {fx_result.price:,.2f} · {fx_result.source}")
    for message in warnings:
        st.warning(message)

    if not portfolio.empty:
        table_df = portfolio[["상품명", "티커", "보유수량", "현재가", "투자원금", "평가금액", "평가손익", "수익률", "가격기준"]].copy()
        st.dataframe(table_df, use_container_width=True, hide_index=True, column_config={"현재가":st.column_config.NumberColumn(format="%.2f"), "투자원금":st.column_config.NumberColumn(format="%,.0f원"), "평가금액":st.column_config.NumberColumn(format="%,.0f원"), "평가손익":st.column_config.NumberColumn(format="%,.0f원"), "수익률":st.column_config.NumberColumn(format="%.1f%%")})
        left, right = st.columns(2)
        with left:
            st.plotly_chart(px.bar(portfolio, x="상품명", y="수익률", color="수익률", color_continuous_scale=["#2563eb", "#f7f8fa", "#e5484d"], title="상품별 수익률"), use_container_width=True)
        with right:
            positive = portfolio[portfolio["평가금액"] > 0]
            if not positive.empty:
                st.plotly_chart(px.pie(positive, names="상품명", values="평가금액", hole=.55, title="투자 비중"), use_container_width=True)

    with st.expander("새 투자상품과 첫 매수 등록", expanded=False):
        with st.form("new_asset_form"):
            asset_name = st.text_input("투자상품명")
            cols = st.columns(2)
            ticker = cols[0].text_input("티커", placeholder="AAPL 또는 005930.KS")
            market = cols[1].selectbox("시장 구분", MARKETS)
            cols = st.columns(2)
            buy_date = cols[0].date_input("매수일", date.today())
            quantity = cols[1].number_input("매수수량", min_value=0.0001, value=1.0, format="%.4f")
            currency = "USD" if market == "미국주식" else "KRW"
            cols = st.columns(2)
            unit_price = cols[0].number_input(f"매수가 ({currency})", min_value=0.0, value=100.0 if currency == "USD" else 10_000.0)
            fx_rate = cols[1].number_input("매수 당시 환율", min_value=1.0, value=1_400.0 if currency == "USD" else 1.0, disabled=currency == "KRW")
            total_default = quantity * unit_price * fx_rate
            total = st.number_input("매수금액 (원)", min_value=1.0, value=float(total_default))
            manual_value = st.number_input("현재 수동 평가금액 (예금·채권·기타)", min_value=0.0, value=0.0)
            memo = st.text_input("투자 메모")
            if st.form_submit_button("투자 등록", use_container_width=True):
                if not asset_name.strip():
                    st.error("투자상품명을 입력해 주세요.")
                elif market not in MANUAL_MARKETS and not ticker.strip():
                    st.error("시장 가격을 조회할 티커를 입력해 주세요.")
                else:
                    asset_id = db.add_asset(asset_name.strip(), ticker, market, currency, unit_price, manual_value or None, memo)
                    db.add_investment_transaction(asset_id, buy_date.isoformat(), "매수", quantity, unit_price, fx_rate, total, memo)
                    st.success("투자상품을 등록했습니다.")
                    st.rerun()

    assets = records("investment_assets", "id ASC")
    if assets:
        name_to_id = {f'{a["asset_name"]} ({a["ticker"] or a["market_type"]})': int(a["id"]) for a in assets}
        with st.expander("추가 매수·매도 기록", expanded=False):
            with st.form("trade_form"):
                selected = st.selectbox("상품", list(name_to_id))
                trade_type = st.radio("구분", ["매수", "매도"], horizontal=True)
                cols = st.columns(2)
                trade_date = cols[0].date_input("거래일", date.today(), key="trade_date")
                quantity = cols[1].number_input("수량", min_value=0.0001, value=1.0, format="%.4f", key="trade_qty")
                asset = next(a for a in assets if int(a["id"]) == name_to_id[selected])
                currency = asset["currency"]
                cols = st.columns(2)
                unit_price = cols[0].number_input(f"거래 단가 ({currency})", min_value=0.0, value=float(asset["manual_current_price"] or 0), key="trade_unit")
                fx_rate = cols[1].number_input("거래 당시 환율", min_value=1.0, value=1_400.0 if currency == "USD" else 1.0, disabled=currency == "KRW", key="trade_fx")
                total = st.number_input("거래 총액 (원)", min_value=1.0, value=max(float(quantity * unit_price * fx_rate), 1.0), key="trade_total")
                memo = st.text_input("메모", key="trade_memo")
                if st.form_submit_button("거래 저장", use_container_width=True):
                    asset_trades = [t for t in records("investment_transactions", "trade_date ASC, id ASC") if int(t["asset_id"]) == int(asset["id"])]
                    held = calculate_position(asset_trades)["quantity"]
                    if trade_type == "매도" and quantity > held + 1e-9:
                        st.error(f"현재 보유수량 {held:g}보다 많이 매도할 수 없습니다.")
                    else:
                        db.add_investment_transaction(int(asset["id"]), trade_date.isoformat(), trade_type, quantity, unit_price, fx_rate, total, memo)
                        st.success("투자 거래를 저장했습니다.")
                        st.rerun()
        with st.expander("수동 가격·평가금액 수정", expanded=False):
            with st.form("manual_value_form"):
                selected = st.selectbox("상품", list(name_to_id), key="manual_asset")
                asset = next(a for a in assets if int(a["id"]) == name_to_id[selected])
                manual_price = st.number_input("실시간 조회 실패 시 사용할 현재가", min_value=0.0, value=float(asset["manual_current_price"] or 0))
                manual_value = st.number_input("수동 평가금액 (예금·채권·기타)", min_value=0.0, value=float(asset["manual_current_value"] or 0))
                if st.form_submit_button("평가값 저장", use_container_width=True):
                    db.update_asset_manual_value(int(asset["id"]), manual_price or None, manual_value or None)
                    st.success("평가값을 저장했습니다.")
                    st.rerun()
        with st.expander("투자상품 정보 수정·삭제", expanded=False):
            selected = st.selectbox("수정할 상품", list(name_to_id), key="asset_edit_select")
            asset = next(a for a in assets if int(a["id"]) == name_to_id[selected])
            with st.form("asset_edit_form"):
                edit_name = st.text_input("투자상품명", value=asset["asset_name"])
                cols = st.columns(2)
                edit_ticker = cols[0].text_input("티커", value=asset["ticker"])
                edit_market = cols[1].selectbox("시장 구분", MARKETS, index=MARKETS.index(asset["market_type"]) if asset["market_type"] in MARKETS else len(MARKETS)-1)
                edit_currency = "USD" if edit_market == "미국주식" else "KRW"
                cols = st.columns(2)
                edit_manual_price = cols[0].number_input("수동 현재가", min_value=0.0, value=float(asset["manual_current_price"] or 0))
                edit_manual_value = cols[1].number_input("수동 평가금액", min_value=0.0, value=float(asset["manual_current_value"] or 0))
                edit_memo = st.text_input("투자 메모", value=asset["memo"])
                confirm_delete = st.checkbox("상품과 모든 거래를 삭제합니다")
                c1, c2, c3 = st.columns(3)
                save = c1.form_submit_button("수정 저장", use_container_width=True)
                delete = c2.form_submit_button("삭제", use_container_width=True)
                cancel = c3.form_submit_button("취소", use_container_width=True)
                if save:
                    if not edit_name.strip() or (edit_market not in MANUAL_MARKETS and not edit_ticker.strip()):
                        st.error("상품명과 티커를 확인해 주세요.")
                    else:
                        db.update_asset(int(asset["id"]), edit_name.strip(), edit_ticker, edit_market, edit_currency, edit_manual_price or None, edit_manual_value or None, edit_memo)
                        st.rerun()
                if delete:
                    if confirm_delete:
                        db.delete_record("investment_assets", int(asset["id"]))
                        st.rerun()
                    else:
                        st.warning("삭제 확인에 체크해 주세요.")
                if cancel:
                    st.info("변경하지 않았습니다.")

        investment_trades = records("investment_transactions", "trade_date DESC, id DESC")
        if investment_trades:
            with st.expander("매수·매도 내역 수정·삭제", expanded=False):
                assets_by_id = {int(a["id"]): a for a in assets}
                trade_choices = {
                    f'{t["trade_date"]} · {assets_by_id[int(t["asset_id"])]["asset_name"]} · {t["trade_type"]} {t["quantity"]:g} (#{t["id"]})': t
                    for t in investment_trades if int(t["asset_id"]) in assets_by_id
                }
                selected_trade = trade_choices[st.selectbox("수정할 거래", list(trade_choices), key="investment_trade_edit_select")]
                selected_asset = assets_by_id[int(selected_trade["asset_id"])]
                with st.form("investment_trade_edit_form"):
                    edit_trade_type = st.radio("구분", ["매수", "매도"], index=["매수", "매도"].index(selected_trade["trade_type"]), horizontal=True)
                    cols = st.columns(2)
                    edit_trade_date = cols[0].date_input("거래일", date.fromisoformat(selected_trade["trade_date"]))
                    edit_quantity = cols[1].number_input("수량", min_value=0.0001, value=float(selected_trade["quantity"]), format="%.4f")
                    cols = st.columns(2)
                    edit_unit_price = cols[0].number_input(f'거래 단가 ({selected_asset["currency"]})', min_value=0.0, value=float(selected_trade["unit_price"]))
                    edit_fx_rate = cols[1].number_input("거래 당시 환율", min_value=1.0, value=float(selected_trade["fx_rate"]), disabled=selected_asset["currency"] == "KRW")
                    edit_total = st.number_input("거래 총액 (원)", min_value=1.0, value=float(selected_trade["total_amount_krw"]))
                    edit_memo = st.text_input("메모", value=selected_trade["memo"])
                    confirm_delete = st.checkbox("이 투자 거래를 삭제합니다")
                    c1, c2, c3 = st.columns(3)
                    save = c1.form_submit_button("수정 저장", use_container_width=True)
                    delete = c2.form_submit_button("삭제", use_container_width=True)
                    cancel = c3.form_submit_button("취소", use_container_width=True)
                    if save:
                        candidate_trades = [t.copy() for t in investment_trades if int(t["asset_id"]) == int(selected_trade["asset_id"]) and int(t["id"]) != int(selected_trade["id"])]
                        candidate_trades.append({"id": int(selected_trade["id"]), "trade_date": edit_trade_date.isoformat(), "trade_type": edit_trade_type, "quantity": edit_quantity, "total_amount_krw": edit_total})
                        try:
                            calculate_position(candidate_trades)
                            db.update_investment_transaction(int(selected_trade["id"]), int(selected_trade["asset_id"]), edit_trade_date.isoformat(), edit_trade_type, edit_quantity, edit_unit_price, edit_fx_rate, edit_total, edit_memo)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                    if delete:
                        if confirm_delete:
                            db.delete_record("investment_transactions", int(selected_trade["id"]))
                            st.rerun()
                        else:
                            st.warning("삭제 확인에 체크해 주세요.")
                    if cancel:
                        st.info("변경하지 않았습니다.")


def render_goals() -> None:
    top_title("🎯 가족 목표", "함께 모으는 돈의 진행 상황을 확인하세요")
    with st.form("goal_form", clear_on_submit=True):
        name = st.text_input("목표명", placeholder="예: 가족여행 기금")
        cols = st.columns(2)
        target = cols[0].number_input("목표금액", min_value=10_000, step=100_000, value=1_000_000)
        current = cols[1].number_input("현재 적립금", min_value=0, step=100_000, value=0)
        cols = st.columns(2)
        start = cols[0].date_input("시작일", date.today())
        target_date = cols[1].date_input("목표일", date.today() + timedelta(days=365))
        owner = st.selectbox("담당자", MEMBERS)
        memo = st.text_input("메모")
        if st.form_submit_button("목표 저장", use_container_width=True):
            if not name.strip() or target_date < start:
                st.error("목표명과 날짜를 확인해 주세요.")
            else:
                db.add_goal(name.strip(), target, current, start.isoformat(), target_date.isoformat(), owner, memo)
                st.success("가족 목표를 저장했습니다.")
                st.rerun()
    goals = records("goals", "target_date ASC")
    if goals:
        with st.expander("목표 수정·삭제", expanded=False):
            goal_choices = {f'{g["goal_name"]} · {format_won(g["target_amount"])} (#{g["id"]})': g for g in goals}
            selected_goal = goal_choices[st.selectbox("수정할 목표", list(goal_choices), key="goal_edit_select")]
            with st.form("goal_edit_form"):
                edit_name = st.text_input("목표명", value=selected_goal["goal_name"])
                cols = st.columns(2)
                edit_target = cols[0].number_input("목표금액", min_value=1.0, value=float(selected_goal["target_amount"]))
                edit_current = cols[1].number_input("현재 적립금", min_value=0.0, value=float(selected_goal["current_amount"]))
                cols = st.columns(2)
                edit_start = cols[0].date_input("시작일", date.fromisoformat(selected_goal["start_date"]))
                edit_target_date = cols[1].date_input("목표일", date.fromisoformat(selected_goal["target_date"]))
                edit_owner = st.selectbox("담당자", MEMBERS, index=MEMBERS.index(selected_goal["owner"]))
                edit_memo = st.text_input("메모", value=selected_goal["memo"])
                confirm_delete = st.checkbox("이 목표를 삭제합니다")
                c1, c2, c3 = st.columns(3)
                save = c1.form_submit_button("수정 저장", use_container_width=True)
                delete = c2.form_submit_button("삭제", use_container_width=True)
                cancel = c3.form_submit_button("취소", use_container_width=True)
                if save:
                    if not edit_name.strip() or edit_target_date < edit_start:
                        st.error("목표명과 날짜를 확인해 주세요.")
                    else:
                        db.update_goal(int(selected_goal["id"]), edit_name.strip(), edit_target, edit_current, edit_start.isoformat(), edit_target_date.isoformat(), edit_owner, edit_memo)
                        st.rerun()
                if delete:
                    if confirm_delete:
                        db.delete_record("goals", int(selected_goal["id"]))
                        st.rerun()
                    else:
                        st.warning("삭제 확인에 체크해 주세요.")
                if cancel:
                    st.info("변경하지 않았습니다.")
    for goal in goals:
        metrics = goal_metrics(goal["target_amount"], goal["current_amount"], goal["start_date"], goal["target_date"])
        st.subheader(goal["goal_name"])
        st.progress(min(metrics["progress"] / 100, 1.0), text=f'{metrics["progress"]:.1f}% · {format_won(goal["current_amount"])} / {format_won(goal["target_amount"])}')
        c1, c2, c3 = st.columns(3)
        c1.metric("남은 금액", format_won(metrics["remaining"]))
        c2.metric("매달 필요한 금액", format_won(metrics["monthly_needed"]) if metrics["monthly_needed"] is not None else "계산할 수 없음")
        c3.metric("예상 달성일", metrics["expected_date"].isoformat() if metrics["expected_date"] else "계산할 수 없음")
        st.caption(f'{goal["owner"]} 담당 · 목표일 {goal["target_date"]} · {goal["memo"]}')
        st.divider()


def render_events() -> None:
    top_title("🗓️ 가족 일정", "병원, 생일, 모임을 놓치지 마세요")
    with st.form("event_form", clear_on_submit=True):
        title = st.text_input("일정명")
        cols = st.columns(2)
        event_date = cols[0].date_input("날짜", date.today())
        event_time = cols[1].time_input("시간", datetime.strptime("12:00", "%H:%M").time())
        event_type = st.selectbox("유형", ["생일", "병원", "여행", "가족모임", "납부일", "기타"])
        participants = st.multiselect("참석자", MEMBERS, default=MEMBERS)
        memo = st.text_input("메모")
        if st.form_submit_button("일정 저장", use_container_width=True):
            if not title.strip():
                st.error("일정명을 입력해 주세요.")
            else:
                db.add_event(event_date.isoformat(), event_time.strftime("%H:%M"), title.strip(), event_type, ", ".join(participants), memo)
                st.success("일정을 저장했습니다.")
                st.rerun()
    events = records("events", "event_date ASC, event_time ASC")
    if events:
        with st.expander("일정 수정·삭제", expanded=False):
            event_choices = {f'{e["event_date"]} {e["event_time"]} · {e["title"]} (#{e["id"]})': e for e in events}
            selected_event = event_choices[st.selectbox("수정할 일정", list(event_choices), key="event_edit_select")]
            current_participants = [m for m in MEMBERS if m in selected_event["participants"]]
            with st.form("event_edit_form"):
                edit_title = st.text_input("일정명", value=selected_event["title"])
                cols = st.columns(2)
                edit_date = cols[0].date_input("날짜", date.fromisoformat(selected_event["event_date"]))
                edit_time = cols[1].time_input("시간", datetime.strptime(selected_event["event_time"] or "12:00", "%H:%M").time())
                event_types = ["생일", "병원", "여행", "가족모임", "납부일", "기타"]
                edit_type = st.selectbox("유형", event_types, index=event_types.index(selected_event["event_type"]) if selected_event["event_type"] in event_types else len(event_types)-1)
                edit_participants = st.multiselect("참석자", MEMBERS, default=current_participants)
                edit_memo = st.text_input("메모", value=selected_event["memo"])
                confirm_delete = st.checkbox("이 일정을 삭제합니다")
                c1, c2, c3 = st.columns(3)
                save = c1.form_submit_button("수정 저장", use_container_width=True)
                delete = c2.form_submit_button("삭제", use_container_width=True)
                cancel = c3.form_submit_button("취소", use_container_width=True)
                if save:
                    if edit_title.strip():
                        db.update_event(int(selected_event["id"]), edit_date.isoformat(), edit_time.strftime("%H:%M"), edit_title.strip(), edit_type, ", ".join(edit_participants), edit_memo)
                        st.rerun()
                    else:
                        st.error("일정명을 입력해 주세요.")
                if delete:
                    if confirm_delete:
                        db.delete_record("events", int(selected_event["id"]))
                        st.rerun()
                    else:
                        st.warning("삭제 확인에 체크해 주세요.")
                if cancel:
                    st.info("변경하지 않았습니다.")
    today_events = [e for e in events if e["event_date"] == date.today().isoformat()]
    st.subheader("오늘 일정")
    if not today_events:
        st.info("오늘은 등록된 일정이 없어요.")
    for event in today_events:
        st.markdown(f'**{event["event_time"]} {event["title"]}** · {event["participants"]}')
    cols = st.columns(2)
    year = int(cols[0].number_input("연도", min_value=2020, max_value=2100, value=date.today().year))
    month = int(cols[1].selectbox("월", list(range(1, 13)), index=date.today().month - 1))
    components.html(month_calendar_html(events, year, month), height=520, scrolling=True)
    st.subheader("다가오는 일정")
    upcoming = [e for e in events if e["event_date"] >= date.today().isoformat()]
    if upcoming:
        st.dataframe(pd.DataFrame(upcoming)[["event_date", "event_time", "title", "event_type", "participants", "memo"]].rename(columns={"event_date":"날짜","event_time":"시간","title":"일정","event_type":"유형","participants":"참석자","memo":"메모"}), use_container_width=True, hide_index=True)


def render_tasks() -> None:
    top_title("✅ 가족 할 일", "누가 무엇을 할지 가볍게 정리하세요")
    with st.form("task_form", clear_on_submit=True):
        title = st.text_input("할 일 제목")
        cols = st.columns(2)
        owner = cols[0].selectbox("담당자", MEMBERS)
        due = cols[1].date_input("마감일", date.today() + timedelta(days=7))
        status = st.selectbox("상태", ["예정", "진행중", "완료"])
        memo = st.text_input("메모")
        if st.form_submit_button("할 일 저장", use_container_width=True):
            if title.strip():
                db.add_task(title.strip(), owner, due.isoformat(), status, memo)
                st.success("할 일을 저장했습니다.")
                st.rerun()
            else:
                st.error("할 일 제목을 입력해 주세요.")
    owner_filter = st.selectbox("담당자별 보기", ["전체"] + MEMBERS)
    tasks = records("tasks", "due_date ASC")
    all_tasks = tasks.copy()
    if owner_filter != "전체":
        tasks = [t for t in tasks if t["owner"] == owner_filter]
    for task in tasks:
        overdue = task["due_date"] < date.today().isoformat() and task["status"] != "완료"
        with st.container(border=True):
            cols = st.columns([3, 1.4, 1.2])
            cols[0].markdown(f'**{"⚠️ " if overdue else ""}{task["title"]}**  \n{task["owner"]} · {task["due_date"]} · {task["memo"]}')
            new_status = cols[1].selectbox("상태", ["예정", "진행중", "완료"], index=["예정", "진행중", "완료"].index(task["status"]), key=f'task_status_{task["id"]}', label_visibility="collapsed")
            if cols[2].button("변경", key=f'task_btn_{task["id"]}', use_container_width=True):
                db.update_task_status(int(task["id"]), new_status)
                st.rerun()
    if all_tasks:
        with st.expander("할 일 수정·삭제", expanded=False):
            task_choices = {f'{t["due_date"]} · {t["title"]} (#{t["id"]})': t for t in all_tasks}
            selected_task = task_choices[st.selectbox("수정할 할 일", list(task_choices), key="task_edit_select")]
            statuses = ["예정", "진행중", "완료"]
            with st.form("task_edit_form"):
                edit_title = st.text_input("할 일 제목", value=selected_task["title"])
                cols = st.columns(2)
                edit_owner = cols[0].selectbox("담당자", MEMBERS, index=MEMBERS.index(selected_task["owner"]))
                edit_due = cols[1].date_input("마감일", date.fromisoformat(selected_task["due_date"]))
                edit_status = st.selectbox("상태", statuses, index=statuses.index(selected_task["status"]))
                edit_memo = st.text_input("메모", value=selected_task["memo"])
                confirm_delete = st.checkbox("이 할 일을 삭제합니다")
                c1, c2, c3 = st.columns(3)
                save = c1.form_submit_button("수정 저장", use_container_width=True)
                delete = c2.form_submit_button("삭제", use_container_width=True)
                cancel = c3.form_submit_button("취소", use_container_width=True)
                if save:
                    if edit_title.strip():
                        db.update_task(int(selected_task["id"]), edit_title.strip(), edit_owner, edit_due.isoformat(), edit_status, edit_memo)
                        st.rerun()
                    else:
                        st.error("할 일 제목을 입력해 주세요.")
                if delete:
                    if confirm_delete:
                        db.delete_record("tasks", int(selected_task["id"]))
                        st.rerun()
                    else:
                        st.warning("삭제 확인에 체크해 주세요.")
                if cancel:
                    st.info("변경하지 않았습니다.")


def render_polls() -> None:
    top_title("🗳️ 가족 투표", "가족의 결정을 빠르고 공평하게 모으세요")
    with st.form("poll_form", clear_on_submit=True):
        title = st.text_input("투표 제목")
        options_text = st.text_area("선택지 (줄마다 하나)", placeholder="제주도\n부산\n강릉")
        deadline = st.date_input("마감일", date.today() + timedelta(days=7))
        if st.form_submit_button("투표 만들기", use_container_width=True):
            options = list(dict.fromkeys(x.strip() for x in options_text.splitlines() if x.strip()))
            if not title.strip() or len(options) < 2:
                st.error("제목과 서로 다른 선택지 2개 이상을 입력해 주세요.")
            else:
                db.add_poll(title.strip(), options, deadline.isoformat())
                st.success("투표를 만들었습니다.")
                st.rerun()
    polls = records("polls", "deadline DESC")
    if polls:
        with st.expander("투표 수정·삭제", expanded=False):
            poll_choices = {f'{p["deadline"]} · {p["title"]} (#{p["id"]})': p for p in polls}
            selected_poll = poll_choices[st.selectbox("수정할 투표", list(poll_choices), key="poll_edit_select")]
            existing_options = db.fetch_all("SELECT option_text FROM poll_options WHERE poll_id=? ORDER BY id", (selected_poll["id"],))
            vote_count = db.fetch_one("SELECT COUNT(*) AS count FROM poll_votes WHERE poll_id=?", (selected_poll["id"],))["count"]
            with st.form("poll_edit_form"):
                edit_title = st.text_input("투표 제목", value=selected_poll["title"])
                edit_options_text = st.text_area("선택지 (투표 전만 수정 가능)", value="\n".join(o["option_text"] for o in existing_options), disabled=vote_count > 0)
                edit_deadline = st.date_input("마감일", date.fromisoformat(selected_poll["deadline"]))
                confirm_delete = st.checkbox("투표와 모든 응답을 삭제합니다")
                c1, c2, c3 = st.columns(3)
                save = c1.form_submit_button("수정 저장", use_container_width=True)
                delete = c2.form_submit_button("삭제", use_container_width=True)
                cancel = c3.form_submit_button("취소", use_container_width=True)
                if save:
                    new_options = list(dict.fromkeys(x.strip() for x in edit_options_text.splitlines() if x.strip()))
                    if not edit_title.strip() or (vote_count == 0 and len(new_options) < 2):
                        st.error("제목과 선택지 2개 이상을 확인해 주세요.")
                    else:
                        db.update_poll(int(selected_poll["id"]), edit_title.strip(), edit_deadline.isoformat(), new_options if vote_count == 0 else None)
                        st.rerun()
                if delete:
                    if confirm_delete:
                        db.delete_record("polls", int(selected_poll["id"]))
                        st.rerun()
                    else:
                        st.warning("삭제 확인에 체크해 주세요.")
                if cancel:
                    st.info("변경하지 않았습니다.")
    for poll in polls:
        st.subheader(poll["title"])
        options = db.fetch_all("SELECT * FROM poll_options WHERE poll_id = ? ORDER BY id", (poll["id"],))
        votes = db.fetch_all("""SELECT o.id AS option_id, o.option_text, COUNT(v.id) AS votes FROM poll_options o LEFT JOIN poll_votes v ON v.option_id=o.id WHERE o.poll_id=? GROUP BY o.id, o.option_text ORDER BY o.id""", (poll["id"],))
        voter_rows = db.fetch_all("SELECT voter_name FROM poll_votes WHERE poll_id = ? ORDER BY created_at", (poll["id"],))
        st.caption(f'마감 {poll["deadline"]} · 참여 {len(voter_rows)}/5명' + (f' · {", ".join(v["voter_name"] for v in voter_rows)}' if voter_rows else ""))
        if date.today().isoformat() <= poll["deadline"]:
            with st.form(f'vote_form_{poll["id"]}'):
                voter = st.selectbox("투표자", MEMBERS, key=f'voter_{poll["id"]}')
                selected_text = st.radio("선택", [o["option_text"] for o in options], key=f'option_{poll["id"]}')
                if st.form_submit_button("투표하기", use_container_width=True):
                    option_id = next(int(o["id"]) for o in options if o["option_text"] == selected_text)
                    try:
                        db.cast_vote(int(poll["id"]), option_id, voter)
                        st.success("투표했습니다.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("이미 이 투표에 참여한 가족입니다.")
        else:
            st.info("마감된 투표입니다.")
        result_df = pd.DataFrame(votes)
        if not result_df.empty:
            st.plotly_chart(px.bar(result_df, x="option_text", y="votes", text_auto=True, labels={"option_text":"선택지","votes":"표"}, color_discrete_sequence=["#4f8df7"]), use_container_width=True)
        st.divider()


PAGES = {
    "홈": render_home, "공동자금": render_cash, "투자": render_investments,
    "목표": render_goals, "일정": render_events, "할 일": render_tasks, "투표": render_polls,
}
with st.sidebar:
    st.markdown("## Family CFO")
    st.caption("우리 가족 운영 대시보드")
    page = st.radio("메뉴", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption("가족 5명이 함께 쓰는 MVP")

PAGES[page]()
