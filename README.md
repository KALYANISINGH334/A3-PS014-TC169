 # NetPulse — Internet-Quality Comparison by Verified Access Medium

**Hackathon:** AIORI Hackathon 3  
**Problem Statement:** PS-014 — Pilot Internet-Quality Comparison by Verified Access Medium  
**Category:** Smart Cities  
**Team:** SYNORA  
**Team Code:** A3-PS014-TC169

## Team

| Name | Email |
|------|------|
| Kalyani Singh | kalyanising997@gmail.com |
| Shruti Singh | SHRUTISINGH@200707 |
| Shikha Singh | ssingh8@lko.amity.edu |

## Intro Video

https://youtu.be/ycyPhKleZVQ

## Live Demo

https://a3-ps014-tc169-ntbkhtdkr3srltwqfsroms.streamlit.app/

## Overview

NetPulse is a prototype for monitoring and comparing internet connection quality across verified access media. It aims to help users understand network performance over time through measurable indicators and dashboard visualisations.

The project focuses on collecting network-performance observations, storing timestamped measurements, and presenting metrics and trends to support connectivity analysis.

## Approach

- **Measurement metrics:** Latency and packet loss, with throughput included where supported by the measurement implementation.
- **Measurement collection:** Collects network-quality observations for analysis.
- **Backend API:** Provides an interface for handling measurement data requests.
- **Data storage:** Stores observations with timestamps and relevant metadata.
- **Dashboard:** Presents measurements and performance trends through visualisations.
- **Comparison:** Supports examining network performance across access media when suitable, verified measurements are available.
- **Future work:** Extended pilot testing, broader access-medium validation, and improved live data collection.

## Repository Contents

| File or Directory | Description |
|------|-------------|
| `src/` | NetPulse application source code |
| `Proposed-structure-hackathon.pdf` | Project presentation following the AIORI proposed structure |
| `README.md` | Project overview, approach, links and references |
| `requirements.txt` | Python dependencies |

## Scope and Limitations

NetPulse is currently a prototype. Some dashboard values may be illustrative demo data rather than results from a completed field pilot. Live measurement availability depends on the deployed backend and API connectivity.

A broader pilot with verified access media, repeated measurements, and validation across different network conditions remains future work. Comparisons should account for measurement conditions and data quality before drawing conclusions about network performance.

## References

1. Paxson, V., Almes, G., Mahdavi, J., and Mathis, M. (1998). *Framework for IP Performance Metrics (RFC 2330).* IETF: https://www.rfc-editor.org/rfc/rfc2330.html
2. AIORI Hackathon 3. *PS-014: Pilot Internet-Quality Comparison by Verified Access Medium.* Problem statement, Smart Cities category.
3. AIORI Hackathon 3. *Proposed Structure for Hackathon Presentation.* October 2026.
