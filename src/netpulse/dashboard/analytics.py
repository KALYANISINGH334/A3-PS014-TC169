"""Pure functions shared by dashboard views and tests."""
import numpy as np
import pandas as pd

METRICS = {
    "latency_ms": ("Median latency", "ms", "Lower values mean a shorter round trip to the chosen target."),
    "packet_loss_pct": ("Packet loss", "%", "Median percentage of probes that received no response."),
    "dns_ms": ("Median DNS delay", "ms", "Time taken to resolve the chosen hostname; cache state matters."),
    "throughput_mbps": ("Median throughput", "Mbps", "Observed transfer rate for a documented, bounded transfer."),
}
COLUMNS = ["id", "timestamp", "access_medium", "medium_verified", "verification_source", "isp", "location_category", "status", "participant_id", "device_id", "observation_id", "interface_id", "network_changed", "target_id", "latency_method", "dns_method", "probe_count", "probe_replies", "throughput_bytes", "collection_interval_seconds", "collection_errors", *METRICS]


def to_frame(records):
    frame = pd.DataFrame(records, columns=COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for key in METRICS:
        frame[key] = pd.to_numeric(frame[key], errors="coerce").replace([np.inf, -np.inf], np.nan)
    frame["medium_verified"] = frame["medium_verified"].fillna(False).astype(bool)
    return frame


def filter_frame(frame, start=None, end=None, mediums=None, verified_only=False):
    result = frame.copy()
    if start is not None:
        result = result[result.timestamp.dt.date >= start]
    if end is not None:
        result = result[result.timestamp.dt.date <= end]
    if mediums is not None:
        result = result[result.access_medium.isin(mediums)]
    if verified_only:
        result = result[result.medium_verified & result.access_medium.ne("Unknown")]
    return result


def valid_observations(frame):
    return frame[frame.status.isin(["success", "partial"])]


def summaries(frame):
    valid = valid_observations(frame)
    return {key: {"median": float(valid[key].median()) if valid[key].notna().any() else None,
                  "count": int(valid[key].count())} for key in METRICS}


def comparisons(frame, illustrative=False):
    valid = valid_observations(frame)
    if not illustrative:
        valid = valid[valid.medium_verified & valid.access_medium.ne("Unknown")]
    rows = []
    for medium, group in valid.groupby("access_medium", sort=True):
        row = {"access_medium": medium, "observations": len(group), "participants": int(group.participant_id.nunique())}
        for key, summary in summaries(group).items():
            row[key] = summary["median"]
            row[key + "_n"] = summary["count"]
        row["latency_q25_ms"] = group.latency_ms.quantile(.25)
        row["latency_q75_ms"] = group.latency_ms.quantile(.75)
        row["missing_any_pct"] = float(group[list(METRICS)].isna().any(axis=1).mean() * 100)
        rows.append(row)
    return pd.DataFrame(rows, columns=["access_medium", "observations", "participants", *METRICS, *[key + "_n" for key in METRICS], "latency_q25_ms", "latency_q75_ms", "missing_any_pct"])


def format_metric(value, unit):
    return "—" if value is None or pd.isna(value) else f"{value:,.2f} {unit}"


def daily_summary(frame, metric):
    """UTC daily median and quartiles; no interpolation or missing-value fill."""
    data = valid_observations(frame).dropna(subset=['timestamp', metric]).copy()
    data['day'] = data.timestamp.dt.floor('D')
    return data.groupby(['day', 'access_medium'])[metric].agg(
        median='median', count='count', q25=lambda s: s.quantile(.25), q75=lambda s: s.quantile(.75)).reset_index()


def completeness(frame):
    valid = valid_observations(frame)
    return pd.DataFrame([{'metric': label, 'Available': int(valid[key].count()),
                          'Missing / failed': len(frame) - int(valid[key].count())}
                         for key, (label, _, _) in METRICS.items()])


def comparison_explanation(groups, demo=False):
    scope = 'illustrative sample' if demo else 'loaded pilot sample'
    if groups.empty:
        return 'No eligible observations match these filters.'
    available = groups.dropna(subset=['latency_ms'])
    description = f'This {scope} contains {int(groups.observations.sum()):,} eligible observations across {len(groups)} categories.'
    if len(available) >= 2:
        description += f" Median RTT ranges from {available.latency_ms.min():.2f} to {available.latency_ms.max():.2f} ms; sample counts and participant coverage differ."
    return description + (' Illustrative results cannot establish real-world superiority.' if demo else ' These observations cannot establish universal superiority or causation.')
