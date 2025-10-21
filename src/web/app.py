import streamlit as st
import base64
from pathlib import Path
from datetime import datetime
import pytz
import DataFetching as df

st.set_page_config(page_title="Stock Screener", layout="wide")

# --- helper to embed local background image as data-uri ---
def _get_base64_of_bin_file(bin_file_path: Path) -> str:
    with open(bin_file_path, "rb") as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_background(local_img_path: Path):
    if not local_img_path.exists():
        return
    img_b64 = _get_base64_of_bin_file(local_img_path)
    css = f"""
    <style>
    .stApp {{
      background-image: url("data:image/jpg;base64,{img_b64}");
      background-size: cover;
      background-position: center;
      background-attachment: fixed;
    }}
    .content-block {{
      background: rgba(255,255,255,0.85);
      padding: 18px;
      border-radius: 8px;
    }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)

# place a background image at: assets/background.jpg (project root)
assets_bg = Path(__file__).parents[1] / "assets" / "background.jpg"
set_background(assets_bg)

# --- Top disclaimer (always visible) ---
st.warning("Disclaimer: This is educational content only and not investment advice. Do your own research before trading.", icon="⚠️")
# Small IST time panel (shows current IST at page load)
ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
ist_str = ist_now.strftime("%Y-%m-%d %H:%M")
st.markdown(
    f"""
    <div style="display:flex; justify-content:flex-end; margin-bottom:8px;">
        <div style="padding:8px 12px; font-weight:700; border-radius: 8px; border: 2px solid #ffffff; background-color: rgba(255,255,255,0.02);">
        IST: {ist_str}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- Navigation: Home / Screener ---
tab_home, tab_screener = st.tabs(["Home", "Screener"])

with tab_home:
    st.title("Fakeout Stock Screener")

    st.markdown(
        """
        <div style="font-weight:700; padding: 18px; border-radius: 8px; border: 2px solid #ffffff; background-color: rgba(255,255,255,0.02);">
        <p style="font-size:2rem; font-weight:700;">
            What this screener shows ❓
        </p>
        <ol style="font-size:1rem; font-weight:400;">
            <li> Futures & Options stocks are selected using Weekly OHLC analysis. </li>
            <li> Default Filters applied: weekly fakeout signals (LONG/SHORT), and monthly movers (±3% threshold) to avoid consolidating stocks. </li>
            <li> In the following week when price retraces and closed below or above prior week's high/low, a fakeout is signaled. </li>
            <li> Additional filters can be applied on the Screener page. </li>
            <li> Datetime column is standardized to (YYYY-MM-DD). Numeric values are rounded to 3 decimals. </li>
            <li> Data is updated on daily basis at 12:00 IST after market close. </li>
        </ol>
        </div>
        """,
        unsafe_allow_html=True
    )

# ensure session state flags exist so we can disable button during processing
if 'processing' not in st.session_state:
    st.session_state['processing'] = False
if 'apply_filters' not in st.session_state:
    st.session_state['apply_filters'] = False

with tab_screener:
    st.header("Screener Page")

    # Use a Streamlit container to group widgets (widgets will render in Streamlit layout)
    box = st.container()
    with box:
        with st.form(key="filters_form"):
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                monthly_threshold = st.number_input(
                    "Monthly Movement Threshold (%)",
                    min_value=-10.0,
                    max_value=10.0,
                    value=3.0,
                    step=0.5,
                    format="%.1f",
                    help="Only include symbols that moved more than this percent in the previous month.",
                )

            with col2:
                signal_type = st.selectbox(
                    "Signal Type",
                    options=["Both", "LONG", "SHORT"],
                    index=0,
                    help="Filter by fakeout signal type.",
                )

            submitted = st.form_submit_button(
                "Apply Filters", 
                disabled=st.session_state.get('processing', False)
            )

        st.markdown("</div>", unsafe_allow_html=True)

    # Process only after Apply Filters pressed
    if submitted:
         # prevent duplicate concurrent runs
        if st.session_state.get('processing', False):
            st.warning("Processing already running. Please wait...")
        else:
            st.session_state['processing'] = True
            # create a single mutable placeholder for status messages
            status = st.empty()
            status.info("Applying filters — please wait.", icon="ℹ️")

            results_df = None
            try:
                with st.spinner("Fetching data from Database based on filters..."):
                    dailydf = df.fetch_dailydata_from_db()
                    if dailydf.empty or dailydf is None:
                        raise ValueError("No daily data fetched from database.")
                    
                    monthly_df = df.compute_monthly_movers_df(dailydf, monthly_threshold) # Get Monthly DF and filter stocks
                    prev_week_df = df.compute_prev_week_df(dailydf) # Get Prev weekly DF
                    curr_week_df = df.compute_curr_week_df(dailydf) # Get Current week DF
                    
                    results_df = df.find_eligible_tickers(monthly_df, prev_week_df, curr_week_df, signal_type)
                    print(results_df)
            except Exception as e:
                status.error(f"Data fetch/processing failed: {e}", icon="❌")
                results_df = None
            finally:
                st.session_state['processing'] = False
                # store last results in session_state to display after rerun
                st.session_state['_last_results'] = results_df
                st.session_state['_last_filters'] = {
                    "monthly_threshold": float(monthly_threshold),
                    "signal_type": signal_type,
                }

            # display outcome immediately (replace status message)
            if results_df is None:
                status.warning("Processing failed. Try again.", icon="⚠️")
            elif results_df.empty:
                status.warning("Processing completed - no matching symbols found.", icon="✅")
            else:
                status.success(f"Done — {len(results_df)} symbols matched.", icon="✅")
                csv_data = results_df.to_csv(index=False)
                st.download_button("Export CSV", data=csv_data, file_name="screener_export.csv", mime="text/csv")
                st.dataframe(results_df, width="stretch")
    else:
        st.info("Set filters and click 'Apply Filters' to run the screener.")
