"""تبدیل تاریخ میلادی به شمشی (جلالی) — بدون وابستگی خارجی."""
from __future__ import annotations

import datetime as _dt

MONTHS_FA = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
             "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]

_G_DAYS = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def _is_leap(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def to_jalali(g: _dt.date | None) -> tuple[int, int, int] | None:
    """میلادی → (سال، ماه، روز) شمسی."""
    if g is None:
        return None
    gy, gm, gd = g.year, g.month, g.day
    gy2 = gy - 1600
    days = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    days += _G_DAYS[gm - 1] + gd - 1
    if gm > 2 and _is_leap(gy):
        days += 1
    days -= 79            # offset to 1 Farvardin 979
    j_np = days // 12053
    days %= 12053
    jy = 979 + 33 * j_np + 4 * (days // 1461)
    days %= 1461
    if days >= 366:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        d = days - 186
        jm, jd = 7 + d // 30, 1 + d % 30
    return jy, jm, jd


def to_gregorian(jy: int, jm: int, jd: int) -> _dt.date:
    """شمسی → میلادی."""
    jy -= 979
    days = (365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4) + 78 + jd
            + ([0, 31, 62, 93, 124, 155, 186, 216, 246, 276, 306, 336])[jm - 1])
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    feb = 29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28
    sal = [0, 31, feb, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > sal[gm]:
        gd -= sal[gm]
        gm += 1
    return _dt.date(gy + 1600, gm, gd)


def fmt(g, style: str = "numeric") -> str:
    """۱۴۰۱/۰۳/۱۵ یا ۱۵ خرداد ۱۴۰۱."""
    if g is None:
        return "—"
    if isinstance(g, str):
        try:
            g = _dt.date.fromisoformat(g[:10])
        except ValueError:
            return g
    if isinstance(g, _dt.datetime):
        g = g.date()
    jy, jm, jd = to_jalali(g)
    if style == "long":
        return f"{jd} {MONTHS_FA[jm - 1]} {jy}"
    if style == "month":
        return f"{MONTHS_FA[jm - 1]} {jy}"
    return f"{jy}/{jm:02d}/{jd:02d}"


if __name__ == "__main__":
    for iso in ["2019-12-16", "2022-06-30", "2026-08-19", "2021-03-21"]:
        d = _dt.date.fromisoformat(iso)
        print(iso, "→", fmt(d), "|", fmt(d, "long"))
