# ...existing code...
import psycopg2
from datetime import datetime
import pandas as pd
import streamlit as st

# DB engine provider (expects connection string in Streamlit secrets or env var)
def _get_db_engine():
    # prefer Streamlit secrets, fallback to environment variables
    uri = st.secrets.get("DATABASE_URL")
    if not uri:
        raise RuntimeError("CockroachDB URI not found. Set st.secrets['DATABASE_URL'] or env DATABASE_URL.")
    engine = psycopg2.connect(uri)
    return engine

# helper: previous month range
def get_previous_month_start():
    today = datetime.now().date()
    first_day_this_month = today.replace(day=1)
    last_month_last = first_day_this_month - pd.Timedelta(days=1)
    return last_month_last.replace(day=1)

def get_previous_month_last():
    today = datetime.now().date()
    first_day_this_month = today.replace(day=1)
    return first_day_this_month - pd.Timedelta(days=1)

# cached fetcher for required OHLC rows
@st.cache_data(ttl=900)
def fetch_ohlc_from_db(intervals: tuple = ("1mo", "1wk")) -> dict:
    engine = _get_db_engine()
    conn = engine.cursor()
    prev_month_start = get_previous_month_start()
    prev_month_last = get_previous_month_last()
    # fetch monthly rows for previous month and weekly rows for recent weeks
    monthly_sql = f"""
        SELECT symbol, datetime_utc, open, high, low, close, volume, interval
        FROM ohlc
        WHERE interval = :interval
          AND datetime_utc >= :start_date
          AND datetime_utc <= :end_date
    """
    weekly_sql = f"""
        SELECT symbol, datetime_utc, open, high, low, close, volume, interval
        FROM ohlc
        WHERE interval = :interval
        ORDER BY symbol, datetime_utc
    """
    monthly_df = conn.execute(monthly_sql, params={"interval": "1mo", "start_date": str(prev_month_start), "end_date": str(prev_month_last)}).fetchall()
    weekly_df = conn.execute(weekly_sql, params={"interval": "1wk"}).fetchall()
    # normalize column names (ensure Datetime/Datetime format)
    if "datetime_utc" in monthly_df.columns:
        monthly_df = monthly_df.rename(columns={"datetime_utc": "Datetime"})
    if "datetime_utc" in weekly_df.columns:
        weekly_df = weekly_df.rename(columns={"datetime_utc": "Datetime"})
    monthly_df["Datetime"] = pd.to_datetime(monthly_df["Datetime"]).dt.date
    weekly_df["Datetime"] = pd.to_datetime(weekly_df["Datetime"]).dt.date
    return {"monthly": monthly_df, "weekly": weekly_df}

def compute_monthly_movers(monthly_df: pd.DataFrame, threshold: float) -> set:
    movers = set()
    if monthly_df.empty:
        return movers
    for sym, g in monthly_df.groupby("symbol"):
        g_sorted = g.sort_values("Datetime")
        first_close = g_sorted["close"].iloc[0]
        last_close = g_sorted["close"].iloc[-1]
        pct = ((last_close - first_close) / first_close) * 100 if first_close != 0 else 0
        if abs(pct) >= threshold:
            movers.add(sym)
    return movers

def filter_weekly(weekly_df: pd.DataFrame, movers_set: set, signal_type: str) -> pd.DataFrame:
    if weekly_df.empty:
        return pd.DataFrame(columns=weekly_df.columns)
    # keep latest weekly row per symbol
    last_week = weekly_df.sort_values(["symbol", "Datetime"]).groupby("symbol").tail(1)
    if movers_set:
        last_week = last_week[last_week["symbol"].isin(movers_set)]
    # if Opportunity column exists and user filtered, apply it
    if signal_type in ("LONG", "SHORT") and "Opportunity" in last_week.columns:
        last_week = last_week[last_week["Opportunity"] == signal_type]
    # rename columns for display consistency
    last_week = last_week.rename(columns={"symbol": "Symbol", "open": "Open", "high": "High", "low": "Low", "close": "Close"})
    # round floats to 3 decimals
    float_cols = last_week.select_dtypes(include="number").columns
    last_week[float_cols] = last_week[float_cols].round(3)
    # ensure Datetime is YYYY-MM-DD string
    last_week["Datetime"] = pd.to_datetime(last_week["Datetime"]).dt.strftime("%Y-%m-%d")
    return last_week[["Datetime", "Symbol", "Open", "High", "Low", "Close"] + ([ "Opportunity" ] if "Opportunity" in last_week.columns else [])]
