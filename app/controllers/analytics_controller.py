import asyncio
import os
from datetime import datetime
from typing import Dict

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunRealtimeReportRequest,
    RunReportRequest,
)
from google.oauth2 import service_account

_PROPERTY_ID = "properties/528274628"
_CREDENTIALS_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "google-analytics-credentials.json",
))
_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

_DATE_RANGES = {
    "today": ("today", "today"),
    "7d": ("7daysAgo", "today"),
    "30d": ("30daysAgo", "today"),
    "90d": ("90daysAgo", "today"),
}


def _get_client() -> BetaAnalyticsDataClient:
    creds = service_account.Credentials.from_service_account_file(
        _CREDENTIALS_PATH, scopes=_SCOPES
    )
    return BetaAnalyticsDataClient(credentials=creds)


def _safe_int(report, row: int, metric: int) -> int:
    try:
        return int(report.rows[row].metric_values[metric].value)
    except (IndexError, ValueError):
        return 0


def _safe_float(report, row: int, metric: int) -> float:
    try:
        return float(report.rows[row].metric_values[metric].value)
    except (IndexError, ValueError):
        return 0.0


def _format_label(dim_value: str, period: str) -> str:
    if period == "today":
        try:
            hour = int(dim_value[-2:])
            suffix = "AM" if hour < 12 else "PM"
            h = hour % 12 or 12
            return f"{h}{suffix}"
        except Exception:
            return dim_value
    else:
        try:
            dt = datetime.strptime(dim_value, "%Y%m%d")
            return f"{dt.strftime('%b')} {dt.day}"
        except Exception:
            return dim_value


def _fetch_sync(period: str) -> Dict:
    client = _get_client()
    start_date, end_date = _DATE_RANGES.get(period, ("today", "today"))
    trend_dim = "dateHour" if period == "today" else "date"
    date_range = [DateRange(start_date=start_date, end_date=end_date)]

    # Summary — no dimension
    summary_r = client.run_report(RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=date_range,
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="screenPageViews"),
            Metric(name="bounceRate"),
            Metric(name="averageSessionDuration"),
            Metric(name="newUsers"),
        ],
    ))

    # Trend — hourly (today) or daily
    trend_r = client.run_report(RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=date_range,
        dimensions=[Dimension(name=trend_dim)],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
            Metric(name="screenPageViews"),
        ],
        order_bys=[OrderBy(
            dimension=OrderBy.DimensionOrderBy(dimension_name=trend_dim)
        )],
    ))

    # Top 10 pages by views
    pages_r = client.run_report(RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=date_range,
        dimensions=[Dimension(name="pagePath")],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="sessions"),
            Metric(name="activeUsers"),
        ],
        order_bys=[OrderBy(
            metric=OrderBy.MetricOrderBy(metric_name="screenPageViews"),
            desc=True,
        )],
        limit=10,
    ))

    # New vs returning
    nvr_r = client.run_report(RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=date_range,
        dimensions=[Dimension(name="newVsReturning")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="activeUsers"),
        ],
    ))

    # Device category
    devices_r = client.run_report(RunReportRequest(
        property=_PROPERTY_ID,
        date_ranges=date_range,
        dimensions=[Dimension(name="deviceCategory")],
        metrics=[Metric(name="sessions")],
    ))

    # Realtime
    rt_r = client.run_realtime_report(RunRealtimeReportRequest(
        property=_PROPERTY_ID,
        metrics=[Metric(name="activeUsers")],
    ))

    # Parse summary
    bounce = _safe_float(summary_r, 0, 3)
    avg_dur = _safe_float(summary_r, 0, 4)
    summary = {
        "sessions": _safe_int(summary_r, 0, 0),
        "users": _safe_int(summary_r, 0, 1),
        "pageviews": _safe_int(summary_r, 0, 2),
        "bounce_rate": round(bounce * 100, 1),
        "avg_session_duration": round(avg_dur, 1),
        "new_users": _safe_int(summary_r, 0, 5),
    }

    # Parse trend
    trend = [
        {
            "label": _format_label(row.dimension_values[0].value, period),
            "sessions": int(row.metric_values[0].value or 0),
            "users": int(row.metric_values[1].value or 0),
            "pageviews": int(row.metric_values[2].value or 0),
        }
        for row in trend_r.rows
    ]

    # Parse top pages (truncate long paths)
    top_pages = [
        {
            "page": (p := row.dimension_values[0].value)[:38] + ("…" if len(p) > 38 else ""),
            "views": int(row.metric_values[0].value or 0),
            "sessions": int(row.metric_values[1].value or 0),
            "users": int(row.metric_values[2].value or 0),
        }
        for row in pages_r.rows
    ]

    # Parse new vs returning
    new_vs_returning = [
        {
            "type": row.dimension_values[0].value.replace("new", "New").replace("returning", "Returning"),
            "sessions": int(row.metric_values[0].value or 0),
            "users": int(row.metric_values[1].value or 0),
        }
        for row in nvr_r.rows
    ]

    # Parse devices
    devices = [
        {
            "device": row.dimension_values[0].value.capitalize(),
            "sessions": int(row.metric_values[0].value or 0),
        }
        for row in devices_r.rows
    ]

    # Realtime
    realtime_users = 0
    if rt_r.rows:
        try:
            realtime_users = int(rt_r.rows[0].metric_values[0].value)
        except (IndexError, ValueError):
            realtime_users = 0

    return {
        "realtime_users": realtime_users,
        "summary": summary,
        "trend": trend,
        "top_pages": top_pages,
        "new_vs_returning": new_vs_returning,
        "devices": devices,
    }


class AnalyticsController:

    @staticmethod
    async def get_overview(period: str = "today") -> Dict:
        loop = asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: _fetch_sync(period))
        except Exception as e:
            raise RuntimeError(f"GA4 API error: {e}") from e
        return {"status": 200, "success": True, "data": data}
