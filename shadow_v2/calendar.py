"""Read-only HK calendar with an explicit continuous-session-close news convention."""
from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
from scripts.trading_calendar import HKEX_HOLIDAYS,is_hk_trading_day

# HKEX primary half-day calendars; auction-period news stays inside the news window.
# 2026: https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf
# 2027: https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2026/ce_SEHK_CT_077_2026.pdf
HALF_DAYS={'2026-02-16','2026-12-24','2026-12-31','2027-02-05','2027-12-24','2027-12-31'}

def previous_continuous_close(stamp):
    """Previous HK trading day's 12:00 half-day or 16:00 ordinary session end."""
    if stamp.tzinfo is None:raise ValueError('aware_cutoff_required')
    day=stamp.astimezone(ZoneInfo('Asia/Hong_Kong')).date()-timedelta(days=1)
    while True:
        if day.year not in HKEX_HOLIDAYS:raise ValueError('calendar_year_unavailable')
        if is_hk_trading_day(day):break
        day-=timedelta(days=1)
    return datetime.combine(day,time(12 if day.isoformat() in HALF_DAYS else 16),ZoneInfo('Asia/Hong_Kong'))
