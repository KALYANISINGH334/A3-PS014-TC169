"""Fixed fictional UI fixtures. Never upload these records or verify their labels."""
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

import numpy as np

DEMO_LABEL = "DEMO MODE — ILLUSTRATIVE DATA, NOT REAL MEASUREMENTS"


def generate_demo_records():
    """420 records, 12 fictional participants, seven fixed UTC days; no I/O."""
    rng = np.random.default_rng(1403)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    records = []
    for participant in range(12):
        medium = ["Wi-Fi", "Ethernet", "Cellular"][participant % 3]
        baseline = rng.uniform(18, 65)
        for day in range(7):
            for hour in [7, 11, 15, 19, 23]:
                timestamp = start + timedelta(days=day, hours=hour, minutes=int(rng.integers(0, 45)))
                busy = 1.35 if hour >= 19 else 1.0
                metrics = {
                    "latency_ms": round(float(rng.lognormal(np.log(baseline * busy), .3)), 2),
                    "packet_loss_pct": round(float(rng.choice([0, 0, 0, .5, 1, 2, 4]) * busy), 2),
                    "dns_ms": round(float(rng.lognormal(np.log(16 * busy), .6)), 2),
                    "throughput_mbps": round(float(rng.uniform(12, 180) / busy), 2),
                }
                for key, probability in zip(metrics, [.04, .06, .12, .35]):
                    if rng.random() < probability:
                        metrics[key] = None
                available = sum(value is not None for value in metrics.values())
                records.append(dict(id=len(records) + 1, timestamp=timestamp.isoformat(),
                                    participant_id=str(uuid5(NAMESPACE_URL, f'netpulse-fictional-participant-{participant + 1}')),
                                    access_medium=medium, medium_verified=False, verification_source='unverified',
                                    isp=f'Fictional Provider {chr(65 + participant % 4)}',
                                    location_category=['urban', 'suburban', 'rural'][participant // 4],
                                    status='success' if available == 4 else 'partial' if available else 'failed',
                                    **metrics))
    return records
