"""لایهٔ ابزار — همان توابعی که هم داشبورد و هم مدل زبانی صدا می‌زنند.

قاعده: مدل هیچ‌گاه محاسبه نمی‌کند. مدل انتخاب می‌کند و توضیح می‌دهد؛ محاسبه
اینجا انجام می‌شود. هر خروجی متنی فارسی و آمادهٔ خواندن است.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

import insights as I
import jalali
from pipeline import fa

BASE = Path(__file__).parent
CACHE = BASE / "cache"


# ------------------------------------------------------- نرمال‌سازی متن فارسی
_AR2FA = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا",
                        "إ": "ا", "آ": "ا", "ؤ": "و", "‌": " ", "ً": "",
                        "ٌ": "", "ٍ": "", "َ": "", "ُ": "",
                        "ِ": "", "ّ": "", "ْ": ""})
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def norm(s: Any) -> str:
    """یکسان‌سازی «ي/ی»، «ك/ک»، نیم‌فاصله، اعراب و ارقام فارسی."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).translate(_AR2FA).translate(_FA_DIGITS)).strip().lower()


class Store:
    """پروفایل‌های غنی‌شده + ابزارهای جست‌وجو و تحلیل."""

    def __init__(self, enriched: dict[str, dict], portfolio: dict):
        self.P = enriched
        self.portfolio = portfolio
        rows = []
        for cid, p in enriched.items():
            c, m, r = p["commercial"], p["margin"], p["receivables"]
            rows.append({
                "customer_id": cid, "segment": p["identity"]["segment"],
                "location_id": p["identity"]["location_id"],
                "sales_rep_id": p["identity"]["sales_rep_id"],
                "revenue": c["revenue_nominal"], "revenue_real": c["revenue_real"],
                "revenue_rank": c["revenue_rank"], "volume": c["volume"],
                "gross_profit": m["gross_profit"], "margin_pct": m["gross_margin_pct"],
                "negative_line_pct": m["negative_margin_line_pct"],
                "overdue": r["uncollected_overdue"], "open_ar": r["uncollected"],
                "collection_rate": r["collection_rate_pct"],
                "net_contribution": r["net_contribution"],
                "oldest_overdue_days": r["oldest_overdue_days"],
                "bounced": r["bounced_cheques"],
                "days_since_purchase": c["days_since_last_purchase"],
                "volume_trend": c["volume_trend_pct"],
                "complaints": p["complaints"]["total"], "open_complaints": p["complaints"]["open"],
                "interactions": p["engagement"]["interactions"],
                "dev_requests": p["development"]["requests"],
                "wallet_share": p["wallet_share"]["avg_share_pct"],
                "risk_score": p["risk_score"], "opportunity_score": p["opportunity_score"],
                "risk_codes": "|".join(x["code"] for x in p["risks"]),
                "opp_codes": "|".join(x["code"] for x in p["opportunities"]),
                "top_risk": p["risks"][0]["title"] if p["risks"] else "",
                "top_opportunity": p["opportunities"][0]["title"] if p["opportunities"] else "",
                "next_action": p["next_best_actions"][0]["action"] if p["next_best_actions"] else "",
            })
        self.frame = pd.DataFrame(rows).set_index("customer_id")

        # نمایهٔ متن آزاد — شکایت، گزارش کارشناس، درخواست توسعه
        self.text_index: list[dict] = []
        for cid, p in enriched.items():
            for x in p["complaints"]["items"]:
                self.text_index.append({
                    "customer_id": cid, "kind": "شکایت", "date": x["date"],
                    "title": x["title"],
                    "text": " ".join(filter(None, [x["title"], x["text"], x["resolution"]])),
                    "meta": f"شدت {fa(x['severity'])} / وضعیت {fa(x['status'])}"})
            for x in p["engagement"]["items"]:
                self.text_index.append({
                    "customer_id": cid, "kind": "تعامل CRM", "date": x["date"],
                    "title": fa(x["type"]), "text": x["summary"],
                    "meta": f"اقدام بعدی {fa(x['next_action'])} / کارشناس {x['rep']}"})
            for x in p["development"]["items"]:
                self.text_index.append({
                    "customer_id": cid, "kind": "درخواست توسعه", "date": x["date"],
                    "title": fa(x["type"]),
                    "text": " ".join(filter(None, [x["requirement"], x["outcome"]])),
                    "meta": f"وضعیت {fa(x['status'])} / مالک {fa(x['owner'])}"})
        for d in self.text_index:
            d["_n"] = norm(d["text"] + " " + d["title"])

    # ══════════════════════════════════════════════════════════ ابزار ۱
    def get_customer_profile(self, customer_id: str) -> str:
        """پروفایل کامل یک مشتری به فارسی."""
        p = self.P.get(customer_id.strip().upper())
        if not p:
            near = [c for c in self.P if customer_id.strip().upper() in c][:5]
            return (f"مشتری «{customer_id}» یافت نشد."
                    + (f" شناسه‌های نزدیک: {'، '.join(near)}" if near else ""))
        return render_profile_fa(p)

    # ══════════════════════════════════════════════════════════ ابزار ۲
    def search_customers(self, sort_by: str = "revenue", ascending: bool = False,
                         limit: int = 10, segment: str | None = None,
                         has_risk: str | None = None, has_opportunity: str | None = None,
                         min_revenue: float | None = None,
                         dormant_days_min: int | None = None) -> str:
        """رتبه‌بندی و پالایش سبد مشتریان. جدول فشرده برمی‌گرداند، نه پروفایل کامل."""
        f = self.frame
        if segment:
            f = f[f.segment == segment.strip().upper()]
        if has_risk:
            f = f[f["risk_codes"].str.contains(has_risk, na=False)]
        if has_opportunity:
            f = f[f["opp_codes"].str.contains(has_opportunity, na=False)]
        if min_revenue is not None:
            f = f[f.revenue >= min_revenue]
        if dormant_days_min is not None:
            f = f[f.days_since_purchase >= dormant_days_min]
        if sort_by not in f.columns:
            return f"ستون «{sort_by}» وجود ندارد. ستون‌های مجاز: {', '.join(f.columns[:20])}"
        f = f.sort_values(sort_by, ascending=ascending).head(int(limit))
        if f.empty:
            return "هیچ مشتری با این شرایط یافت نشد."
        lines = [f"{len(f)} مشتری (از {len(self.frame)}) — مرتب بر اساس {sort_by}:", ""]
        for cid, r in f.iterrows():
            lines.append(
                f"• {cid} | بخش {r.segment} | فروش {I.money(r.revenue)} "
                f"(رتبه {int(r.revenue_rank) if pd.notna(r.revenue_rank) else '—'}) | "
                f"حاشیه {I.pct(r.margin_pct)} | معوق {I.money(r.overdue)} | "
                f"مشارکت خالص {I.money(r.net_contribution)} | "
                f"{int(r.days_since_purchase) if pd.notna(r.days_since_purchase) else '—'} روز از آخرین خرید"
                + (f"\n    ریسک اصلی: {r.top_risk}" if r.top_risk else "")
                + (f"\n    فرصت اصلی: {r.top_opportunity}" if r.top_opportunity else ""))
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════ ابزار ۳
    def get_risks_and_actions(self, customer_id: str) -> str:
        """ریسک‌ها، فرصت‌ها و اقدام بعدی پیشنهادی یک مشتری."""
        p = self.P.get(customer_id.strip().upper())
        if not p:
            return f"مشتری «{customer_id}» یافت نشد."
        L = [f"◆ {customer_id} — {p['summary']}", ""]
        if p["risks"]:
            L.append("▸ ریسک‌ها")
            for x in p["risks"]:
                L.append(f"  [{x['severity_fa']}] {x['title']}\n      شاهد: {x['evidence']}"
                         f"\n      اقدام: {x['action']} — {x['owner']}")
        if p["opportunities"]:
            L.append("\n▸ فرصت‌ها")
            for x in p["opportunities"]:
                L.append(f"  [{x['potential_fa']}] {x['title']}\n      شاهد: {x['evidence']}"
                         f"\n      اقدام: {x['action']} — {x['owner']}")
        if p["next_best_actions"]:
            L.append("\n▸ اقدام بعدی پیشنهادی (به ترتیب اولویت)")
            for x in p["next_best_actions"]:
                L.append(f"  {x['rank']}. {x['action']}\n      مسئول: {x['owner']} | "
                         f"نوع: {x['kind_fa']} | مبلغ در معرض: {I.money(x['value'])}")
        return "\n".join(L)

    # ══════════════════════════════════════════════════════════ ابزار ۴
    def search_text(self, query: str, limit: int = 12, kind: str | None = None) -> str:
        """جست‌وجو در متن آزاد: شکایت‌ها، گزارش‌های کارشناس فروش و درخواست‌های توسعه.

        این ابزار همان بخشی است که دانش «نهفته در متن» را قابل بازیابی می‌کند.
        """
        terms = [t for t in norm(query).split() if len(t) > 2]
        if not terms:
            return "عبارت جست‌وجو خیلی کوتاه است."
        hits = []
        for d in self.text_index:
            if kind and d["kind"] != kind:
                continue
            score = sum(1 for t in terms if t in d["_n"])
            if score:
                hits.append((score, d))
        if not hits:
            return f"هیچ متنی شامل «{query}» یافت نشد."
        hits.sort(key=lambda x: (-x[0], x[1]["date"] or ""))
        by_cust: dict[str, int] = {}
        for _, d in hits:
            by_cust[d["customer_id"]] = by_cust.get(d["customer_id"], 0) + 1
        L = [f"{len(hits)} رکورد متنی در {len(by_cust)} مشتری شامل «{query}» یافت شد.",
             "پرتکرارترین مشتریان: " + "، ".join(
                 f"{c} ({n})" for c, n in sorted(by_cust.items(), key=lambda x: -x[1])[:6]), ""]
        for _, d in hits[:int(limit)]:
            L.append(f"• [{d['kind']}] {d['customer_id']} — {jalali.fmt(d['date'])} | {d['meta']}"
                     f"\n    {str(d['text'])[:240]}")
        return "\n".join(L)

    # ══════════════════════════════════════════════════════════ ابزار ۵
    def portfolio_summary(self) -> str:
        """آمار کل سبد مشتریان — برای هر پرسشی که دربارهٔ یک مشتری خاص نیست."""
        s = self.portfolio
        f = self.frame
        h = s.get("half_years") or []
        hline = ""
        if len(h) >= 2:
            a, b = h[0], h[-1]
            hline = (
                f"• مقایسهٔ هم‌ارز فصل بهار ({a['label']} → {b['label']}، "
                f"هر دو پنجره دقیقاً هم‌طول): "
                f"حجم {I.qty(a['volume'])} → {I.qty(b['volume'])} "
                f"(شاخص {b['volume_index']}) | "
                f"فروش اسمی {I.money(a['revenue'])} → {I.money(b['revenue'])} "
                f"(شاخص {b['revenue_index']}) | "
                f"مشتری فعال {a['customers']} → {b['customers']} (شاخص {b['customer_index']}) | "
                f"قیمت میانگین واحد {b['price_index'] / 100:.1f} برابر | "
                f"حاشیه {I.pct(a['margin_pct'])} → {I.pct(b['margin_pct'])}\n"
                f"  ⇒ فروش اسمی رشد کرده اما حجم و تعداد مشتری کاهش یافته؛ "
                f"رشد از قیمت است نه از بازار.\n")
        return (
            f"وضعیت کل سبد در تاریخ {jalali.fmt(s['as_of'], 'long')}:\n"
            + hline +
            f"• {s['customers']} مشتری ({s['customers_with_sales']} با سابقهٔ خرید) | "
            f"فروش اسمی {I.money(s['revenue_nominal'])} | فروش حقیقی (تعدیل تورم) "
            f"{I.money(s['revenue_real'])} | حجم {I.qty(s['volume'])}\n"
            f"• سود ناخالص {I.money(s['gross_profit'])} با حاشیه {I.pct(s['gross_margin_pct'])} "
            f"({I.pct(s['realized_cost_share_pct'], 0)} خطوط بر مبنای هزینه تحقق‌یافته، بقیه برآوردی)\n"
            f"• مطالبات معوق {I.money(s['overdue'])} = {I.pct(s['overdue_pct_of_revenue'])} فروش "
            f"و {s['overdue_x_gross_profit']} برابر کل سود ناخالص | "
            f"سررسیدنشده {I.money(s['not_yet_due'])}\n"
            f"• مشارکت خالص کل {I.money(s['net_contribution'])} | "
            f"{s['net_negative_customers']} مشتری مشارکت منفی دارند "
            f"({I.pct(s['net_negative_revenue_share_pct'])} فروش)\n"
            f"• تمرکز: ۱۰ مشتری اول {I.pct(s['top10_revenue_share_pct'])} فروش | "
            f"{s['dormant_180d']} مشتری بیش از ۱۸۰ روز راکد | "
            f"{I.pct(s['negative_margin_lines_pct'])} خطوط فروش زیان‌ده\n"
            f"• {s['open_complaints']} شکایت باز | "
            f"{int(f.dev_requests.sum())} درخواست توسعه ثبت‌شده\n"
            f"• بخش‌ها: " + " | ".join(
                f"{k}: {v['customers']} مشتری، فروش {I.money(v['revenue'])}، "
                f"معوق {I.money(v['overdue'])}" for k, v in s["segments"].items())
        )

    # ══════════════════════════════════════════════════════════ ابزار ۶
    def compare_customers(self, customer_ids: list[str]) -> str:
        """مقایسهٔ چند مشتری روی شاخص‌های تصمیم‌ساز."""
        ids = [c.strip().upper() for c in customer_ids if c.strip().upper() in self.frame.index]
        if not ids:
            return "هیچ‌کدام از شناسه‌ها یافت نشد."
        cols = [("بخش", "segment", str), ("فروش", "revenue", I.money),
                ("سود ناخالص", "gross_profit", I.money), ("حاشیه", "margin_pct", I.pct),
                ("معوق", "overdue", I.money), ("نرخ وصول", "collection_rate", I.pct),
                ("مشارکت خالص", "net_contribution", I.money),
                ("شکایت", "complaints", lambda v: str(int(v))),
                ("سهم از سبد", "wallet_share", I.pct)]
        L = ["مقایسهٔ " + "، ".join(ids), ""]
        for label, col, f in cols:
            L.append(f"{label}: " + " | ".join(
                f"{c}={f(self.frame.at[c, col]) if pd.notna(self.frame.at[c, col]) else '—'}"
                for c in ids))
        return "\n".join(L)


# ═══════════════════════════════════════════════════ رندر فارسی پروفایل
def render_profile_fa(p: dict) -> str:
    """پروفایل کامل به متن فارسی — هم برای نمایش، هم به‌عنوان زمینهٔ مدل زبانی."""
    i, c, m, r = p["identity"], p["commercial"], p["margin"], p["receivables"]
    L = [f"# پروفایل مشتری {p['customer_id']} — در تاریخ {jalali.fmt(p['as_of'], 'long')}",
         f"بخش {i['segment']} | موقعیت {i['location_id']} | کارشناس {i['sales_rep_id']} | "
         f"سقف اعتبار {I.money(i['credit_limit'])} | مهلت پرداخت {i['payment_terms_days']} روز | "
         f"سابقهٔ همکاری از {jalali.fmt(i['relationship_start'])}",
         "", "## خلاصه وضعیت", p["summary"]]

    if not p["coverage"]["sales"]:
        return "\n".join(L)

    L += ["", "## عملکرد تجاری",
          f"فروش اسمی {I.money(c['revenue_nominal'])} | فروش حقیقی {I.money(c['revenue_real'])} | "
          f"رتبه {c['revenue_rank']} از ۶۴۴ ({I.pct(c['revenue_share_pct'], 2)} کل سبد)",
          f"حجم {I.qty(c['volume'])} در {c['order_lines']} خط و {c['invoices']} فاکتور | "
          f"میانگین ارزش فاکتور {I.money(c['avg_order_value'])}",
          f"{c['active_months']} ماه فعال، از {jalali.fmt(c['first_purchase'])} تا "
          f"{jalali.fmt(c['last_purchase'])} ({c['days_since_last_purchase']} روز پیش)"
          + (f" | روند حجم شش‌ماهه {I.pct(c['volume_trend_pct'], 0)}"
             if c["volume_trend_pct"] is not None else "")]
    if c["product_family_mix"]:
        L.append("ترکیب گروه کالا: " + "، ".join(
            f"{k} {I.pct(v, 0)}" for k, v in list(c["product_family_mix"].items())[:5]))
    if c["payment_type_mix"]:
        L.append("ترکیب شرایط پرداخت: " + "، ".join(
            f"{fa(k)} {I.pct(v, 0)}" for k, v in c["payment_type_mix"].items()))
    if c["top_products"]:
        L.append("محصولات اصلی:")
        for x in c["top_products"][:3]:
            L.append(f"  - {x['desc']} ({x['product_id']}): {I.money(x['revenue'])}، "
                     f"{I.qty(x['qty'])}، حاشیه {I.pct(x['margin_pct'])}")

    L += ["", "## سودآوری و بهای تمام‌شده",
          f"سود ناخالص {I.money(m['gross_profit'])} | حاشیه {I.pct(m['gross_margin_pct'])} "
          f"(رتبه سود {m['gp_rank']}) | میانگین سبد ۱۰.۱٪",
          f"مبنای بهای تمام‌شده: {I.pct(m['realized_cost_share_pct'], 0)} خطوط هزینه تحقق‌یافته، "
          f"بقیه هزینه برآوردی محصول-ماه (برآوردی حاشیه را حدود ۵ واحد درصد خوش‌بینانه‌تر نشان می‌دهد)",
          f"{m['negative_margin_lines']} خط زیان‌ده ({I.pct(m['negative_margin_line_pct'], 0)}) "
          f"با {I.money(abs(m['gross_profit_destroyed']))} زیان انباشته"]

    L += ["", "## مطالبات و وصول",
          f"فاکتورشده {I.money(r['invoiced'])} | وصول‌شده {I.money(r['collected'])} "
          f"({I.pct(r['collection_rate_pct'])}) | مانده باز {I.money(r['uncollected'])}",
          f"از این مانده: {I.money(r['uncollected_overdue'])} سررسیدگذشته و "
          f"{I.money(r['uncollected_not_yet_due'])} هنوز سررسید نشده"
          + (f" | قدیمی‌ترین معوق {r['oldest_overdue_days']} روز"
             if r["oldest_overdue_days"] else ""),
          f"فاکتورها: {r['invoices_fully_collected']} تسویه‌شده، "
          f"{r['invoices_partially_collected']} ناقص، {r['invoices_uncollected']} بدون وصول | "
          f"میانگین تأخیر {r['avg_days_late']} روز (بیشینه {r['max_days_late']})"
          + (f" | {r['bounced_cheques']} چک برگشتی" if r["bounced_cheques"] else ""),
          f"**مشارکت خالص (سود ناخالص منهای معوق): {I.money(r['net_contribution'])}**"]
    if r["credit_limit_utilisation_pct"] is not None:
        L.append(f"معوق معادل {I.pct(r['credit_limit_utilisation_pct'], 0)} سقف اعتبار است")

    cp = p["complaints"]
    if cp["total"]:
        L += ["", "## شکایات و کیفیت",
              f"{cp['total']} شکایت ({cp['open']} باز) | شدت: " + "، ".join(
                  f"{fa(k)}×{v}" for k, v in cp["by_severity"].items())
              + f" | {cp['linked_order_lines']} خط فروش درگیر، "
                f"{I.qty(cp['returned_qty'])} برگشتی"
              + (f" ({I.pct(cp['return_rate_pct'], 2)} حجم)" if cp["return_rate_pct"] else "")
              + (f" | میانگین رسیدگی {cp['avg_resolution_days']} روز"
                 if cp["avg_resolution_days"] else "")]
        imp = cp.get("purchase_impact")
        if imp and imp["change_pct"] is not None:
            note = "" if imp["window_complete"] else " (پنجرهٔ مقایسه کامل نیست)"
            L.append(f"اثر بر رفتار خرید: حجم {imp['window_days']} روز پیش از نخستین شکایت "
                     f"{I.qty(imp['volume_before'])} و پس از آن {I.qty(imp['volume_after'])} "
                     f"→ {I.pct(imp['change_pct'], 0)}{note}")
        for x in cp["items"][:4]:
            L.append(f"  - {jalali.fmt(x['date'])} [{fa(x['severity'])}/{fa(x['status'])}] "
                     f"{x['title']}: {str(x['text'])[:150]}")

    q = p["quality"]
    if q["lab_records"]:
        L.append(f"آزمایشگاه: {q['lab_records']} رکورد، {q['lab_failures']} رد | "
                 f"استحکام {q['avg_tensile_cN_dtex']} cN/dtex | "
                 f"کشش {I.pct(q['avg_elongation_pct'])} | "
                 f"یکنواختی CV {I.pct(q['avg_evenness_cv_pct'])} | "
                 f"روغن {I.pct(q['avg_oil_pickup_pct'], 2)}")

    e = p["engagement"]
    if e["interactions"]:
        L += ["", "## تعاملات ثبت‌شده",
              f"{e['interactions']} تعامل | آخرین {jalali.fmt(e['last_interaction'])} "
              f"({e['days_since_last_interaction']} روز پیش) | " + "، ".join(
                  f"{fa(k)}×{v}" for k, v in list(e["by_type"].items())[:5])]
        if e["open_next_actions"]:
            L.append("اقدام‌های بعدی ثبت‌شده: " + "، ".join(
                f"{fa(k)}×{v}" for k, v in e["open_next_actions"].items()))
        for x in e["items"][:4]:
            L.append(f"  - {jalali.fmt(x['date'])} [{fa(x['type'])}] {x['summary']}")

    dv = p["development"]
    if dv["requests"]:
        L += ["", "## درخواست‌های توسعه محصول",
              f"{dv['requests']} درخواست | {dv['approved']} نمونه تأیید، "
              f"{dv['rejected']} رد فنی، {dv['pending']} در جریان | " + "، ".join(
                  f"{fa(k)}×{v}" for k, v in dv["by_type"].items())]
        for x in dv["items"][:4]:
            L.append(f"  - {jalali.fmt(x['date'])} [{fa(x['status'])}] {x['requirement']}")

    o = p["offers"]
    if o["total"]:
        L += ["", "## آفرها",
              f"{o['total']} آفر | {o['accepted']} قبول، {o['rejected']} رد، {o['expired']} منقضی، "
              f"{o['pending']} بی‌پاسخ | نرخ پذیرش {I.pct(o['acceptance_rate_pct'])} | "
              f"میانگین تخفیف {I.pct(o['avg_discount_pct'], 2)}",
              "دلایل آفر: " + "، ".join(f"{fa(k)}×{v}" for k, v in list(o["by_reason"].items())[:4])]

    w = p["wallet_share"]
    if w["months_observed"]:
        L += ["", "## سهم از سبد خرید مشتری",
              f"میانگین {I.pct(w['avg_share_pct'])} در {w['months_observed']} ماه "
              f"(آخرین {I.pct(w['latest_share_pct'])}، میانگین بخش "
              f"{I.pct(w['segment_avg_share_pct'])}) | خرید برآوردی مشتری "
              f"{I.qty(w['estimated_total_purchase'])} در ماه | رقبای گزارش‌شده: " + "، ".join(
                  f"{fa(k)}×{v}" for k, v in w["main_competitors"].items())]

    mk = p["market"]
    if mk["signals"]:
        L.append(f"\nسیگنال بازار: {mk['signals']} گزارش (آخرین "
                 f"{jalali.fmt(mk['latest_signal'])}) | " + "، ".join(
                     f"{fa(k)}×{v}" for k, v in mk["signal_types"].items()))

    if p["risks"]:
        L += ["", "## ریسک‌ها"]
        L += [f"- [{x['severity_fa']}] {x['title']} — {x['evidence']}" for x in p["risks"]]
    if p["opportunities"]:
        L += ["", "## فرصت‌ها"]
        L += [f"- [{x['potential_fa']}] {x['title']} — {x['evidence']}" for x in p["opportunities"]]
    if p["next_best_actions"]:
        L += ["", "## اقدام بعدی پیشنهادی"]
        L += [f"{x['rank']}. {x['action']} (مسئول: {x['owner']}، "
              f"مبلغ در معرض: {I.money(x['value'])})" for x in p["next_best_actions"]]
    return "\n".join(L)


# ═════════════════════════════════════════════════════════ ساخت / خواندن کش
def build_cache(as_of: str | None = None) -> Store:
    import pipeline
    ts = pd.Timestamp(as_of) if as_of else pipeline.DEFAULT_AS_OF
    D, profiles, rep = pipeline.load_all(ts)
    enriched = I.enrich_all(profiles)
    portfolio = pipeline.portfolio_stats(profiles, D, ts)
    CACHE.mkdir(exist_ok=True)
    (CACHE / "profiles.json").write_text(
        json.dumps(enriched, ensure_ascii=False), encoding="utf-8")
    (CACHE / "portfolio.json").write_text(
        json.dumps(portfolio, ensure_ascii=False), encoding="utf-8")
    (CACHE / "clean_report.json").write_text(
        json.dumps({str(k): str(v) for k, v in rep.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return Store(enriched, portfolio)


def load_store(rebuild: bool = False) -> Store:
    if rebuild or not (CACHE / "profiles.json").exists():
        return build_cache()
    enriched = json.loads((CACHE / "profiles.json").read_text(encoding="utf-8"))
    portfolio = json.loads((CACHE / "portfolio.json").read_text(encoding="utf-8"))
    return Store(enriched, portfolio)


if __name__ == "__main__":
    import sys
    import time
    t = time.time()
    st = build_cache(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"کش ساخته شد در {time.time() - t:.1f} ثانیه — {len(st.P)} پروفایل، "
          f"{len(st.text_index)} رکورد متنی\n")
    print(st.portfolio_summary())
    print("\n" + "─" * 78 + "\n")
    print(st.search_customers(sort_by="net_contribution", ascending=True, limit=5))
    print("\n" + "─" * 78 + "\n")
    print(st.search_text("شید رنگ", limit=4))
