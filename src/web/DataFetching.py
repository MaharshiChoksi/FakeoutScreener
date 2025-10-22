# ...existing code...
import psycopg2
from datetime import datetime
import pandas as pd
import streamlit as st
import logging
import pytz

logging.basicConfig(level=logging.INFO)

# DB engine provider (expects connection string in Streamlit secrets or env var)
def _get_db_engine():
    # prefer Streamlit secrets, fallback to environment variables
    uri = st.secrets.get("DATABASE_URL")
    if not uri:
        raise RuntimeError("CockroachDB URI not found. Set st.secrets['DATABASE_URL'] or env DATABASE_URL.")
    engine = psycopg2.connect(uri)
    logging.info("Database connection established.")
    return engine

# helper: previous month range
def get_previous_month_start():
    now_ist = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    first_day_this_month = now_ist.replace(day=1)
    last_month_last = first_day_this_month - pd.Timedelta(days=1)
    return last_month_last.replace(day=1)

def get_previous_month_last():
    now_ist = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    first_day_this_month = now_ist.replace(day=1)
    return first_day_this_month - pd.Timedelta(days=1)

# cached fetcher for required Daily rows
@st.cache_data(ttl=10800) # cache for 3 hours
def fetch_dailydata_from_db() -> pd.DataFrame:
    engine = _get_db_engine()
    cur = engine.cursor()
    prev_month_start = get_previous_month_start().strftime("%Y-%m-%d")
    # fetch monthly rows for previous month and weekly rows for recent weeks
    query = f"SELECT symbol, closedate, open, high, low, close, volume FROM dailydata WHERE closedate >= '{prev_month_start}';"
    cur.execute(query)
    rows = cur.fetchall()
    cols = [desc[0] for desc in cur.description]
    df = pd.DataFrame(rows, columns=cols)
    logging.info(f"Fetched {len(df)} rows from dailydata table.")
    return df


@st.cache_data(ttl=10800) # cache for 3 hours
def compute_monthly_movers_df(daily_df: pd.DataFrame, monthly_threshold: float) -> pd.DataFrame:
    # create dataframe aggregating to monthly OHLCV for getting start and end of month date use of get_previous_month_start and get_previous_month_last
    start = get_previous_month_start()
    end = get_previous_month_last()

    # filter rows belonging to previous month (inclusive)
    month_mask = (daily_df["closedate"] >= start) & (daily_df["closedate"] <= end)
    month_df = daily_df.loc[month_mask].copy()
    if month_df.empty:
        return pd.DataFrame(columns=[
            "symbol", "date", "open", "high", "low", "close", "volume", "%Change Prev Month"
        ])
    
    records = []
    # aggregate per symbol
    for sym, g in month_df.groupby("symbol"):
        g_sorted = g.sort_values("closedate")
        first_row = g_sorted.iloc[0]
        last_row = g_sorted.iloc[-1]

        open_price = float(first_row.get("open", None)) if pd.notna(first_row.get("open", None)) else None
        close_price = float(last_row.get("close", None)) if pd.notna(last_row.get("close", None)) else None
        high_price = float(g_sorted["high"].max()) if "high" in g_sorted.columns and not g_sorted["high"].isna().all() else None
        low_price = float(g_sorted["low"].min()) if "low" in g_sorted.columns and not g_sorted["low"].isna().all() else None
        volume_sum = int(g_sorted["volume"].sum()) if "volume" in g_sorted.columns else None

        pct_change = None
        if open_price is not None and close_price is not None and open_price != 0:
            pct_change = round(((close_price - open_price) / open_price) * 100, 3)

        records.append({
            "symbol": sym,
            "date": start.strftime("%Y-%m-%d"),
            "open": round(open_price, 3) if open_price is not None else None,
            "high": round(high_price, 3) if high_price is not None else None,
            "low": round(low_price, 3) if low_price is not None else None,
            "close": round(close_price, 3) if close_price is not None else None,
            "volume": volume_sum,
            "%Change Prev Month": pct_change,
        })
    monthly_df = pd.DataFrame.from_records(records, columns=[
        "symbol", "date", "open", "high", "low", "close", "volume", "%Change Prev Month"
    ])
    # filter rows which have absolute %Change >= threshold (drop NaN %Change)
    monthly_df = monthly_df[monthly_df["%Change Prev Month"].notna() & (monthly_df["%Change Prev Month"].abs() >= float(monthly_threshold))]

    # sort for deterministic order
    monthly_df = monthly_df.sort_values("symbol").reset_index(drop=True)
    logging.info(f"Computed monthly movers df with {len(monthly_df)} rows meeting threshold {monthly_threshold}%.")
    return monthly_df


@st.cache_data(ttl=10800) # cache for 3 hours
def compute_prev_week_df(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        return pd.DataFrame(columns=[
            "symbol", "date", "open", "high", "low", "close", "volume"
        ])

    today_ist = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    # current week's Monday
    current_monday = today_ist - pd.Timedelta(days=today_ist.weekday())
    prev_week_start = current_monday - pd.Timedelta(days=7)
    prev_week_end = prev_week_start + pd.Timedelta(days=6)

    # normalize dates and filter rows in the previous week (inclusive)
    df = daily_df.copy()
    if "closedate" not in df.columns:
        raise KeyError("daily_df must contain 'closedate' column")
    df["closedate"] = pd.to_datetime(df["closedate"]).dt.date
    mask = (df["closedate"] >= prev_week_start) & (df["closedate"] <= prev_week_end)
    week_df = df.loc[mask].copy()
    
    records = []
    for sym, g in week_df.groupby("symbol"):
        g_sorted = g.sort_values("closedate")
        first_row = g_sorted.iloc[0]
        last_row = g_sorted.iloc[-1]

        open_price = float(first_row.get("open")) if pd.notna(first_row.get("open")) else None
        close_price = float(last_row.get("close")) if pd.notna(last_row.get("close")) else None
        high_price = float(g_sorted["high"].max()) if "high" in g_sorted.columns and not g_sorted["high"].isna().all() else None
        low_price = float(g_sorted["low"].min()) if "low" in g_sorted.columns and not g_sorted["low"].isna().all() else None
        volume_sum = int(g_sorted["volume"].sum()) if "volume" in g_sorted.columns else None

        records.append({
            "symbol": sym,
            "date": prev_week_start.strftime("%Y-%m-%d"),
            "open": round(open_price, 3) if open_price is not None else None,
            "high": round(high_price, 3) if high_price is not None else None,
            "low": round(low_price, 3) if low_price is not None else None,
            "close": round(close_price, 3) if close_price is not None else None,
            "volume": volume_sum,
        })

    weekly_df = pd.DataFrame.from_records(records, columns=[
        "symbol", "date", "open", "high", "low", "close", "volume"
    ])
    weekly_df = weekly_df.sort_values("symbol").reset_index(drop=True)
    logging.info(f"Computed previous week df with {len(weekly_df)} rows.")
    return weekly_df


@st.cache_data(ttl=10800) # cache for 3 hours
def compute_curr_week_df(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        return pd.DataFrame(columns=[
            "symbol", "date", "open", "high", "low", "close", "volume"
        ])

    today_ist = datetime.now(pytz.timezone("Asia/Kolkata")).date()
    # current week's Monday
    current_monday = today_ist - pd.Timedelta(days=today_ist.weekday())

    # normalize dates and filter rows in the previous week (inclusive)
    df = daily_df.copy()
    if "closedate" not in df.columns:
        raise KeyError("daily_df must contain 'closedate' column")
    df["closedate"] = pd.to_datetime(df["closedate"]).dt.date
    mask = (df["closedate"] >= current_monday) & (df["closedate"] <= today_ist)
    week_df = df.loc[mask].copy()
    
    records = []
    for sym, g in week_df.groupby("symbol"):
        g_sorted = g.sort_values("closedate")
        first_row = g_sorted.iloc[0]
        last_row = g_sorted.iloc[-1]

        open_price = float(first_row.get("open")) if pd.notna(first_row.get("open")) else None
        close_price = float(last_row.get("close")) if pd.notna(last_row.get("close")) else None
        high_price = float(g_sorted["high"].max()) if "high" in g_sorted.columns and not g_sorted["high"].isna().all() else None
        low_price = float(g_sorted["low"].min()) if "low" in g_sorted.columns and not g_sorted["low"].isna().all() else None
        volume_sum = int(g_sorted["volume"].sum()) if "volume" in g_sorted.columns else None

        records.append({
            "symbol": sym,
            "date": current_monday.strftime("%Y-%m-%d"),
            "open": round(open_price, 3) if open_price is not None else None,
            "high": round(high_price, 3) if high_price is not None else None,
            "low": round(low_price, 3) if low_price is not None else None,
            "close": round(close_price, 3) if close_price is not None else None,
            "volume": volume_sum,
        })

    weekly_df = pd.DataFrame.from_records(records, columns=[
        "symbol", "date", "open", "high", "low", "close", "volume"
    ])
    weekly_df = weekly_df.sort_values("symbol").reset_index(drop=True)
    streamlit_root_logger.info(f"Computed current week df with {len(weekly_df)} rows.")
    return weekly_df


def find_eligible_tickers(monthly_df: pd.DataFrame, prev_week_df: pd.DataFrame, curr_week_df: pd.DataFrame, signal_type: str):
    eligible_rows = []

    for symbol in curr_week_df['symbol'].unique():
        prev_week_stock = prev_week_df[prev_week_df['symbol'] == symbol]
        curr_week_stock = curr_week_df[curr_week_df['symbol'] == symbol]
        prev_month_stock = monthly_df[monthly_df['symbol'] == symbol]

        if prev_week_stock.empty or curr_week_stock.empty or prev_month_stock.empty:
            continue

        prev_week_high = prev_week_stock['high'].values[0]
        prev_week_low = prev_week_stock['low'].values[0]

        curr_week_high = curr_week_stock['high'].values[0]
        curr_week_low = curr_week_stock['low'].values[0]
        curr_week_close = curr_week_stock['close'].values[0]

        prev_month_open = prev_month_stock['open'].values[0]
        prev_month_close = prev_month_stock['close'].values[0]

        # safe percent calc
        prev_month_change = None
        try:
            if prev_month_open and not pd.isna(prev_month_open):
                prev_month_change = ((prev_month_close - prev_month_open) / prev_month_open) * 100
        except Exception:
            prev_month_change = None

        # Check for fakeout conditions (require month threshold)
        if (curr_week_high > prev_week_high and curr_week_close < prev_week_high):
            row = curr_week_stock.iloc[0].copy()
            row['Opportunity'] = 'SHORT'
            row['% Change Prev Month'] = round(prev_month_change, 2)
            eligible_rows.append(row)
        elif (curr_week_low < prev_week_low and curr_week_close > prev_week_low):
            row = curr_week_stock.iloc[0].copy()
            row['Opportunity'] = 'LONG'
            row['% Change Prev Month'] = round(prev_month_change, 2)
            eligible_rows.append(row)

    eligible_stocks = pd.DataFrame(eligible_rows)
    eligible_stocks = eligible_stocks[eligible_stocks['Opportunity'].isin([signal_type])] if signal_type in ['LONG', 'SHORT'] else eligible_stocks
    eligible_stocks.reset_index(inplace=True, drop=True)
    eligible_stocks.index = pd.RangeIndex(start=1, stop=len(eligible_stocks) + 1)
    eligible_stocks.index.name = "S.No"

    # persist only if results present
    if eligible_stocks.empty or eligible_stocks is None:
        return pd.DataFrame(columns=[
            "symbol", "date", "open", "high", "low", "close", "volume", "Opportunity", "% Change Prev Month"
        ])
    
    logging.info(f"Found {len(eligible_stocks)} eligible stocks for signal type '{signal_type}'.")
    return eligible_stocks
