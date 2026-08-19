"""استخراج ریسک، فرصت و «اقدام بعدی پیشنهادی»  —  MVP ۰۳ و ۰۴

فلسفهٔ طراحی: تمام محاسبه اینجا و قطعی انجام می‌شود؛ مدل زبانی فقط روایت
می‌کند. دلیل: عدد اشتباهی که مدل تولید کند، اعتماد کارشناس فروش را برای همیشه
از بین می‌برد. هر ریسک و فرصت «شاهد عددی» خودش را همراه دارد تا کاربر بتواند
راستی‌آزمایی کند.
"""
from __future__ import annotations

from typing import Any

from pipeline import fa

# وزن فوریت برای رتبه‌بندی اقدام‌ها
URGENCY = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.2}

SEVERITY_FA = {"critical": "بحرانی", "high": "زیاد", "medium": "متوسط", "low": "کم"}

OWNER_FA = {
    "collections": "واحد وصول مطالبات",
    "sales": "واحد فروش",
    "pricing": "کمیته قیمت‌گذاری",
    "quality": "کنترل کیفیت",
    "rnd": "تحقیق‌وتوسعه",
    "planning": "برنامه‌ریزی تولید",
    "credit": "کمیته اعتباری",
}


def money(x: float | None) -> str:
    """قالب‌بندی مبلغ به فارسی. واحد پول در داده مشخص نشده است."""
    if x is None:
        return "—"
    s = "-" if x < 0 else ""
    x = abs(float(x))
    if x >= 1e9:
        return f"{s}{x / 1e9:,.2f} میلیارد"
    if x >= 1e6:
        return f"{s}{x / 1e6:,.1f} میلیون"
    if x >= 1e3:
        return f"{s}{x / 1e3:,.0f} هزار"
    return f"{s}{x:,.0f}"


def qty(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f} کیلوگرم"


def pct(x: float | None, digits: int = 1) -> str:
    return "—" if x is None else f"{x:,.{digits}f}٪"


# ═══════════════════════════════════════════════════════════════════ ریسک‌ها
def find_risks(p: dict) -> list[dict]:
    c, m, r = p["commercial"], p["margin"], p["receivables"]
    cp, e, w, ws = p["complaints"], p["engagement"], p["market"], p["wallet_share"]
    R: list[dict] = []

    def add(code, title, severity, evidence, action, owner, at_stake=0.0):
        R.append({"code": code, "title": title, "severity": severity,
                  "severity_fa": SEVERITY_FA[severity], "evidence": evidence,
                  "action": action, "owner": OWNER_FA[owner], "value_at_stake": round(at_stake)})

    # ---- ریسک اعتباری و وصول
    if r["uncollected_overdue"] > 0 and m["gross_profit"] > 0 and \
            r["uncollected_overdue"] > m["gross_profit"]:
        add("overdue_exceeds_gp", "مطالبات معوق از کل سود ناخالص بیشتر است", "critical",
            f"{money(r['uncollected_overdue'])} معوق در برابر {money(m['gross_profit'])} "
            f"سود ناخالص انباشته؛ مشارکت خالص {money(r['net_contribution'])}",
            "توقف فروش اعتباری تا تسویه بخشی از معوق؛ تعیین برنامه پرداخت مکتوب",
            "collections", r["uncollected_overdue"])

    if (r["oldest_overdue_days"] or 0) > 365:
        add("overdue_aged", "معوق کهنه (بیش از یک سال)", "high",
            f"قدیمی‌ترین بدهی سررسیدشده {r['oldest_overdue_days']} روز عمر دارد "
            f"و {r['invoices_uncollected']} فاکتور هیچ وصولی نداشته است",
            "ارجاع به کمیته اعتباری برای تعیین تکلیف: تسویه، تقسیط یا ذخیره‌گیری مطالبات مشکوک",
            "credit", r["uncollected_overdue"])

    if r["bounced_cheques"] > 0:
        add("bounced_cheques", f"{r['bounced_cheques']} چک برگشتی", "high",
            f"{r['bounced_cheques']} مورد چک برگشتی ثبت شده و نرخ وصول "
            f"{pct(r['collection_rate_pct'])} است",
            "بازنگری شرایط پرداخت به نقدی یا پیش‌پرداخت؛ درخواست تضمین جدید",
            "credit", r["uncollected_overdue"])

    if (r["credit_limit_utilisation_pct"] or 0) > 100:
        add("over_credit_limit", "عبور از سقف اعتبار", "high",
            f"معوق {money(r['uncollected_overdue'])} معادل "
            f"{pct(r['credit_limit_utilisation_pct'], 0)} سقف اعتبار "
            f"({money(p['identity']['credit_limit'])}) است",
            "بازتعریف سقف اعتبار یا مسدودسازی سفارش جدید تا کاهش مانده",
            "credit", r["uncollected_overdue"] - p["identity"]["credit_limit"])

    if (r["collection_rate_pct"] or 100) < 80:
        add("low_collection_rate", "نرخ وصول پایین", "medium",
            f"تنها {pct(r['collection_rate_pct'])} از {money(r['invoiced'])} فاکتورشده "
            f"وصول شده؛ میانگین تأخیر {r['avg_days_late']} روز",
            "تشدید پیگیری وصول و پیوند تخفیف آتی به تسویه", "collections",
            r["uncollected_overdue"])

    # ---- ریسک ریزش مشتری
    d = c["days_since_last_purchase"]
    if d is not None and d > 180:
        sev = "high" if (c["revenue_rank"] or 999) <= 150 else "medium"
        add("dormant", f"مشتری راکد ({d} روز بی‌خرید)", sev,
            f"آخرین خرید {d} روز پیش؛ رتبه درآمدی {c['revenue_rank']} از ۶۴۴ با "
            f"{money(c['revenue_nominal'])} فروش تاریخی",
            "تماس بازگشت با آفر هدفمند؛ ریشه‌یابی علت قطع خرید در گفت‌وگوی حضوری",
            "sales", c["revenue_nominal"] / max(c["active_months"], 1) * 6)

    vt = c["volume_trend_pct"]
    if vt is not None and vt < -50:
        add("volume_collapse", f"ریزش حجم خرید ({pct(vt, 0)} در ۶ ماه)", "high",
            f"حجم شش ماه اخیر {pct(abs(vt), 0)} کمتر از شش ماه پیش از آن است "
            f"(کل حجم تاریخی {qty(c['volume'])})",
            "بازدید حضوری کارشناس فروش و بررسی جایگزینی توسط رقیب", "sales",
            c["revenue_nominal"] / max(c["active_months"], 1) * 6)

    # ---- پیوند کیفیت با رفتار خرید (پرسش صریح صورت‌مسئله)
    imp = cp.get("purchase_impact")
    if imp and imp["change_pct"] is not None and imp["change_pct"] < -25 and imp["window_complete"]:
        add("quality_linked_decline", "کاهش خرید پس از ثبت شکایت", "critical",
            f"در {imp['window_days']} روز پیش از نخستین شکایت "
            f"({imp['first_complaint']}) حجم خرید {qty(imp['volume_before'])} بود و در "
            f"{imp['window_days']} روز پس از آن {qty(imp['volume_after'])} "
            f"({pct(imp['change_pct'], 0)}). شکایت‌های ثبت‌شده: "
            + "، ".join(f"{fa(k)}×{v}" for k, v in cp["by_severity"].items()),
            "بازبینی فنی مشترک با مشتری روی همان کد کالا و ارائه گزارش اقدام اصلاحی",
            "quality", c["revenue_nominal"] / max(c["active_months"], 1) * 6)

    if cp["open"] > 0 and cp["critical_or_high"] > 0:
        add("open_severe_complaint", f"{cp['open']} شکایت باز (شامل شدت زیاد/بحرانی)", "high",
            f"{cp['total']} شکایت ثبت‌شده که {cp['open']} مورد باز است؛ "
            f"{cp['critical_or_high']} مورد شدت زیاد یا بحرانی دارد و "
            f"{cp['linked_order_lines']} خط فروش را درگیر کرده است",
            "تعیین مسئول رسیدگی و مهلت پاسخ؛ اطلاع نتیجه به مشتری", "quality", 0.0)

    # ---- ریسک سودآوری
    gm = m["gross_margin_pct"]
    if gm is not None and gm < 3:
        add("thin_margin", f"حاشیه سود بسیار نازک ({pct(gm)})", "high",
            f"حاشیه سود ناخالص {pct(gm)} در برابر میانگین سبد ۱۰.۱٪؛ "
            f"{m['negative_margin_lines']} خط زیان‌ده "
            f"({pct(m['negative_margin_line_pct'], 0)}) با "
            f"{money(abs(m['gross_profit_destroyed']))} زیان انباشته. "
            f"مبنای بهای تمام‌شده: {pct(m['realized_cost_share_pct'], 0)} تحقق‌یافته",
            "بازنگری قیمت یا حذف کدهای زیان‌ده از سبد این مشتری", "pricing",
            abs(m["gross_profit_destroyed"]))
    elif m["negative_margin_line_pct"] > 30:
        add("many_negative_lines", "سهم بالای خطوط زیان‌ده", "medium",
            f"{pct(m['negative_margin_line_pct'], 0)} خطوط فروش این مشتری زیان‌ده‌اند "
            f"({m['negative_margin_lines']} خط، {money(abs(m['gross_profit_destroyed']))} زیان)",
            "شناسایی کدهای کالای زیان‌ده و اصلاح قیمت پایه", "pricing",
            abs(m["gross_profit_destroyed"]))

    # ---- ریسک ارتباطی و رقابتی
    di = e["days_since_last_interaction"]
    if di is not None and di > 180 and d is not None and d < 90:
        add("uncontacted_active", "مشتری فعال بدون تماس ثبت‌شده", "medium",
            f"آخرین خرید {d} روز پیش اما آخرین تعامل ثبت‌شده {di} روز پیش بوده است",
            "برنامه تماس دوره‌ای؛ ثبت گزارش تعامل در CRM", "sales", 0.0)
    elif e["interactions"] == 0 and c["revenue_nominal"] > 0:
        add("no_crm_history", "هیچ تعاملی در CRM ثبت نشده", "medium",
            f"با {money(c['revenue_nominal'])} فروش، هیچ گزارش تعاملی ثبت نشده است؛ "
            "دانش این مشتری فقط در ذهن کارشناس است",
            "ثبت تاریخچه شناخته‌شده مشتری در CRM توسط کارشناس مسئول", "sales", 0.0)

    if ws["main_competitors"] and (ws["avg_share_pct"] or 100) < 25:
        top_comp = max(ws["main_competitors"], key=ws["main_competitors"].get)
        add("competitor_dominant", "سهم غالب رقیب در سبد خرید مشتری", "medium",
            f"میانگین سهم ما {pct(ws['avg_share_pct'])} از خرید برآوردی "
            f"{qty(ws['estimated_total_purchase'])} ماهانه؛ رقیب اصلی گزارش‌شده "
            f"{fa(top_comp)} در {ws['main_competitors'][top_comp]} ماه",
            "تحلیل شکاف قیمت و تحویل در برابر رقیب اصلی", "sales", 0.0)

    if "price_pressure" in w["signal_types"]:
        add("market_price_pressure", "سیگنال فشار قیمتی بازار", "low",
            f"{w['signal_types']['price_pressure']} گزارش فشار قیمتی مرتبط با این مشتری "
            f"(آخرین سیگنال {w['latest_signal']})",
            "پیش‌دستی در بازنگری قیمت پیش از درخواست مشتری", "pricing", 0.0)

    fam = c["product_family_mix"]
    if fam and max(fam.values()) > 90 and c["revenue_nominal"] > 0:
        top_fam = max(fam, key=fam.get)
        add("single_family_dependency", "وابستگی به یک گروه کالا", "low",
            f"{pct(fam[top_fam], 0)} فروش این مشتری تنها از {top_fam} است",
            "معرفی گروه کالای مکمل برای کاهش ریسک تک‌محصولی", "sales", 0.0)

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(R, key=lambda x: (order[x["severity"]], -x["value_at_stake"]))


# ══════════════════════════════════════════════════════════════════ فرصت‌ها
def find_opportunities(p: dict) -> list[dict]:
    c, m, r = p["commercial"], p["margin"], p["receivables"]
    cp, e, dv, of, ws = p["complaints"], p["engagement"], p["development"], p["offers"], p["wallet_share"]
    O: list[dict] = []

    def add(code, title, potential, evidence, action, owner, value=0.0):
        O.append({"code": code, "title": title, "potential": potential,
                  "potential_fa": SEVERITY_FA[potential], "evidence": evidence,
                  "action": action, "owner": OWNER_FA[owner], "value": round(value)})

    # ---- شکاف سهم از سبد: بزرگ‌ترین فرصت قابل اندازه‌گیری
    share, seg_avg = ws["avg_share_pct"], ws["segment_avg_share_pct"]
    if share is not None and seg_avg is not None and share < seg_avg and ws["estimated_total_purchase"]:
        gap = seg_avg - share
        monthly_kg = ws["estimated_total_purchase"] * gap / 100
        price = (c["revenue_nominal"] / c["volume"]) if c["volume"] else 0
        add("wallet_share_gap", "شکاف سهم از سبد خرید مشتری", "high",
            f"سهم ما {pct(share)} در برابر میانگین {pct(seg_avg)} بخش "
            f"{p['identity']['segment']}؛ خرید برآوردی مشتری "
            f"{qty(ws['estimated_total_purchase'])} در ماه. رسیدن به میانگین بخش "
            f"معادل {qty(monthly_kg)} در ماه است",
            "تدوین پیشنهاد حجمی پله‌ای برای جذب سهم بیشتر", "sales",
            monthly_kg * price * 12)

    # ---- نمونهٔ تأییدشده که به فروش تبدیل نشده
    if dv["approved"] > 0:
        items = [i for i in dv["items"] if i["status"] == "sample_approved"]
        detail = items[0]["requirement"][:110] if items else ""
        add("approved_sample_idle", f"{dv['approved']} نمونه تأییدشده، آمادهٔ تبدیل به سفارش", "high",
            f"{dv['approved']} درخواست توسعه به مرحلهٔ تأیید نمونه رسیده است. "
            f"نمونهٔ اخیر: «{detail}»",
            "پیگیری تبدیل نمونهٔ تأییدشده به سفارش انبوه و قیمت‌گذاری آن", "rnd",
            c["revenue_nominal"] / max(c["active_months"], 1) * 3)

    if dv["pending"] > 0:
        types = "، ".join(fa(k) for k in list(dv["by_type"])[:3])
        add("pending_dev_request", f"{dv['pending']} درخواست توسعه در انتظار پاسخ", "medium",
            f"{dv['requests']} درخواست توسعه ثبت شده که {dv['pending']} مورد بی‌پاسخ است "
            f"({types}). این‌ها نیاز اعلام‌شدهٔ خود مشتری‌اند",
            "تعیین مهلت پاسخ فنی و اطلاع نتیجه به مشتری", "rnd", 0.0)

    if of["pending"] > 0:
        add("pending_offers", f"{of['pending']} آفر بی‌پاسخ یا در مذاکره", "medium",
            f"از {of['total']} آفر، {of['pending']} مورد نتیجه‌ای ثبت نکرده و نرخ پذیرش "
            f"تاریخی {pct(of['acceptance_rate_pct'])} است",
            "پیگیری تلفنی آفرهای باز پیش از انقضا", "sales", 0.0)

    if (of["acceptance_rate_pct"] or 0) >= 50 and of["total"] >= 5:
        add("offer_responsive", "مشتری به آفر پاسخ‌ده است", "medium",
            f"{of['accepted']} پذیرش از {of['total']} آفر "
            f"(نرخ {pct(of['acceptance_rate_pct'])}) با میانگین تخفیف "
            f"{pct(of['avg_discount_pct'], 2)}",
            "استفاده از آفر هدفمند برای رشد حجم؛ ابزار مؤثری برای این مشتری است",
            "sales", 0.0)

    if c["cross_sell_families"]:
        fams = "، ".join(c["cross_sell_families"][:3])
        add("cross_sell", "گروه کالای فروخته‌نشده در این مشتری", "medium",
            f"هم‌بخشی‌های این مشتری (بخش {p['identity']['segment']}) از {fams} خرید "
            f"می‌کنند اما این مشتری هیچ خریدی در این گروه‌ها نداشته است",
            "ارسال نمونه و معرفی فنی گروه‌های کالای پیشنهادی", "sales", 0.0)

    vt = c["volume_trend_pct"]
    if vt is not None and vt > 25:
        add("growing", f"رشد حجم خرید ({pct(vt, 0)} در ۶ ماه)", "high",
            f"حجم شش ماه اخیر {pct(vt, 0)} بیشتر از دورهٔ پیش است "
            f"و حاشیه سود {pct(m['gross_margin_pct'])} است",
            "تثبیت رشد با قرارداد حجمی؛ بررسی ظرفیت تولید برای پاسخ به رشد",
            "planning", c["revenue_nominal"] / max(c["active_months"], 1) * 6)

    gm = m["gross_margin_pct"]
    if gm is not None and 0 < gm < 8 and c["revenue_nominal"] > 5e7:
        upside = c["revenue_nominal"] * (8 - gm) / 100
        add("repricing_upside", "ظرفیت اصلاح قیمت در مشتری بزرگ", "high",
            f"با {money(c['revenue_nominal'])} فروش، حاشیه {pct(gm)} است. "
            f"رسیدن به ۸٪ معادل {money(upside)} سود بیشتر روی همین حجم است",
            "مذاکره اصلاح قیمت با تکیه بر تحلیل بهای تمام‌شده", "pricing", upside)

    if cp["total"] > 0 and cp["open"] == 0 and (vt or 0) > -10:
        add("recovered_trust", "شکایت‌های رسیدگی‌شده و خرید پایدار", "low",
            f"{cp['total']} شکایت ثبت و همه بسته شده؛ میانگین زمان رسیدگی "
            f"{cp['avg_resolution_days']} روز و حجم خرید افت معناداری نداشته است",
            "استفاده از این سابقه به‌عنوان مرجع کیفیت در مذاکرات آتی", "sales", 0.0)

    d = c["days_since_last_purchase"]
    if d is not None and d > 180 and (c["revenue_rank"] or 999) <= 100:
        add("win_back", "بازیابی مشتری بزرگ راکد", "high",
            f"رتبه درآمدی {c['revenue_rank']} از ۶۴۴ با {money(c['revenue_nominal'])} "
            f"فروش تاریخی در {c['active_months']} ماه فعال، اما {d} روز است خریدی نداشته",
            "کمپین بازگشت با آفر و بازدید مدیر فروش", "sales",
            c["revenue_nominal"] / max(c["active_months"], 1) * 12)

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(O, key=lambda x: (order[x["potential"]], -x["value"]))


# ═══════════════════════════════════════════════════ اقدام بعدی پیشنهادی
def next_best_actions(p: dict, risks: list[dict], opps: list[dict], top: int = 4) -> list[dict]:
    """اقدام‌ها را بر اساس «مبلغ در معرض خطر × فوریت» رتبه می‌دهد."""
    pool = []
    for x in risks:
        pool.append({"kind": "risk", "kind_fa": "کاهش ریسک", "code": x["code"],
                     "title": x["title"], "action": x["action"], "owner": x["owner"],
                     "evidence": x["evidence"], "weight": URGENCY[x["severity"]],
                     "value": x["value_at_stake"]})
    for x in opps:
        pool.append({"kind": "opportunity", "kind_fa": "بهره‌گیری از فرصت", "code": x["code"],
                     "title": x["title"], "action": x["action"], "owner": x["owner"],
                     "evidence": x["evidence"], "weight": URGENCY[x["potential"]] * 0.85,
                     "value": x["value"]})
    if not pool:
        return []
    mx = max((x["value"] for x in pool), default=0) or 1
    for x in pool:
        # نرمال‌سازی مبلغ + پایهٔ فوریت، تا اقدام‌های بی‌مبلغ ولی فوری هم دیده شوند
        x["score"] = round(x["weight"] * (0.45 + 0.55 * x["value"] / mx), 4)
    pool.sort(key=lambda x: -x["score"])
    out, seen = [], set()
    for x in pool:
        if x["owner"] in seen and len(out) >= 2:
            continue          # تنوع مالک اقدام، تا همه‌ی پیشنهادها به یک واحد نیفتد
        seen.add(x["owner"])
        out.append({**x, "rank": len(out) + 1})
        if len(out) == top:
            break
    return out


def summarise(p: dict, risks: list[dict], opps: list[dict], nba: list[dict]) -> str:
    """خلاصه وضعیت مشتری — قطعی، بدون مدل زبانی. مبنای اعتماد و پشتیبان دمو."""
    c, m, r = p["commercial"], p["margin"], p["receivables"]
    seg = p["identity"]["segment"]
    L = []
    if not p["coverage"]["sales"]:
        return (f"مشتری {p['customer_id']} در بخش {seg} ثبت شده اما در بازهٔ داده هیچ "
                f"خریدی نداشته است. پروفایل تجاری قابل ساخت نیست.")

    L.append(
        f"مشتری {p['customer_id']} از بخش {seg}، رتبه {c['revenue_rank']} از ۶۴۴ با "
        f"{money(c['revenue_nominal'])} فروش ({qty(c['volume'])}) در "
        f"{c['active_months']} ماه فعال."
    )
    trend = ""
    if c["volume_trend_pct"] is not None:
        word = "رشد" if c["volume_trend_pct"] > 0 else "افت"
        trend = f" حجم شش ماه اخیر {word} {pct(abs(c['volume_trend_pct']), 0)} داشته است."
    L.append(
        f"سود ناخالص {money(m['gross_profit'])} با حاشیه {pct(m['gross_margin_pct'])} "
        f"(میانگین سبد ۱۰.۱٪).{trend}"
    )
    if r["uncollected_overdue"] > 0:
        L.append(
            f"مطالبات معوق {money(r['uncollected_overdue'])} است"
            + (f" و قدیمی‌ترین بدهی {r['oldest_overdue_days']} روز عمر دارد"
               if r["oldest_overdue_days"] else "")
            + f"؛ مشارکت خالص (سود ناخالص منهای معوق) {money(r['net_contribution'])}."
        )
    else:
        L.append(f"مطالبات معوقی ندارد و نرخ وصول {pct(r['collection_rate_pct'])} است.")

    if p["complaints"]["total"]:
        imp = p["complaints"].get("purchase_impact")
        extra = ""
        if imp and imp["change_pct"] is not None and imp["window_complete"] \
                and abs(imp["change_pct"]) >= 25:
            word = "افزایش" if imp["change_pct"] > 0 else "کاهش"
            extra = (f" حجم خرید در {imp['window_days']} روز پس از نخستین شکایت "
                     f"{pct(abs(imp['change_pct']), 0)} {word} یافته است.")
        L.append(f"{p['complaints']['total']} شکایت ثبت شده "
                 f"({p['complaints']['open']} باز).{extra}")

    if risks:
        L.append("مهم‌ترین ریسک: " + risks[0]["title"] + f" (شدت {risks[0]['severity_fa']}).")
    if opps:
        L.append("مهم‌ترین فرصت: " + opps[0]["title"] + ".")
    if nba:
        L.append("اقدام بعدی پیشنهادی: " + nba[0]["action"] + f" — مسئول: {nba[0]['owner']}.")
    return " ".join(L)


def enrich(p: dict) -> dict:
    """پروفایل + ریسک + فرصت + اقدام + خلاصه."""
    risks = find_risks(p)
    opps = find_opportunities(p)
    nba = next_best_actions(p, risks, opps)
    return {**p, "risks": risks, "opportunities": opps, "next_best_actions": nba,
            "summary": summarise(p, risks, opps, nba),
            "risk_score": round(sum(URGENCY[x["severity"]] for x in risks), 2),
            "opportunity_score": round(sum(URGENCY[x["potential"]] for x in opps), 2)}


def enrich_all(profiles: dict[str, dict]) -> dict[str, dict]:
    return {cid: enrich(p) for cid, p in profiles.items()}


if __name__ == "__main__":
    import pipeline
    D, P, _ = pipeline.load_all()
    E = enrich_all(P)
    top = max(E.values(), key=lambda p: p["commercial"]["revenue_nominal"])
    print("═" * 78)
    print(top["summary"])
    print("═" * 78)
    print("\n▸ ریسک‌ها")
    for x in top["risks"]:
        print(f"  [{x['severity_fa']}] {x['title']}\n      شاهد: {x['evidence']}\n"
              f"      اقدام: {x['action']} ({x['owner']})")
    print("\n▸ فرصت‌ها")
    for x in top["opportunities"]:
        print(f"  [{x['potential_fa']}] {x['title']}\n      شاهد: {x['evidence']}\n"
              f"      اقدام: {x['action']} ({x['owner']})")
    print("\n▸ اقدام بعدی پیشنهادی")
    for x in top["next_best_actions"]:
        print(f"  {x['rank']}. ({x['kind_fa']}, امتیاز {x['score']}) {x['action']}"
              f"\n      مسئول: {x['owner']} | مبلغ در معرض: {money(x['value'])}")
    n_r = sum(len(p["risks"]) for p in E.values())
    n_o = sum(len(p["opportunities"]) for p in E.values())
    print(f"\nدر کل سبد: {n_r} ریسک و {n_o} فرصت شناسایی شد.")
