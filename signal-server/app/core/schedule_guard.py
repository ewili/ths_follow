"""运行时段判断工具。"""

from __future__ import annotations

from datetime import datetime, time


def is_within_schedule(
    weekdays: list[int],
    time_ranges: list[dict[str, str]],
    now: datetime | None = None,
) -> bool:
    """判断当前时间是否在允许运行的时段内。

    Args:
        weekdays: 允许运行的星期列表，1=周一, 7=周日。
        time_ranges: 时间段列表，每项含 start/end (HH:MM)。
        now: 可选的当前时间，默认取 datetime.now()。

    Returns:
        True 表示允许运行。weekdays 或 time_ranges 为空时返回 True（不限制）。
    """
    if not weekdays or not time_ranges:
        return True

    if now is None:
        now = datetime.now()

    # Python weekday(): 0=周一 → 转为 1=周一
    current_weekday = now.weekday() + 1
    if current_weekday not in weekdays:
        return False

    current_time = now.time().replace(microsecond=0)
    for tr in time_ranges:
        start = _parse_hhmm(tr.get("start", "00:00"))
        end = _parse_hhmm(tr.get("end", "23:59"))
        if start <= current_time <= end:
            return True

    return False


def _parse_hhmm(s: str) -> time:
    """将 HH:MM 字符串解析为 time 对象。"""
    parts = s.strip().split(":")
    return time(int(parts[0]), int(parts[1]))
