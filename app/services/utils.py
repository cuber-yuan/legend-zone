from datetime import datetime, timezone
from ..db import get_db_connection


def utc_now_iso():
    """Current UTC instant as ISO-8601 with a trailing Z (e.g. 2026-10-10T00:53:49Z).

    All created_at values are stored in UTC so a DB copied between machines in
    different timezones still represents the same instants; the browser renders
    them in the viewer's local time.
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


__all__ = ['get_db_connection', 'utc_now_iso']
