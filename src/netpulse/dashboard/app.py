"""Run from the repository root: python -m streamlit run dashboard/app.py."""
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Streamlit executes this file as a script; make the project packages importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from backend.models import AccessMedium, MeasurementCreate
from dashboard.analytics import METRICS, comparisons, filter_frame, format_metric, summaries, to_frame, valid_observations, comparison_explanation
from dashboard.api import APIClient, APIError
from dashboard.charts import comparison_chart, history_chart, daily_chart, box_chart, count_chart, completeness_chart
from dashboard.demo_data import DEMO_LABEL, generate_demo_records

st.set_page_config(page_title="NetPulse · Network intelligence", page_icon="◉", layout="wide", initial_sidebar_state="auto")
st.markdown("""<style>
.block-container {padding-top:4rem; padding-bottom:2rem; max-width:1500px;}
[data-testid="stSidebar"] {border-right:1px solid #23304b;}
[data-testid="stMetric"] {background:linear-gradient(135deg,#14223c,#101a30);border:1px solid #263654;border-radius:14px;padding:18px;min-height:145px;}
[data-testid="stMetricLabel"] {color:#a9bbd5;}
[data-testid="stMetricValue"] {font-size:1.65rem;color:#eef5ff;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px;}
h1,h2,h3 {letter-spacing:-0.035em;}
.eyebrow {color:#49c8ee;letter-spacing:0.16em;font-size:0.72rem;font-weight:700;margin-bottom:8px;}
.brand {font-size:1.7rem;font-weight:800;letter-spacing:-1px;color:#eef5ff;}
.brand span {color:#49c8ee;}
.note {color:#94a9c8;font-size:0.85rem;line-height:1.6;}
.stButton>button {border-radius:9px;transition:background .15s ease;}
@media (max-width:700px) {.block-container {padding:4rem 1rem 1rem;} [data-testid="stMetricValue"] {font-size:1.3rem;}}
</style>""", unsafe_allow_html=True)

PAGES = ["Overview", "Live Measurements", "Access Medium Comparison", "Historical Trends", "Data Quality & Methodology", "Settings & About"]
DESCRIPTIONS = {
    "Overview": "Understand your observed internet quality, with evidence behind every number.",
    "Live Measurements": "Consenting device collectors upload genuine observations on a configurable schedule.",
    "Access Medium Comparison": "Compare verified labels within this pilot, with metric-specific sample counts.",
    "Historical Trends": "Explore observation timing, variability, and access-medium differences.",
    "Data Quality & Methodology": "Know what was measured, what is missing, and what the pilot can support.",
    "Settings & About": "Connection settings, scope, and the next steps toward live measurement.",
}

with st.sidebar:
    st.markdown('<div class="brand">◉ Net<span>Pulse</span></div>', unsafe_allow_html=True)
    st.caption("INTERNET QUALITY · LIMITED PILOT")
    st.divider()
    page = st.radio("Workspace", PAGES, key="page", label_visibility="collapsed")
    st.divider()
    demo_mode = st.toggle("Demo Mode", value=False, key="demo_mode", help="Separate fictional dataset; never uploaded or mixed with real observations.")
    st.caption("Illustrative preview" if demo_mode else "Actual API observations only")
    st.button("Refresh API data", width="stretch")
    auto_refresh = st.checkbox("Auto refresh every 45 seconds", value=True)

@st.fragment(run_every=timedelta(seconds=45) if auto_refresh else None)
def render_workspace():
    if st.session_state.pop("_netpulse_navigation", False):
        st.rerun(scope="app")
    page = st.session_state.page
    client = None
    health_ok = False
    health_error = None
    data_error = None
    frame = to_frame([])
    total = 0
    checked_at = datetime.now(timezone.utc)
    try:
        client = APIClient()
        try:
            client.health()
            health_ok = True
        except APIError as exc:
            health_error = str(exc)
        try:
            if not demo_mode:
                result = client.measurements()
                frame = to_frame([item.model_dump(mode="json") for item in result.items])
                total = result.total
        except APIError as exc:
            data_error = str(exc)
    except APIError as exc:
        health_error = data_error = str(exc)

    if demo_mode:
        frame = to_frame(generate_demo_records())
        frame["access_medium"] = frame.access_medium.replace({"Cellular": "Mobile data"})
        total = len(frame)
        data_error = None
        st.warning(DEMO_LABEL)
        st.caption("420 fictional observations · 12 fictional participants · 5–11 January 2026 (UTC). Labels are illustrative, not verified. No demo records are saved or uploaded.")

    st.markdown('<div class="eyebrow">AIORI-3 / PS-014 · NETPULSE</div>', unsafe_allow_html=True)
    header, connection = st.columns([3, 1])
    with header:
        st.title(page)
        st.write(DESCRIPTIONS[page])
    with connection:
        if health_ok:
            st.success("Backend responding · /health")
        else:
            st.error("Backend unavailable")
        st.caption(f"Health checked {checked_at:%Y-%m-%d %H:%M:%S} UTC")
    successes = frame[frame.status.eq("success")]
    last = successes.timestamp.max() if not successes.empty else None
    st.caption(("Latest complete illustrative observation: " if demo_mode else "Last successful measurement: ") + (f"{last:%Y-%m-%d %H:%M:%S} UTC" if last is not None else "No successful observations available"))
    if health_error:
        st.warning(health_error)
    if data_error:
        st.error(data_error + " Statistics are unavailable; no cached data is being shown.")
    if total > len(frame):
        st.warning(f"Viewing the latest {len(frame):,} of {total:,} stored attempts. All filters and statistics apply only to this loaded window.")


    def filters(data):
        filter_key = f"{demo_mode}_{page}"
        with st.expander("Filter observations", expanded=True):
            if data.empty:
                st.caption("Filters become available when this mode has observations.")
                return data
            dates = data.timestamp.dt.date
            left, right = st.columns(2)
            with left:
                selected_dates = st.date_input("Date range (UTC)", value=(dates.min(), dates.max()), min_value=dates.min(), max_value=dates.max(), key=f"dates_{filter_key}")
            with right:
                mediums = sorted(data.access_medium.unique())
                chosen = st.multiselect("Access medium", mediums, default=mediums, key=f"mediums_{filter_key}")
            participants = sorted(data.participant_id.dropna().unique())
            selected_participants = st.multiselect("Participant (pseudonymous ID)", participants, default=participants, key=f"participants_{filter_key}") if participants else None
            include_imports = st.checkbox("Include records without a participant ID", value=True) if participants else True
            verified = st.checkbox("Only verified access-medium labels", value=False, key=f"verified_{filter_key}", disabled=demo_mode)
            if len(selected_dates) != 2:
                st.info("Select both a start and end date.")
                return data.iloc[0:0]
            result = filter_frame(data, selected_dates[0], selected_dates[1], chosen, verified)
            if selected_participants is not None:
                result = result[result.participant_id.isin(selected_participants) | (result.participant_id.isna() & include_imports)]
            st.caption(f"{len(result):,} matching attempts · timestamps and date filters use UTC")
            return result


    def kpis(data):
        stats = summaries(data)
        cards = [*st.columns(4), *st.columns(3)]
        cards[0].metric("Observations", ("—" if data_error else f"{len(data):,}"), help="All attempts in the selected mode and filtered window, including failed attempts.")
        for column, (key, (label, unit, help_text)) in zip(cards[1:5], METRICS.items()):
            value = valid_observations(data)[key].mean() if key == "packet_loss_pct" else stats[key]["median"]
            column.metric("Average packet loss" if key == "packet_loss_pct" else label, format_metric(value, unit), help=f"Available values only; n={stats[key]['count']}. " + ("Arithmetic mean of observation loss percentages, not pooled probe loss." if key == "packet_loss_pct" else help_text))
        cards[5].metric("Participants", "—" if data_error else str(data.participant_id.nunique()), help="Distinct pseudonymous IDs; repeated observations are not independent participants.")
        latest = data.timestamp.max()
        cards[6].metric("Latest observation", "—" if pd.isna(latest) else latest.strftime("%d %b %H:%M"), help="Latest filtered attempt, including partial or failed records. UTC; year and exact time shown below.")
        if not pd.isna(latest):
            st.caption(f"Latest observation: {latest:%Y-%m-%d %H:%M:%S} UTC")
        st.caption("Metric cards show medians (packet loss: arithmetic mean) of available values from successful/partial observations. Missing values are —, never zero.")


    def recent_table(data):
        st.subheader("Recent observations")
        if data.empty:
            st.info("No observations match this view. Import actual measurements or adjust your filters.")
            return
        left, right = st.columns(2)
        status = left.multiselect("Measurement status", ["success", "partial", "failed"], default=["success", "partial", "failed"])
        order = right.selectbox("Time order", ["Newest first", "Oldest first"])
        table = data[data.status.isin(status)].sort_values("timestamp", ascending=order == "Oldest first").head(100).copy()
        table["timestamp"] = table.timestamp.dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            "timestamp": "Timestamp (UTC)", "access_medium": "Access medium", "medium_verified": "Label verified",
            "verification_source": "Verification source", "latency_ms": st.column_config.NumberColumn("Latency (ms)", format="%.2f"),
            "packet_loss_pct": st.column_config.NumberColumn("Packet loss (%)", format="%.2f"),
            "dns_ms": st.column_config.NumberColumn("DNS delay (ms)", format="%.2f"),
            "throughput_mbps": st.column_config.NumberColumn("Throughput (Mbps)", format="%.2f")})
        st.caption("Up to 100 matching records. Click a column header to sort. Blank cells represent missing data.")


    def comparison_view(data):
        st.subheader("Illustrative access-medium comparison" if demo_mode else "Verified access-medium comparison")
        groups = comparisons(data, illustrative=demo_mode)
        if groups.empty:
            st.info("No verified successful/partial observations match this view. Unverified labels are excluded from comparison.")
            return
        if demo_mode:
            st.info("Fictional categories are shown without treating their labels as verified.")
        st.caption("Verification sources are declared by the uploader, not independently audited by NetPulse. Compare only observations collected under comparable conditions.")
        if len(groups) < 2:
            st.info("Only one verified category is available. At least two are needed for a between-medium comparison.")
        if (groups.observations < 5).any():
            st.warning("Small pilot samples: at least one category has fewer than 5 observations. Five is a display caution threshold, not evidence of statistical adequacy.")
        columns = st.columns(2)
        for index, (key, (label, unit, _)) in enumerate(METRICS.items()):
            with columns[index % 2]:
                st.markdown(f"**{label} · {unit}**")
                if groups[key].notna().any():
                    st.plotly_chart(comparison_chart(groups, key), width="stretch", key=f"compare_{key}")
                    missing = groups[groups[key + "_n"].eq(0)].access_medium.tolist()
                    if missing:
                        st.caption("No metric samples for: " + ", ".join(missing))
                else:
                    st.info("No values collected for this metric.")
        st.write(comparison_explanation(groups, demo=demo_mode))
        st.caption("RTT IQR spans the 25th–75th percentiles. Missing-any % counts eligible observations missing at least one of the four metrics. Failed attempts are excluded here; coverage charts include them.")
        names = {"access_medium": "Access medium", "observations": "Observations", "participants": "Participants",
                 "latency_ms": "Median RTT (ms)", "latency_q25_ms": "RTT Q25 (ms)", "latency_q75_ms": "RTT Q75 (ms)",
                 "packet_loss_pct": "Median packet loss (%)", "dns_ms": "Median DNS delay (ms)",
                 "throughput_mbps": "Median download (Mbps)", "missing_any_pct": "Missing any metric (%)"}
        names.update({key + "_n": f"{METRICS[key][0]} samples" for key in METRICS})
        st.dataframe(groups.rename(columns=names), hide_index=True, width="stretch")
        st.caption("n is the number of non-missing samples for that metric. Medians describe this pilot; they do not establish a universally superior medium or causation.")


    def history_view(data):
        st.subheader("Observation timeline")
        daily = st.checkbox("Aggregate by UTC day", value=True, key="daily_trends")
        tabs = st.tabs(["Latency", "Packet loss", "DNS delay", "Throughput", "Latency distribution"])
        valid = valid_observations(data)
        for tab, key in zip(tabs[:4], METRICS):
            with tab:
                if valid[key].notna().any():
                    st.plotly_chart((daily_chart(data, key) if daily else history_chart(data, key)), width="stretch", key=f"history_{key}")
                    st.caption("Daily points are medians of available observations; hover for quartiles and sample counts. Lines connect summaries, not continuous measurements. Turn aggregation off to see individual observations.")
                else:
                    st.info("No measured values are available for this metric in the selected window.")
        with tabs[4]:
            if valid.latency_ms.notna().any():
                st.plotly_chart(box_chart(data, "latency_ms"), width="stretch")
            else:
                st.info("A latency distribution will appear when actual latency samples are available.")


    def collection_status(data):
        st.subheader("Collector observations")
        if demo_mode:
            st.info("Demo observations do not represent active collectors. Switch Demo Mode OFF to see genuine uploads and freshness.")
            return
        if data_error:
            st.info("Collection status is unavailable while the API cannot be read.")
            return
        collected = data[data.device_id.notna()].sort_values("timestamp", ascending=False)
        if collected.empty:
            st.info("No collector uploads yet. Start a configured consenting-device agent. This is not a live heartbeat.")
            return
        latest = collected.drop_duplicates("device_id").copy()
        age = (pd.Timestamp.now(tz="UTC") - latest.timestamp).dt.total_seconds()
        interval = pd.to_numeric(latest.collection_interval_seconds, errors="coerce").fillna(300)
        latest["upload_freshness"] = ["Recent observation" if elapsed <= expected * 2 + 60 else "No recent observation" for elapsed, expected in zip(age, interval)]
        latest["timestamp"] = latest.timestamp.dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        st.dataframe(latest[["participant_id", "device_id", "timestamp", "status", "access_medium", "medium_verified", "network_changed", "upload_freshness", "collection_errors"]], hide_index=True, width="stretch")
        st.caption("Freshness is inferred from received observation times, not a process heartbeat. Missing uploads may indicate an offline/stopped device or a queued retry. IDs distinguish devices; no precise location is collected.")


    def go_live():
        st.session_state.page = "Live Measurements"
        st.session_state["_netpulse_navigation"] = True


    if page in {"Overview", "Access Medium Comparison", "Historical Trends"}:
        filtered = filters(frame)
        kpis(filtered)
        st.divider()
        if page == "Overview":
            with st.container(border=True):
                st.subheader("Evidence before rankings")
                st.write("Explore latency, reliability, DNS delay, and throughput together. A fast connection can still have inconsistent response times; a single number cannot describe its quality.")
                if frame.empty and not data_error:
                    st.info("Your workspace is connected and empty. Start the collector or import actual observations. Enable Demo Mode in the sidebar for a clearly labelled illustrative preview.")
                st.button("Open measurement workspace", on_click=go_live, type="primary")
            left, right = st.columns([2, 1])
            with left:
                st.subheader("Latency over time")
                if valid_observations(filtered).latency_ms.notna().any():
                    st.plotly_chart(history_chart(filtered, "latency_ms"), width="stretch")
                else:
                    st.info("No latency samples yet. Your first real observation will appear here.")
            with right:
                with st.container(border=True):
                    st.subheader("Observation coverage")
                    st.metric("Verified labels", ("—" if data_error else f"{int(filtered.medium_verified.sum()):,}"))
                    st.metric("Failed attempts", ("—" if data_error else f"{int(filtered.status.eq('failed').sum()):,}"))
                    st.caption("Verified means a declared participant attestation or operator record. No IP-based inference is used.")
            st.subheader("Sample coverage & variability")
            chart_specs = [("Packet loss over time", lambda: daily_chart(filtered, "packet_loss_pct")),
                           ("DNS delay by medium", lambda: box_chart(filtered, "dns_ms")),
                           ("Download throughput by medium", lambda: box_chart(filtered, "throughput_mbps")),
                           ("RTT distribution by medium", lambda: box_chart(filtered, "latency_ms")),
                           ("Observations by medium", lambda: count_chart(filtered)),
                           ("Observations by day", lambda: count_chart(filtered, by_day=True)),
                           ("Data completeness", lambda: completeness_chart(filtered))]
            if filtered.empty:
                st.info("No observations match these filters.")
            else:
                chart_columns = st.columns(2)
                for index, (title, make_chart) in enumerate(chart_specs):
                    with chart_columns[index % 2]:
                        st.markdown(f"**{title}**")
                        metric_key = {0: "packet_loss_pct", 1: "dns_ms", 2: "throughput_mbps", 3: "latency_ms"}.get(index)
                        if metric_key and not valid_observations(filtered)[metric_key].notna().any():
                            st.info("No available values for this metric in the selected window.")
                        else:
                            st.plotly_chart(make_chart(), width="stretch", key=f"overview_extra_{index}")
                st.caption("Boxes show median and quartiles; only available successful/partial metric values contribute. Coverage counts include all attempts. No missing values are replaced by zero.")
            collection_status(filtered)
            recent_table(filtered)
        elif page == "Access Medium Comparison":
            comparison_view(filtered)
        else:
            history_view(filtered)
            recent_table(filtered)

    elif page == "Live Measurements" and demo_mode:
        st.info("This is an illustrative preview, not live collection. Switch Demo Mode OFF to inspect genuine collector uploads or import an actual observation. Real collectors continue independently.")
        recent_table(frame)

    elif page == "Live Measurements":
        with st.container(border=True):
            st.subheader("Automatic device collection")
            st.write("The background agent runs on each consenting device, normally every five minutes. Start it with start_netpulse.bat; this dashboard only reads its uploaded observations.")
            st.button("Run Measurement", disabled=True, help="Collection runs in the device agent, not the dashboard server. Use the Windows launcher or python -m agent.")
            st.caption("Default approved target: 1.1.1.1, three ICMP probes. DNS: example.com. Throughput stays disabled. Stop with stop_netpulse.bat or python -m agent --stop; set enabled=false in targets.json to disable collection.")
        collection_status(frame)
        if "import_success" in st.session_state:
            st.success(st.session_state.pop("import_success"))
        with st.expander("Import an actual observation", expanded=True):
            st.write("This saves a measurement you already collected elsewhere. It does not run a network test. Import only genuine observations with known units; omit metrics that were not measured.")
            with st.form("import_observation", clear_on_submit=False):
                timestamp = st.text_input("Observed at (ISO 8601 with timezone)", placeholder="Enter the actual observation timestamp with Z or +05:30")
                a, b = st.columns(2)
                medium = a.selectbox("Access medium", [item.value for item in AccessMedium])
                source = b.selectbox("Label verification source", ["unverified", "participant_attestation", "operator_record"])
                a, b = st.columns(2)
                isp = a.text_input("ISP label (optional)", max_chars=80, help="Use a provider name only, not an account number or address.")
                location = b.selectbox("Location category", ["unknown", "urban", "suburban", "rural"])
                status = st.selectbox("Measurement status", ["success", "partial", "failed"])
                values = {}
                columns = st.columns(2)
                for index, (key, (label, unit, _)) in enumerate(METRICS.items()):
                    maximum = 100.0 if key == "packet_loss_pct" else 1000000.0 if key == "throughput_mbps" else 60000.0
                    values[key] = columns[index % 2].number_input(f"{label.replace('Median ', '')} ({unit})", min_value=0.0, max_value=maximum, value=None, step=0.1, placeholder="Not measured", key=f"input_{key}")
                attested = st.checkbox("These are actual observations; the timestamp and declared verification source are accurate.")
                submitted = st.form_submit_button("Validate & save observation", type="primary", disabled=client is None or not health_ok)
            if submitted:
                if not attested:
                    st.error("Confirm that this is an actual observation before importing.")
                else:
                    try:
                        payload = MeasurementCreate(timestamp=timestamp, access_medium=medium, medium_verified=source != "unverified",
                                                    verification_source=source, isp=isp or None, location_category=location, status=status, **values)
                        with st.spinner("Validating and saving through the API…"):
                            saved = client.create(payload)
                        st.session_state.import_success = f"Observation #{saved.id} saved to SQLite through the API. This was an import, not a live measurement."
                        st.rerun()
                    except ValidationError as exc:
                        for error in exc.errors(include_input=False):
                            field = ".".join(str(part) for part in error["loc"]) or "Observation"
                            st.error(f"{field}: {error['msg']}")
                    except APIError as exc:
                        st.error(str(exc))
        recent_table(frame)

    elif page == "Data Quality & Methodology":
        st.info("Demo mode uses fixed, fictional, unverified labels in memory only. Real mode reads only the API. Illustrative values explain the proposed interface; they are not evidence about any ISP or medium.")
        st.plotly_chart(completeness_chart(frame), width="stretch")
        st.subheader("Coverage of the loaded observation window")
        rows = []
        for key, (label, unit, _) in METRICS.items():
            count = None if data_error else summaries(frame)[key]["count"]
            rows.append({"Metric": label, "Unit": unit, "Available samples": count, "Missing / failed attempts": None if count is None else len(frame) - count})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown("""
    ### What each metric means
    - **Latency (ms):** round-trip time to a declared target. The agent records the median ICMP echo RTT from up to five bounded probes. Windows ping results below 1ms are censored: they contribute a reply, but no invented latency value.
    - **Packet loss (%):** unanswered probes divided by probes sent, multiplied by 100. Record probe count and timeout in the external measurement procedure. ICMP blocking can look like loss and must be distinguished from connection failure.
    - **DNS delay (ms):** elapsed time for a hostname lookup using a documented resolver. Cache hits, resolver choice, and hostname affect the result. The agent times the system resolver for the configured DNS hostname. It does not clear caches; cached answers are possible.
    - **Throughput (Mbps):** transferred bytes × 8 divided by elapsed seconds and 1,000,000. The agent requires an explicitly approved download endpoint, a byte budget, a total timeout, and a separate throughput interval of at least 30 minutes. Link speed is not measured internet throughput.

    ### Labels and missing values
    Wi-Fi and Ethernet describe the local access link; Cellular is a direct cellular connection. They do not identify the ISP's upstream technology. **An IP address cannot verify the local medium.** Verify through participant attestation or an operator record, and declare the source. NetPulse records that declaration; it does not independently authenticate it.

    A blank value is **not measured**, not zero. A measured 0% loss remains zero. Failed attempts are retained in attempt counts and excluded from metric medians. Partial observations contribute only their non-missing metrics. Historical charts show actual points without interpolation. Comparisons include only verified successful/partial observations and show per-metric sample counts.

    ### Interpret with care
    Sample size, time of day, target, ISP, location category, device, and concurrent traffic all influence observations. Agent records include pseudonymous participant/device IDs, target ID, method, probe counts, bytes transferred, schedule interval, and diagnostic codes. The target ID maps to local configuration; target addresses, interface names, MACs, SSIDs, and exact locations are not uploaded. Imported records can lack provenance. Confirmed labels are downgraded if the routed interface no longer matches the participant confirmation; changes within one Wi-Fi interface may not be detected. Repeated observations from one participant are not independent samples.

    This is a **limited pilot**, not a nationwide ranking or proof of causation. Small samples cannot establish that one access medium is universally superior. The five-observation warning threshold is an interface cue, not a statistical test. Medians summarize available observations; no confidence or causal claims are computed.

    ### Privacy and storage
    Only coarse location categories and optional ISP labels are stored. Do not enter precise addresses, names, account identifiers, or other personal data. The API supports NETPULSE_UPLOAD_TOKEN for both reading and writing observations. Local loopback use needs no token; a central deployment requires HTTPS, access controls, informed volunteer consent, and a securely shared token. Pseudonyms are not authenticated participant identities. Demo Mode is an explicitly labelled, isolated UI dataset. It is never uploaded, stored in SQLite, or combined with actual observations. Fictional providers and pseudonyms are not real participants.
    """)

    else:
        st.subheader("Connection & runtime")
        if client:
            st.code(client.base_url, language=None)
        st.write("Set NETPULSE_API_URL before starting Streamlit. Set NETPULSE_DB_PATH before starting FastAPI. Run both commands from the project root. Environment files are examples and are not loaded automatically.")
        st.code('python -m uvicorn backend.main:app --reload --port 8000\npython -m streamlit run dashboard/app.py', language="bash")
        st.info("The dashboard refreshes every 45 seconds when enabled. The collector independently measures every 300 seconds by default. Refreshing does not send probes.")
        st.subheader("Prototype scope")
        st.write("NetPulse combines device-side ICMP/DNS collection, durable uploads, FastAPI, SQLite, and Streamlit/Plotly analytics. AI model assistance is not implemented. Real mode uses only stored actual observations or genuine imports. Demo mode uses a separate fixed illustrative dataset; it is not measurement evidence.")
        st.caption("Future AI assistance should explain evidence and uncertainty, without generating measurement values. See README.md for setup, API schema, tests, and the recording script.")

    st.divider()
    st.caption("NETPULSE · Limited pilot prototype · PS-014 · No universal rankings · All times UTC")


render_workspace()
