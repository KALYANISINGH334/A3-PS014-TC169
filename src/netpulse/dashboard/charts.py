"""Plotly figures with consistent units, hover detail, and dark styling."""
import plotly.express as px

from dashboard.analytics import METRICS, valid_observations

COLORS = ["#49c8ee", "#9a8cff", "#4cd6a5", "#f5b76b"]


def style(figure, y_title):
    figure.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                         font=dict(family="Arial, sans-serif", color="#cdd9ed"),
                         margin=dict(l=12, r=12, t=30, b=12), height=340,
                         legend_title_text="Access medium", hovermode="closest", yaxis_title=y_title)
    figure.update_xaxes(gridcolor="#1c2941", zeroline=False)
    figure.update_yaxes(gridcolor="#1c2941", zeroline=False)
    return figure


def history_chart(frame, metric):
    title, unit, _ = METRICS[metric]
    title = title.replace("Median ", "")
    data = valid_observations(frame).dropna(subset=[metric]).sort_values("timestamp")
    # Plot individual observations; a line would imply unmeasured intermediate values.
    fig = px.scatter(data, x="timestamp", y=metric, color="access_medium", color_discrete_sequence=COLORS,
                     hover_data={"status": True, "medium_verified": True, "isp": True},
                     labels={"timestamp": "Observation time (UTC)", metric: f"{title} ({unit})", "access_medium": "Access medium"})
    fig.update_traces(marker=dict(size=8, opacity=0.85))
    return style(fig, f"{title} ({unit})")


def distribution_chart(frame):
    data = valid_observations(frame).dropna(subset=["latency_ms"])
    fig = px.histogram(data, x="latency_ms", color="access_medium", color_discrete_sequence=COLORS,
                       barmode="overlay", opacity=0.75, nbins=20,
                       labels={"latency_ms": "Latency (ms)", "access_medium": "Access medium"})
    return style(fig, "Observation count")


def comparison_chart(groups, metric):
    title, unit, _ = METRICS[metric]
    data = groups.dropna(subset=[metric]).copy()
    data["sample"] = data[metric + "_n"].map(lambda n: f"n={n}")
    fig = px.bar(data, x="access_medium", y=metric, color="access_medium", text="sample",
                 color_discrete_sequence=COLORS, hover_data={metric + "_n": True, "observations": True},
                 labels={"access_medium": "Access medium", metric: f"{title} ({unit})", metric + "_n": "Metric samples"})
    fig.update_layout(showlegend=False)
    fig.update_traces(textposition="outside", cliponaxis=False)
    return style(fig, f"{title} ({unit})")


def daily_chart(frame, metric):
    from dashboard.analytics import daily_summary
    data = daily_summary(frame, metric)
    label, unit, _ = METRICS[metric]
    fig = px.line(data, x='day', y='median', color='access_medium', markers=True,
                  color_discrete_sequence=COLORS, hover_data=['count', 'q25', 'q75'],
                  labels={'day': 'Day (UTC)', 'median': f'Daily median ({unit})', 'count': 'Available samples',
                          'q25': f'25th percentile ({unit})', 'q75': f'75th percentile ({unit})'})
    return style(fig, f'Daily median {label.lower()} ({unit})')


def box_chart(frame, metric):
    data = valid_observations(frame).dropna(subset=[metric]).copy()
    data["samples"] = data.groupby("access_medium")[metric].transform("count")
    label, unit, _ = METRICS[metric]
    label = label.replace("Median ", "")
    fig = px.box(data, x='access_medium', y=metric, color='access_medium', points=False,
                 color_discrete_sequence=COLORS, hover_data={'samples': True},
                 labels={'access_medium': 'Access medium', metric: f'{label} ({unit})', 'samples': 'Available samples'})
    fig.update_layout(showlegend=False)
    return style(fig, f'{label} ({unit})')


def count_chart(frame, by_day=False):
    data = frame.copy()
    key = 'day' if by_day else 'access_medium'
    if by_day:
        data['day'] = data.timestamp.dt.floor('D')
    counts = data.groupby(key).size().reset_index(name='observations')
    fig = px.bar(counts, x=key, y='observations', text='observations', color_discrete_sequence=COLORS,
                 labels={key: 'Day (UTC)' if by_day else 'Access medium', 'observations': 'Observation count'})
    return style(fig, 'Observation count')


def completeness_chart(frame):
    from dashboard.analytics import completeness
    data = completeness(frame).melt(id_vars='metric', var_name='coverage', value_name='observations')
    fig = px.bar(data, x='metric', y='observations', color='coverage', barmode='stack',
                 color_discrete_map={'Available': COLORS[0], 'Missing / failed': '#52617a'},
                 labels={'metric': 'Metric', 'observations': 'Observation count', 'coverage': 'Coverage'})
    fig.update_layout(legend_title_text='Coverage')
    return style(fig, 'Observation count')
