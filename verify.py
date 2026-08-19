"""آزمون‌های صحت — پیش از ارائه اجرا کنید: python verify.py

سه دستهٔ خطا را می‌گیرد: تجمیع‌هایی که با منبع نمی‌خوانند، نشتی زمانی
(اطلاعاتی که در تاریخ برش در دسترس نبوده)، و گم‌شدن بی‌صدای مشتری.
"""
from __future__ import annotations

import sys

import pandas as pd

import insights as I
import pipeline as P


def run() -> int:
    rows = []

    def ck(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"آزمون": name, "نتیجه": "قبول" if ok else "رد", "جزئیات": detail})

    print("بارگذاری و پاک‌سازی…")
    D, rep = P.clean(P.load_raw())
    as_of = P.DEFAULT_AS_OF
    prof = P.build_profiles(D, as_of)
    P.add_complaint_impact(D, prof, as_of)
    E = I.enrich_all(prof)
    V = P.as_of_view(D, as_of)
    stats = P.portfolio_stats(prof, D, as_of)

    # ── ۱. یکپارچگی ارجاعی و کلیدها
    rel = pd.read_excel(P.META_XLSX, sheet_name="روابط")
    # شناسهٔ خط فروش باید در «فروش ∪ ردیف‌های ردیابی» حل شود: دام ۱ آن ۵۲ ردیف را
    # از فروش جدا کرده، ولی شیت‌های هزینه و آزمایشگاه و پل شکایت هنوز به آن‌ها
    # ارجاع می‌دهند و این ارجاع درست است.
    all_lines = set(D["sales"].Sales_Line_ID) | set(D["traceability_lines"].Sales_Line_ID)
    orphans, trace_refs = 0, 0
    for _, r in rel.iterrows():
        a, b = P.SHEETS[r["From_Sheet"]], P.SHEETS[r["To_Sheet"]]
        ac = P.COLUMN_RENAMES.get(r["From_Column"], r["From_Column"])
        bc = P.COLUMN_RENAMES.get(r["To_Column"], r["To_Column"])
        if ac not in D[a].columns or bc not in D[b].columns:
            continue
        left = set(D[a][ac].dropna())
        right = all_lines if bc == "Sales_Line_ID" else set(D[b][bc].dropna())
        miss = left - right
        orphans += len(miss)
        if bc == "Sales_Line_ID":
            trace_refs += len({x for x in left if str(x).startswith("SL-CMP")})
    ck("هیچ کلید یتیمی در روابط اعلام‌شدهٔ متادیتا نیست", orphans == 0,
       f"{orphans} کلید یتیم (شامل {trace_refs} ارجاع مجاز به ردیف‌های ردیابی)")
    ck("ردیف‌های ردیابی از فروش جدا شده‌اند اما دور ریخته نشده‌اند",
       len(D["traceability_lines"]) == 52,
       f"{len(D['traceability_lines'])} ردیف در traceability_lines نگه داشته شده")

    # ── ۲. تجمیع‌ها با منبع می‌خوانند
    S = V["sales"]
    for label, src, got, tol in [
        ("فروش", S.line_amount.sum(),
         sum(p["commercial"]["revenue_nominal"] for p in prof.values()), 1e-6),
        ("حجم", S.qty.sum(), sum(p["commercial"]["volume"] for p in prof.values()), 1e-4),
        ("سود ناخالص", S.gross_profit.sum(),
         sum(p["margin"]["gross_profit"] for p in prof.values()), 1e-5),
        ("وصول", V["collections"].collected_amount.sum(),
         sum(p["receivables"]["collected"] for p in prof.values()), 1e-5),
    ]:
        ck(f"{label} با شیت منبع می‌خواند", abs(src - got) / abs(src) < tol,
           f"منبع {src:,.0f} در برابر پروفایل‌ها {got:,.0f}")

    # ── ۳. دام‌های داده
    ck("هیچ ردیف ردیابی شکایتی در فروش نمانده",
       not S.Sales_Line_ID.str.startswith("SL-CMP").any())
    ck("بازهٔ فروش پیش از ردیف‌های تزریقی تمام می‌شود",
       S.date.max() < P.ERP_WINDOW_END, f"آخرین تاریخ فروش {S.date.max().date()}")
    ck("CRM به یک ردیف برای هر تعامل کاهش یافته",
       not V["crm"].Interaction_ID.duplicated().any())
    ck("پوشش بهای تمام‌شده کامل است", S.unit_cost.notna().all(),
       f"{S.unit_cost.notna().mean():.1%}")
    ck("ستون‌های درصدی آزمایشگاه به مقیاس درصد آمده‌اند",
       V["lab"].Elongation_Pct.max() > 1.0, f"بیشینهٔ کشش {V['lab'].Elongation_Pct.max():.2f}")
    ck("فیلد وضعیت نشتی تغییر نام یافته و قرنطینه است",
       "source_status_LEAKY" in D["customers"].columns
       and "Customer_Status" not in D["customers"].columns)

    # ── ۴. تفکیک مطالبات
    ck("معوق + سررسیدنشده = مانده باز، برای هر مشتری",
       all(abs(p["receivables"]["uncollected"]
               - (p["receivables"]["uncollected_overdue"]
                  + p["receivables"]["uncollected_not_yet_due"])) < 2 for p in prof.values()))
    ck("مشارکت خالص = سود ناخالص منهای معوق",
       all(abs(p["receivables"]["net_contribution"]
               - (p["margin"]["gross_profit"] - p["receivables"]["uncollected_overdue"])) < 1
           for p in prof.values()))
    ck("هیچ مانده باز منفی وجود ندارد",
       all(p["receivables"]["uncollected"] >= 0 for p in prof.values()))

    # ── ۵. نشتی زمانی — پروفایل در تاریخ قدیمی‌تر
    early = pd.Timestamp("2021-06-30")
    print(f"ساخت پروفایل در تاریخ {early.date()} برای آزمون نشتی…")
    Pe = P.build_profiles(D, early)
    latest = max((p["commercial"]["last_purchase"] for p in Pe.values()
                  if p["commercial"]["last_purchase"]), default=None)
    ck("برش زمانی هیچ فروش آینده‌ای را لو نمی‌دهد",
       latest is not None and latest <= str(early.date()),
       f"آخرین خرید در نمای {early.date()}: {latest}")
    ck("نمای قدیمی‌تر فروش کمتری دارد",
       sum(p["commercial"]["revenue_nominal"] for p in Pe.values())
       < sum(p["commercial"]["revenue_nominal"] for p in prof.values()))
    Ve = P.as_of_view(D, early)
    ck("شکایت‌های بازِ آن تاریخ، رسیدگی‌شده نشان داده نمی‌شوند",
       Ve["complaints"][Ve["complaints"].outcome_censored].Resolved_At.isna().all())
    ck("آفرهای بی‌نتیجهٔ آن تاریخ، «بی‌پاسخ» علامت خورده‌اند",
       (Ve["offers"][Ve["offers"].outcome_censored].Result == "pending").all())

    # ── ۶. پوشش و بینش
    ck("هر مشتری یک پروفایل دارد", len(prof) == len(D["customers"]),
       f"{len(prof)} پروفایل / {len(D['customers'])} مشتری")
    ck("هر مشتری خلاصه وضعیت فارسی دارد",
       all(len(p["summary"]) > 40 for p in E.values()))
    ck("هر ریسک شاهد عددی و مالک دارد",
       all(x["evidence"] and x["owner"] and x["action"]
           for p in E.values() for x in p["risks"]))
    ck("هر فرصت شاهد عددی و مالک دارد",
       all(x["evidence"] and x["owner"] and x["action"]
           for p in E.values() for x in p["opportunities"]))
    ck("هر مشتری با ریسک یا فرصت، اقدام بعدی دارد",
       all(p["next_best_actions"] for p in E.values()
           if p["risks"] or p["opportunities"]))
    ck("ماه‌های ناقص مرزی شناسایی شده‌اند", len(stats["partial_months"]) == 2,
       "، ".join(stats["partial_months"]))
    ck("پنجره‌های مقایسهٔ بهار هم‌ارزند", len(stats["half_years"]) >= 2,
       "، ".join(h["label"] for h in stats["half_years"]))

    df = pd.DataFrame(rows)
    print()
    print(df.to_string(index=False))
    passed = int((df["نتیجه"] == "قبول").sum())
    print(f"\n{passed} از {len(df)} آزمون قبول شد.")
    if passed != len(df):
        print("\nآزمون‌های رد‌شده:")
        print(df[df["نتیجه"] == "رد"].to_string(index=False))
        return 1
    print("همهٔ آزمون‌ها قبول — خروجی قابل ارائه است.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
