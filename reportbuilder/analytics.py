"""Privacy-minimizing report event analytics with offline country lookup only."""
from __future__ import annotations

import datetime as dt
import ipaddress
import logging
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import ReportAccess

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
EVENTS = tuple(x[0] for x in ReportAccess.EVENTS)
DEVICES = tuple(x[0] for x in ReportAccess.DEVICES)
BROWSERS = tuple(x[0] for x in ReportAccess.BROWSERS)
SYSTEMS = tuple(x[0] for x in ReportAccess.SYSTEMS)
MAX_DAYS = 366
RECENT_LIMIT = 100
XLSX_DETAIL_LIMIT = 10000
PDF_DETAIL_LIMIT = 500


class AnalyticsError(ValueError):
    code = "INVALID_ANALYTICS_FILTER"


def _ip(value):
    try:
        result = ipaddress.ip_address(str(value).strip())
        if getattr(result, "ipv4_mapped", None):
            result = result.ipv4_mapped
        return result
    except ValueError:
        return None


def client_address(request):
    """Trust XFF only from configured proxy CIDRs; walk right to left.

    The address is an ephemeral lookup input, never a model field or log value.
    A trusted proxy must append/overwrite XFF rather than passing arbitrary input.
    """
    remote = _ip(request.META.get("REMOTE_ADDR", ""))
    networks = []
    for value in getattr(settings, "REPORT_TRUSTED_PROXIES", []):
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    def trusted(address):
        return address is not None and any(address in network for network in networks)
    if not trusted(remote):
        return remote
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not isinstance(forwarded, str) or len(forwarded) > 2048:
        return remote
    parts = forwarded.split(",")
    if len(parts) > 32:
        return remote
    addresses = [_ip(value) for value in parts]
    if any(address is None for address in addresses):
        return remote
    candidate = remote
    for address in reversed(addresses):
        if not trusted(candidate):
            break
        candidate = address
    return candidate


def _geo_reader():
    path = getattr(settings, "REPORT_GEOIP_DATABASE", "")
    if not path or not Path(path).is_file():
        return None
    try:
        from geoip2.database import Reader
        return Reader(str(path))
    except (ImportError, OSError, ValueError):
        return None
    except Exception:
        # Corrupt/incompatible offline files must never cause a reporting outage.
        return None


def geolocation_status():
    reader = _geo_reader()
    available = reader is not None
    if reader is not None:
        reader.close()
    return {"available": available, "mode": "offline_geoip" if available else "unavailable",
            "unknown": "Unknown", "private": "Private"}


def country_for(address):
    if address is None:
        return "Unknown"
    if not address.is_global:
        return "Private"
    reader = _geo_reader()
    if reader is None:
        return "Unknown"
    try:
        code = reader.country(str(address)).country.iso_code
        return code if isinstance(code, str) and re.fullmatch(r"[A-Z]{2}", code) else "Unknown"
    except Exception:
        return "Unknown"
    finally:
        reader.close()


def user_agent_dimensions(value):
    agent = value[:4096].lower() if isinstance(value, str) else ""
    if not agent:
        return {"device": "unknown", "browser": "unknown", "os": "unknown"}
    bot = bool(re.search(r"bot|crawler|spider|headless|slurp|bingpreview", agent))
    ios = any(key in agent for key in ("iphone", "ipad", "ipod")) or ("macintosh" in agent and "mobile" in agent)
    if bot:
        device = "bot"
    elif "ipad" in agent or ("macintosh" in agent and "mobile" in agent) or "tablet" in agent or ("android" in agent and "mobile" not in agent):
        device = "tablet"
    elif "mobile" in agent or "iphone" in agent or "ipod" in agent:
        device = "mobile"
    elif any(key in agent for key in ("windows", "macintosh", "linux", "x11", "cros")):
        device = "desktop"
    else:
        device = "unknown"
    if any(key in agent for key in ("edg/", "edga/", "edgios/", "edge/")):
        browser = "edge"
    elif "opr/" in agent or "opera" in agent:
        browser = "opera"
    elif "firefox/" in agent or "fxios/" in agent:
        browser = "firefox"
    elif any(key in agent for key in ("chrome/", "crios/", "chromium/")):
        browser = "chrome"
    elif "safari/" in agent:
        browser = "safari"
    else:
        browser = "other"
    if ios:
        system = "ios"
    elif "android" in agent:
        system = "android"
    elif "windows" in agent:
        system = "windows"
    elif "cros" in agent:
        system = "chromeos"
    elif "macintosh" in agent or "mac os" in agent:
        system = "macos"
    elif "linux" in agent or "x11" in agent:
        system = "linux"
    else:
        system = "other"
    return {"device": device, "browser": browser, "os": system}


def record_report_access(request, report, event):
    """Call only after authorization and a successful response/execution.

    Collection failures do not poison outer transactions or block report use.
    No exception text, request identifier, raw IP, or UA is logged.
    """
    if not getattr(settings, "REPORT_ANALYTICS_ENABLED", True):
        return None
    if event not in EVENTS:
        return None
    try:
        dimensions = user_agent_dimensions(request.META.get("HTTP_USER_AGENT", ""))
        country = country_for(client_address(request))
        with transaction.atomic():
            return ReportAccess.objects.create(report=report, event=event, country=country, **dimensions)
    except Exception as exc:
        try:
            logger.warning("Report analytics recording failed (%s)", type(exc).__name__)
        except Exception:
            pass
        return None


def parse_filters(params):
    allowed = {"start", "end", "event", "country", "device", "browser"}
    if set(params) - allowed:
        raise AnalyticsError("지원하지 않는 통계 필터입니다.")
    if hasattr(params, "lists") and any(len(values) != 1 for _, values in params.lists()):
        raise AnalyticsError("동일 통계 필터를 여러 번 지정할 수 없습니다.")
    def text(name):
        value = params.get(name, "")
        if not isinstance(value, str) or len(value) > 64:
            raise AnalyticsError("통계 필터 값이 올바르지 않습니다.")
        return value.strip()
    def date_value(name, fallback):
        value = text(name)
        if not value:
            return fallback
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            return dt.date.fromisoformat(value)
        except ValueError:
            raise AnalyticsError("기간은 YYYY-MM-DD 형식의 실제 날짜여야 합니다.") from None
    today = timezone.localdate(timezone.now(), KST)
    end = date_value("end", today)
    try:
        start = date_value("start", end - dt.timedelta(days=29))
    except OverflowError:
        raise AnalyticsError("조회 가능한 날짜 범위를 벗어났습니다.") from None
    days = (end - start).days + 1
    if days < 1 or days > MAX_DAYS:
        raise AnalyticsError("통계 기간은 시작일을 포함하여 1일 이상 366일 이하로 지정하세요.")
    if start.year < 1970 or end.year > 9998:
        raise AnalyticsError("조회 가능한 날짜 범위를 벗어났습니다.")
    event, device, browser = text("event").lower(), text("device").lower(), text("browser").lower()
    if event and event not in EVENTS or device and device not in DEVICES or browser and browser not in BROWSERS:
        raise AnalyticsError("이벤트·기기·브라우저 필터가 올바르지 않습니다.")
    country = text("country")
    if country.lower() in {"unknown", "private"}:
        country = country.capitalize()
    elif country:
        country = country.upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise AnalyticsError("국가는 두 글자 ISO 코드, Unknown 또는 Private로 지정하세요.")
    try:
        end_exclusive = end + dt.timedelta(days=1)
    except OverflowError:
        raise AnalyticsError("조회 가능한 날짜 범위를 벗어났습니다.") from None
    return {"start": start, "end": end, "days": days,
            "start_at": dt.datetime.combine(start, dt.time.min, KST).astimezone(dt.timezone.utc),
            "end_at": dt.datetime.combine(end_exclusive, dt.time.min, KST).astimezone(dt.timezone.utc),
            "event": event, "country": country, "device": device, "browser": browser}


def statistics(report, params, detail_limit=RECENT_LIMIT):
    filters = parse_filters(params)
    if not 1 <= detail_limit <= XLSX_DETAIL_LIMIT:
        raise AnalyticsError("통계 상세 조회 한도가 올바르지 않습니다.")
    queryset = ReportAccess.objects.filter(report=report, created_at__gte=filters["start_at"], created_at__lt=filters["end_at"])
    for dimension in ("event", "country", "device", "browser"):
        if filters[dimension]:
            queryset = queryset.filter(**{dimension: filters[dimension]})
    # Ensure all counts and capped detail rows describe the same transaction
    # snapshot. Supported metadata stores are SQLite and PostgreSQL.
    own_transaction = not connection.in_atomic_block
    with transaction.atomic():
        if own_transaction and connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        total = queryset.count()
        def distribution(dimension):
            return list(queryset.values(dimension).annotate(count=Count("pk")).order_by("-count", dimension))
        counted_events = {item["event"]: item["count"] for item in distribution("event")}
        daily_counts = {item["day"]: item["count"] for item in queryset.annotate(day=TruncDate("created_at", tzinfo=KST)).values("day").annotate(count=Count("pk")).order_by("day")}
        recent = [{"timestamp": row["created_at"].astimezone(KST).isoformat(timespec="seconds"),
                   **{key: row[key] for key in ("event", "country", "device", "browser", "os")}}
                  for row in queryset.order_by("-created_at", "-pk").values("created_at", "event", "country", "device", "browser", "os")[:detail_limit]]
        result = {
            "report": {"id": str(report.pk), "name": report.name},
            "range": {"start": filters["start"].isoformat(), "end": filters["end"].isoformat(), "timezone": "Asia/Seoul", "days": filters["days"]},
            "filters": {key: filters[key] for key in ("event", "country", "device", "browser")},
            "total": total,
            "event_counts": [{"event": event, "count": counted_events.get(event, 0)} for event in EVENTS],
            "countries": distribution("country"), "devices": distribution("device"), "browsers": distribution("browser"),
            "daily": [{"date": (filters["start"] + dt.timedelta(days=day)).isoformat(), "count": daily_counts.get(filters["start"] + dt.timedelta(days=day), 0)} for day in range(filters["days"])],
            "recent": recent, "recent_limit": detail_limit, "details_total": total,
            "details_truncated": total > detail_limit, "details_omitted": max(total - detail_limit, 0),
            "meta": {"geolocation": geolocation_status(), "counts": "events_not_unique_visitors",
                     "timestamp_timezone": "Asia/Seoul", "raw_ip_stored": False, "raw_user_agent_stored": False},
        }
    return result
