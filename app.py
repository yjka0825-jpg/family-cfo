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
