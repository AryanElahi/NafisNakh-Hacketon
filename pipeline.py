"""لایه یکپارچه‌سازی داده و ساخت پروفایل مشتری  —  MVP ۰۱ و ۰۲ و ۰۶

این ماژول ۱۶ شیت پراکنده را به یک پروفایل واحد برای هر مشتری تبدیل می‌کند.

قاعده‌ی طراحی: هر پروفایل «در تاریخ مشخص» ساخته می‌شود (as-of). هیچ داده‌ای
پیش از تاریخ Available_At خود قابل استفاده نیست، پس دستیار هرگز اطلاعاتی را
نمی‌بیند که در آن لحظه در دسترس سازمان نبوده است.

چهار دام داده که در این لایه اصلاح می‌شوند:
  ۱. ۵۲ ردیف با شناسه SL-CMP-* فروش نیستند؛ رکورد ردیابی شکایت‌اند و تاریخ
     ۱۴۰۴–۱۴۰۵ دارند. تنها ردیف‌هایی هستند که Hembaft_Lot_Key دارند.
  ۲. درآمد اسمی = تورم. شاخص قیمت ۱۰۰ → ۱۱۷۴ ولی شاخص حجم ۱۰۰ → ۴۹.
  ۳. Customer_Status نشتی است: هر ۳۷۱ مشتری راکد بیش از ۱۸۰ روز «غیرفعال»
     علامت خورده‌اند و هیچ مشتری فعالی چنین نیست. یعنی همان «رکود» است.
  ۴. مبنای بهای تمام‌شده نتیجه را عوض می‌کند: هزینه تحقق‌یافته (۳۲٪ خطوط)
     حاشیه ۶.۹٪ می‌دهد، هزینه برآوردی ۱۱.۶٪.
"""
from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

BASE = Path(__file__).parent
DATA_XLSX = BASE / "DATASET.xlsx"
META_XLSX = BASE / "METADATA.xlsx"

ERP_WINDOW_END = pd.Timestamp("2022-07-01")
DEFAULT_AS_OF = pd.Timestamp("2022-06-30")
DORMANCY_DAYS = 180

# ---------------------------------------------------------------- نگاشت نام‌ها
SHEETS = {
    "مشتریان": "customers", "محصولات": "products", "فاکتورها": "invoices",
    "فروش": "sales", "اجزای_هزینه_تحقق": "realized_cost", "وصول": "collections",
    "شکایات": "complaints", "اتصال_شکایت": "complaint_links", "تعاملات_CRM": "crm",
    "درخواست_توسعه": "dev_requests", "کیفیت_لات": "lab", "همبافت_لات": "hembaft_lots",
    "آفرها": "offers", "سهم_سبد": "wallet_share", "سیگنال_بازار": "market_signals",
    "برآورد_هزینه_ماهانه": "estimated_cost",
}

COLUMN_RENAMES = {
    "شماره فاکتور": "invoice_no", "تاریخ": "date", "ماه": "month_label",
    "سال": "year_label", "ردیف فاکتور": "invoice_line_no", "نوع پرداخت": "payment_type",
    "مقدار": "qty", "قیمت فی فروش": "unit_price", "مبلغ کل": "line_amount",
    "دسته بندی براقیت": "luster_class", "گروه کالا": "product_family",
    "گروه رنگ": "color_class", "زیرگروه کالا": "denier_subgroup",
    "شرح کالا": "product_desc", "هزینه کل به ازای واحد": "realized_unit_cost",
    "هزینه کل برآوردی به ازای واحد": "estimated_unit_cost",
    "مقدار برگشتی": "returned_qty", "مبلغ برگشتی": "returned_amount",
    "تاریخ فاکتور": "invoice_date", "تاریخ سررسید": "due_date",
    "تاریخ رویداد وصول": "collection_date", "مبلغ وصول": "collected_amount",
    "روز تأخیر": "days_late", "چک برگشتی": "bounced_cheque",
}

# مقادیر دسته‌ای به انگلیسی نرمال می‌شوند تا کلید پایدار داشته باشیم؛
# برچسب فارسی برای نمایش در LABELS_FA پایین نگه داشته می‌شود.
VALUE_MAP = {
    "فعال": "active", "غیرفعال": "inactive", "بله": "yes", "خیر": "no",
    "کم": "low", "متوسط": "medium", "زیاد": "high", "بحرانی": "critical",
    "بسته‌شده": "closed", "درحال بررسی": "under_review", "پذیرفته‌شده": "accepted",
    "ردشده": "rejected", "نیازمند بررسی": "needs_review", "رسیدگی‌شده": "handled",
    "باز": "open", "قبول": "accepted", "رد": "rejected", "منقضی‌شده": "expired",
    "درحال مذاکره": "negotiating", "مدت‌دار": "term", "قیمتی": "price", "حجمی": "volume",
    "درحال توسعه": "in_development", "نمونه تأیید": "sample_approved",
    "فنی رد": "technically_rejected", "ثبت اولیه": "initial", "اصلاح‌شده": "amended",
    "رقیب X": "Competitor_X", "رقیب Y": "Competitor_Y", "رقیب Z": "Competitor_Z",
    "تأمین‌کننده محلی": "Local_Supplier", "مشتری اظهار": "customer_stated",
    "فروش کارشناس": "sales_rep", "برآورد بازدید": "visit_estimate",
    "افزایش": "increase", "ثابت": "stable", "کاهش": "decrease",
    "افزایش تقاضا": "rising_demand", "تقاضای ثابت": "stable_demand",
    "کاهش تقاضا": "falling_demand", "فشار قیمتی": "price_pressure",
    "تحویل سریع": "fast_delivery", "ظرفیت محدود": "limited_capacity",
    "قیمت رقابتی": "competitive_price", "وصول متمرکز": "collection_focus",
    "برنامه خرید": "purchase_plan", "خدمات فنی": "technical_service",
    "قیمت و تخفیف": "price_and_discount", "نمونه محصول": "product_sample",
    "وصول مطالبات": "receivables_chase", "پیگیری سفارش": "order_followup",
    "کیفیت محصول": "product_quality", "ارسال نمونه": "send_sample",
    "بازدید فنی": "technical_visit", "بدون اقدام": "no_action",
    "جلسه قیمت": "price_meeting", "پیگیری تلفنی": "phone_followup",
    "بسته‌بندی اختصاصی": "custom_packaging", "بهبود استحکام": "strength_improvement",
    "بهبود شید رنگ": "colour_shade_improvement",
    "تغییر تعداد فیلامنت": "filament_count_change", "تغییر دنیر": "denier_change",
    "کاهش پرز": "hairiness_reduction", "برنامه‌ریزی تولید": "production_planning",
    "تحقیق‌وتوسعه": "r_and_d", "کنترل کیفیت": "quality_control",
    "آزمون محصول": "product_trial", "افزایش حجم سفارش": "order_volume_growth",
    "افزایش سهم از سبد": "wallet_share_growth", "تسویه سریع": "fast_settlement",
    "حفظ مشتری کلیدی": "key_account_retention", "رقابت قیمتی": "price_competition",
    "معرفی محصول جدید": "new_product_intro",
}

# برچسب فارسی برای نمایش (عکس نگاشت بالا، به‌علاوه چند مورد محاسبه‌شده)
LABELS_FA = {v: k for k, v in VALUE_MAP.items()}
LABELS_FA.update({
    "pending": "بی‌پاسخ", "cash_or_prepaid": "نقدی/پیش‌پرداخت", "short_term": "کوتاه‌مدت",
    "long_term": "بلندمدت", "payment_generalized": "سایر شرایط پرداخت",
    "realized": "تحقق‌یافته", "estimated": "برآوردی",
})


def fa(v: Any) -> str:
    """برچسب فارسی یک مقدار دسته‌ای."""
    return LABELS_FA.get(v, str(v))


DATE_COLS = {
    "date", "invoice_date", "due_date", "collection_date", "Available_At",
    "Created_At", "Resolved_At", "Resolution_Available_At", "Event_Time",
    "Updated_At", "Decision_At", "Decision_Available_At", "Offer_Date",
    "Production_Date", "Measured_At", "Cost_Close_Date", "Relationship_Start_Date",
    "Report_Date", "First_Observed_Date", "Purchase_Date", "Link_Available_At",
    "Month_Key",
}


def _strip_zwnj(v):
    """نیم‌فاصله (U+200C) جست‌وجوی سادهٔ دیکشنری را می‌شکند."""
    return v.replace("‌", "") if isinstance(v, str) else v


VALUE_MAP_N = {_strip_zwnj(k): v for k, v in VALUE_MAP.items()}


# ------------------------------------------------------------------ بارگذاری
def load_raw(path: Path = DATA_XLSX) -> dict[str, pd.DataFrame]:
    raw = pd.read_excel(path, sheet_name=None)
    out: dict[str, pd.DataFrame] = {}
    for fa_name, df in raw.items():
        key = SHEETS.get(fa_name, fa_name)
        df = df.rename(columns=COLUMN_RENAMES).copy()
        for c in df.columns:
            if c in DATE_COLS:
                df[c] = pd.to_datetime(df[c], errors="coerce")
            # توجه: در pandas 3 ستون متنی dtype='str' دارد نه 'object'
            elif pd.api.types.is_string_dtype(df[c]) or pd.api.types.is_object_dtype(df[c]):
                if df[c].nunique(dropna=True) <= 25:
                    df[c] = df[c].map(lambda v: VALUE_MAP_N.get(_strip_zwnj(v), v))
        out[key] = df
    return out


# --------------------------------------------------------------------- پاک‌سازی
def clean(D: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    D = {k: v.copy() for k, v in D.items()}
    rep: dict[str, Any] = {}

    # دام ۱ — جداسازی ردیف‌های ردیابی شکایت از فروش واقعی
    s = D["sales"]
    s["is_traceability"] = s["Sales_Line_ID"].str.startswith("SL-CMP")
    trace, s = s[s.is_traceability].copy(), s[~s.is_traceability].copy()
    rep["ردیف‌های ردیابی جدا شده"] = len(trace)
    rep["بازه فروش واقعی"] = (str(s.date.min().date()), str(s.date.max().date()))
    assert s.date.max() < ERP_WINDOW_END
    D["sales"], D["traceability_lines"] = s, trace

    # قاعده ۵ — آخرین نسخه هر تعامل CRM
    crm = D["crm"].sort_values(["Interaction_ID", "Record_Version"])
    rep["ردیف CRM قبل/بعد از حذف نسخه‌های قدیمی"] = (len(crm), crm.Interaction_ID.nunique())
    crm = crm.groupby("Interaction_ID", as_index=False).tail(1)
    crm["was_amended"] = crm["Record_Version"] > 1
    D["crm"] = crm

    # قاعده ۶ — بهای تمام‌شده: تحقق‌یافته اولویت دارد، برآوردی جانشین
    est = D["estimated_cost"].copy()
    est["Month_Key"] = est["Month_Key"].dt.strftime("%Y-%m")
    s = D["sales"]
    s["month_key"] = s["date"].dt.strftime("%Y-%m")
    s = (s.merge(D["realized_cost"][["Sales_Line_ID", "realized_unit_cost", "returned_qty",
                                     "returned_amount", "Cost_Close_Date"]],
                 on="Sales_Line_ID", how="left")
          .merge(est[["Product_ID", "Month_Key", "estimated_unit_cost"]],
                 left_on=["Product_ID", "month_key"], right_on=["Product_ID", "Month_Key"],
                 how="left"))
    s["unit_cost"] = s["realized_unit_cost"].fillna(s["estimated_unit_cost"])
    s["cost_basis"] = np.where(s["realized_unit_cost"].notna(), "realized", "estimated")
    s["gross_profit"] = (s["unit_price"] - s["unit_cost"]) * s["qty"]
    rep["پوشش بهای تمام‌شده"] = float(s.unit_cost.notna().mean())
    rep["سهم هزینه تحقق‌یافته"] = float((s.cost_basis == "realized").mean())

    # دام ۲ — شاخص قیمت و درآمد حقیقی
    idx = (s.groupby("month_key").apply(lambda g: np.average(g.unit_price, weights=g.qty),
                                        include_groups=False))
    idx = idx / idx.loc["2020-01"] * 100
    s["price_index"] = s["month_key"].map(idx)
    s["line_amount_real"] = s["line_amount"] / (s["price_index"] / 100)
    rep["شاخص قیمت (اول → آخر)"] = (round(float(idx.iloc[0]), 1), round(float(idx.iloc[-1]), 1))
    D["sales"] = s
    D["_price_index"] = idx.rename("price_index").to_frame()

    # دام ۴ — ستون‌های *_Pct در آزمایشگاه کسری‌اند نه درصد
    lab = D["lab"]
    for c in ["Elongation_Pct", "Evenness_CV_Pct", "Oil_Pickup_Pct"]:
        assert lab[c].max() < 1.0
        lab[c] = lab[c] * 100.0

    # دام ۳ — قرنطینه پرچم نشتی
    D["customers"] = D["customers"].rename(columns={"Customer_Status": "source_status_LEAKY"})
    return D, rep


# ------------------------------------------------------------ موتور «در تاریخ»
AVAIL_COL = {
    "invoices": "Available_At", "sales": "Available_At", "collections": "Available_At",
    "complaints": "Available_At", "complaint_links": "Link_Available_At",
    "crm": "Available_At", "dev_requests": "Available_At", "lab": "Available_At",
    "offers": "Available_At", "wallet_share": "Available_At",
    "market_signals": "Available_At", "hembaft_lots": "Available_At",
}
CENSOR_RULES = {
    "complaints": (["Resolved_At", "Resolution_Text"], "Resolution_Available_At",
                   {"Complaint_Status": "under_review"}),
    "offers": (["Decision_At", "Result"], "Decision_Available_At", {"Result": "pending"}),
    "dev_requests": (["Decision_At", "Outcome_Text", "Status"], "Decision_At",
                     {"Status": "under_review"}),
}


def as_of_view(D: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """برش زمانی: حذف ردیف‌های در دسترس‌نبوده، سپس سانسور نتایجِ آن‌زمان‌نامعلوم."""
    V = {}
    for key, df in D.items():
        if key.startswith("_"):
            V[key] = df
            continue
        col = AVAIL_COL.get(key)
        V[key] = df[df[col] <= as_of].copy() if col and col in df.columns else df.copy()

    for key, (outcome_cols, known_col, defaults) in CENSOR_RULES.items():
        df = V[key]
        if known_col not in df.columns:
            continue
        future = df[known_col].isna() | (df[known_col] > as_of)
        for c in outcome_cols:
            if c in df.columns:
                df.loc[future, c] = np.nan
        for c, val in defaults.items():
            if c in df.columns:
                df.loc[future, c] = val
        df["outcome_censored"] = future
        V[key] = df
    return V


# ------------------------------------------------------------------- سازنده‌ها
def _mix(s: pd.Series, top: int | None = None) -> dict:
    vc = s.value_counts()
    if top:
        vc = vc.head(top)
    return {str(k): int(v) for k, v in vc.items()}


def _share(df: pd.DataFrame, by: str, val: str) -> dict:
    t = df.groupby(by)[val].sum()
    tot = t.sum()
    return ({str(k): round(float(v / tot * 100), 1)
             for k, v in t.sort_values(ascending=False).items()} if tot else {})


def _d(x) -> str | None:
    return None if pd.isna(x) else str(pd.Timestamp(x).date())


def build_profiles(D: dict[str, pd.DataFrame], as_of: pd.Timestamp = DEFAULT_AS_OF) -> dict[str, dict]:
    """۶۴۴ پروفایل مشتری در تاریخ داده‌شده. خروجی dict خالص برای JSON/API."""
    V = as_of_view(D, as_of)
    S, C = V["sales"], V["customers"]
    prod = V["products"].set_index("Product_ID")
    tot_rev = S.line_amount.sum()

    # ---- تجاری
    com = S.groupby("Customer_ID").agg(
        first_purchase=("date", "min"), last_purchase=("date", "max"),
        active_months=("month_key", "nunique"), invoices=("invoice_no", "nunique"),
        order_lines=("Sales_Line_ID", "count"), volume=("qty", "sum"),
        revenue=("line_amount", "sum"), revenue_real=("line_amount_real", "sum"),
        gross_profit=("gross_profit", "sum"),
        realized_lines=("cost_basis", lambda x: (x == "realized").sum()),
        neg_lines=("gross_profit", lambda x: (x < 0).sum()),
        gp_destroyed=("gross_profit", lambda x: x[x < 0].sum()),
    )
    com["revenue_rank"] = com.revenue.rank(ascending=False, method="min").astype(int)
    com["gp_rank"] = com.gross_profit.rank(ascending=False, method="min").astype(int)

    six, twelve = as_of - pd.Timedelta(days=182), as_of - pd.Timedelta(days=365)
    v_recent = S[S.date > six].groupby("Customer_ID").qty.sum()
    v_prior = S[(S.date > twelve) & (S.date <= six)].groupby("Customer_ID").qty.sum()

    # سری زمانی ماهانه برای نمودار
    monthly = (S.groupby(["Customer_ID", "month_key"])
                .agg(volume=("qty", "sum"), revenue=("line_amount", "sum"),
                     gross_profit=("gross_profit", "sum")).reset_index())

    # ---- مطالبات (سررسید = تاریخ فاکتور + مهلت پرداخت مشتری)
    terms = C.set_index("Customer_ID").Payment_Terms_Days
    inv = S.groupby(["Customer_ID", "invoice_no"]).agg(
        invoiced=("line_amount", "sum"), invoice_date=("date", "min")).reset_index()
    got = V["collections"].groupby("invoice_no").collected_amount.sum().rename("collected")
    inv = inv.join(got, on="invoice_no").fillna({"collected": 0.0})
    inv["ratio"] = inv.collected / inv.invoiced
    inv["due_date"] = inv.invoice_date + pd.to_timedelta(
        inv.Customer_ID.map(terms).fillna(0), unit="D")
    inv["open_amount"] = (inv.invoiced - inv.collected).clip(lower=0)
    inv["is_overdue"] = inv.due_date <= as_of

    ar = inv.groupby("Customer_ID").agg(
        invoiced=("invoiced", "sum"), collected=("collected", "sum"),
        inv_full=("ratio", lambda x: (x >= 0.99).sum()),
        inv_part=("ratio", lambda x: ((x > 0) & (x < 0.99)).sum()),
        inv_none=("ratio", lambda x: (x == 0).sum()))
    od = inv[inv.is_overdue & (inv.open_amount > 0)].groupby("Customer_ID").agg(
        overdue=("open_amount", "sum"), oldest=("due_date", "min"))
    nyd = inv[~inv.is_overdue].groupby("Customer_ID").open_amount.sum()
    late = V["collections"].groupby("Customer_ID").agg(
        avg_late=("days_late", "mean"), max_late=("days_late", "max"),
        bounced=("bounced_cheque", lambda x: (x == "yes").sum()))

    # ---- کیفیت
    lab = V["lab"].merge(S[["Sales_Line_ID", "Customer_ID"]], on="Sales_Line_ID", how="inner")
    q = lab.groupby("Customer_ID").agg(
        n=("Quality_Record_ID", "count"), fails=("Lab_Result", lambda x: (x == "rejected").sum()),
        tensile=("Tensile_Strength_cN_dtex", "mean"), elong=("Elongation_Pct", "mean"),
        cv=("Evenness_CV_Pct", "mean"), oil=("Oil_Pickup_Pct", "mean"))

    # ---- شکایات
    cmp_df = V["complaints"]
    links = V["complaint_links"]
    links = links[links.Complaint_ID.isin(cmp_df.Complaint_ID)]
    lagg = links.groupby("Customer_ID").agg(lines=("Sales_Line_ID", "nunique"),
                                            returned=("returned_qty", "sum"))
    W = V["wallet_share"].copy()
    W["share"] = np.where(W.Estimated_Total_Purchase > 0,
                          W.Nafis_Purchase / W.Estimated_Total_Purchase * 100, np.nan)

    # میانگین سهم سبد در هر بخش، برای سنجش فرصت
    seg_share = (W.merge(C[["Customer_ID", "Customer_Segment"]], on="Customer_ID")
                  .groupby("Customer_Segment")["share"].mean().to_dict())
    # خانواده‌های محصول پرفروش هر بخش، برای فروش مکمل
    seg_fam = (S.merge(C[["Customer_ID", "Customer_Segment"]], on="Customer_ID")
                .groupby(["Customer_Segment", "product_family"]).line_amount.sum())

    profiles: dict[str, dict] = {}
    for _, r in C.iterrows():
        cid = r.Customer_ID
        has = cid in com.index
        c = com.loc[cid] if has else None
        a = ar.loc[cid] if cid in ar.index else None
        L = late.loc[cid] if cid in late.index else None
        Q = q.loc[cid] if cid in q.index else None
        overdue = round(float(od.overdue.get(cid, 0.0)), 0) if cid in od.index else 0.0
        oldest = od.oldest.get(cid) if cid in od.index else None
        gp = round(float(c.gross_profit), 0) if has else 0.0
        rev = float(c.revenue) if has else 0.0
        start = pd.to_datetime(r.Relationship_Start_Date, errors="coerce")
        g = S[S.Customer_ID == cid]
        cg = cmp_df[cmp_df.Customer_ID == cid]
        eg = V["crm"][V["crm"].Customer_ID == cid]
        dg = V["dev_requests"][V["dev_requests"].Customer_ID == cid]
        og = V["offers"][V["offers"].Customer_ID == cid]
        wg = W[W.Customer_ID == cid].sort_values("Month_Key")
        mg = V["market_signals"][V["market_signals"].Customer_ID == cid]
        Lk = lagg.loc[cid] if cid in lagg.index else None
        a6 = float(v_recent.get(cid, 0)); b6 = float(v_prior.get(cid, 0))
        cl = float(r.Credit_Limit)

        top_products = []
        if has:
            pp = g.groupby("Product_ID").agg(revenue=("line_amount", "sum"),
                                             qty=("qty", "sum"),
                                             gp=("gross_profit", "sum")).nlargest(5, "revenue")
            for pid, x in pp.iterrows():
                top_products.append({
                    "product_id": pid,
                    "desc": str(prod.product_desc.get(pid, pid)),
                    "family": str(prod.product_family.get(pid, "")),
                    "revenue": round(float(x.revenue)), "qty": round(float(x.qty), 1),
                    "gross_profit": round(float(x.gp)),
                    "margin_pct": round(float(x.gp / x.revenue * 100), 1) if x.revenue else None,
                })

        fam_mix = _share(g, "product_family", "line_amount") if has else {}
        seg_top = (seg_fam.loc[r.Customer_Segment].nlargest(4).index.tolist()
                   if r.Customer_Segment in seg_fam.index.get_level_values(0) else [])
        cross_sell = [f for f in seg_top if f not in fam_mix and "GENERALIZED" not in f]

        profiles[cid] = {
            "customer_id": cid,
            "as_of": str(as_of.date()),
            "identity": {
                "location_id": r.Location_ID, "segment": r.Customer_Segment,
                "sales_rep_id": r.Sales_Rep_ID, "relationship_start": _d(start),
                "tenure_days": int((as_of - start).days) if pd.notna(start) else None,
                "credit_limit": cl, "payment_terms_days": int(r.Payment_Terms_Days),
                "source_system": r.Source_System,
                "source_status_LEAKY": r.source_status_LEAKY,
            },
            "commercial": {
                "first_purchase": _d(c.first_purchase) if has else None,
                "last_purchase": _d(c.last_purchase) if has else None,
                "days_since_last_purchase": int((as_of - c.last_purchase).days) if has else None,
                "active_months": int(c.active_months) if has else 0,
                "invoices": int(c.invoices) if has else 0,
                "order_lines": int(c.order_lines) if has else 0,
                "volume": round(float(c.volume), 1) if has else 0.0,
                "revenue_nominal": round(rev), "revenue_real": round(float(c.revenue_real)) if has else 0,
                "avg_order_value": round(rev / int(c.invoices)) if has and c.invoices else 0,
                "revenue_rank": int(c.revenue_rank) if has else None,
                "revenue_share_pct": round(rev / tot_rev * 100, 3) if has else 0.0,
                "volume_trend_pct": round((a6 - b6) / b6 * 100, 1) if b6 > 0 else None,
                "top_products": top_products,
                "product_family_mix": fam_mix,
                "payment_type_mix": _share(g, "payment_type", "line_amount") if has else {},
                "cross_sell_families": cross_sell,
                "monthly": (monthly[monthly.Customer_ID == cid]
                            .assign(volume=lambda d: d.volume.round(1),
                                    revenue=lambda d: d.revenue.round(0),
                                    gross_profit=lambda d: d.gross_profit.round(0))
                            [["month_key", "volume", "revenue", "gross_profit"]]
                            .to_dict("records")),
            },
            "margin": {
                "gross_profit": gp,
                "gross_margin_pct": round(gp / rev * 100, 2) if rev else None,
                "gp_rank": int(c.gp_rank) if has else None,
                "realized_cost_share_pct": round(float(c.realized_lines / c.order_lines * 100), 1) if has else 0.0,
                "negative_margin_lines": int(c.neg_lines) if has else 0,
                "negative_margin_line_pct": round(float(c.neg_lines / c.order_lines * 100), 1) if has else 0.0,
                "gross_profit_destroyed": round(float(c.gp_destroyed), 0) if has else 0.0,
            },
            "receivables": {
                "invoiced": round(float(a.invoiced)) if a is not None else 0,
                "collected": round(float(a.collected)) if a is not None else 0,
                "uncollected": round(max(float(a.invoiced - a.collected), 0.0)) if a is not None else 0,
                "uncollected_overdue": overdue,
                "uncollected_not_yet_due": round(float(nyd.get(cid, 0.0))),
                "oldest_overdue_days": (int((as_of - oldest).days)
                                        if oldest is not None and pd.notna(oldest) else None),
                "collection_rate_pct": (round(float(a.collected / a.invoiced * 100), 1)
                                        if a is not None and a.invoiced else None),
                "invoices_fully_collected": int(a.inv_full) if a is not None else 0,
                "invoices_partially_collected": int(a.inv_part) if a is not None else 0,
                "invoices_uncollected": int(a.inv_none) if a is not None else 0,
                "avg_days_late": round(float(L.avg_late), 1) if L is not None else None,
                "max_days_late": float(L.max_late) if L is not None else None,
                "bounced_cheques": int(L.bounced) if L is not None else 0,
                "credit_limit_utilisation_pct": round(overdue / cl * 100, 1) if cl > 0 else None,
                "net_contribution": gp - overdue,
            },
            "quality": {
                "lab_records": int(Q.n) if Q is not None else 0,
                "lab_failures": int(Q.fails) if Q is not None else 0,
                "avg_tensile_cN_dtex": round(float(Q.tensile), 3) if Q is not None else None,
                "avg_elongation_pct": round(float(Q.elong), 2) if Q is not None else None,
                "avg_evenness_cv_pct": round(float(Q.cv), 2) if Q is not None else None,
                "avg_oil_pickup_pct": round(float(Q.oil), 3) if Q is not None else None,
            },
            "complaints": {
                "total": len(cg),
                "open": int((cg.Complaint_Status != "closed").sum()) if len(cg) else 0,
                "by_severity": _mix(cg.Severity) if len(cg) else {},
                "by_status": _mix(cg.Complaint_Status) if len(cg) else {},
                "critical_or_high": int(cg.Severity.isin(["critical", "high"]).sum()) if len(cg) else 0,
                "linked_order_lines": int(Lk.lines) if Lk is not None else 0,
                "returned_qty": round(float(Lk.returned), 1) if Lk is not None else 0.0,
                "return_rate_pct": (round(float(Lk.returned) / float(c.volume) * 100, 3)
                                    if Lk is not None and has and c.volume else None),
                "avg_resolution_days": (round(float((cg.Resolved_At - cg.Created_At).dt.days.mean()), 1)
                                        if len(cg) and (cg.Resolved_At - cg.Created_At).notna().any() else None),
                "last_complaint": _d(cg.Created_At.max()) if len(cg) else None,
                "items": [{"date": _d(x.Created_At), "severity": x.Severity,
                           "status": x.Complaint_Status, "title": x.Complaint_Title,
                           "text": x.Complaint_Text,
                           "resolution": None if pd.isna(x.Resolution_Text) else x.Resolution_Text}
                          for _, x in cg.nlargest(6, "Created_At").iterrows()],
            },
            "engagement": {
                "interactions": len(eg),
                "amended_records": int(eg.was_amended.sum()) if len(eg) else 0,
                "last_interaction": _d(eg.Event_Time.max()) if len(eg) else None,
                "days_since_last_interaction": (int((as_of - eg.Event_Time.max()).days)
                                                if len(eg) else None),
                "by_type": _mix(eg.Interaction_Type) if len(eg) else {},
                "open_next_actions": (_mix(eg[eg.Next_Action != "no_action"].Next_Action)
                                      if len(eg) else {}),
                "items": [{"date": _d(x.Event_Time), "type": x.Interaction_Type,
                           "next_action": x.Next_Action, "summary": x.Summary_Text,
                           "rep": x.Sales_Rep_ID}
                          for _, x in eg.nlargest(8, "Event_Time").iterrows()],
            },
            "development": {
                "requests": len(dg),
                "by_type": _mix(dg.Request_Type) if len(dg) else {},
                "by_status": _mix(dg.Status) if len(dg) else {},
                "approved": int((dg.Status == "sample_approved").sum()) if len(dg) else 0,
                "rejected": int((dg.Status == "technically_rejected").sum()) if len(dg) else 0,
                "pending": int(dg.Status.isin(["under_review", "in_development"]).sum()) if len(dg) else 0,
                "items": [{"date": _d(x.Created_At), "type": x.Request_Type, "status": x.Status,
                           "requirement": x.Requirement_Text, "owner": x.Owner_Unit,
                           "outcome": None if pd.isna(x.Outcome_Text) else x.Outcome_Text}
                          for _, x in dg.nlargest(6, "Created_At").iterrows()],
            },
            "offers": {
                "total": len(og),
                "accepted": int((og.Result == "accepted").sum()) if len(og) else 0,
                "rejected": int((og.Result == "rejected").sum()) if len(og) else 0,
                "expired": int((og.Result == "expired").sum()) if len(og) else 0,
                "pending": int(og.Result.isin(["pending", "negotiating"]).sum()) if len(og) else 0,
                "acceptance_rate_pct": (round(float((og[og.Result.isin(["accepted", "rejected", "expired"])].Result == "accepted").mean() * 100), 1)
                                        if len(og) and og.Result.isin(["accepted", "rejected", "expired"]).any() else None),
                "avg_discount_pct": round(float(og.Offer_Discount_Pct.mean() * 100), 2) if len(og) else None,
                "by_reason": _mix(og.Offer_Reason) if len(og) else {},
            },
            "wallet_share": {
                "months_observed": len(wg),
                "avg_share_pct": round(float(wg.share.mean()), 1) if len(wg) and wg.share.notna().any() else None,
                "latest_share_pct": (round(float(wg.share.iloc[-1]), 1)
                                     if len(wg) and pd.notna(wg.share.iloc[-1]) else None),
                "segment_avg_share_pct": round(float(seg_share.get(r.Customer_Segment, np.nan)), 1)
                                          if not pd.isna(seg_share.get(r.Customer_Segment, np.nan)) else None,
                "estimated_total_purchase": round(float(wg.Estimated_Total_Purchase.mean()), 1) if len(wg) else None,
                "main_competitors": _mix(wg.Main_Competitor) if len(wg) else {},
                "estimate_sources": _mix(wg.Estimate_Source) if len(wg) else {},
                "zero_purchase_months": int((wg.Nafis_Purchase == 0).sum()) if len(wg) else 0,
            },
            "market": {
                "signals": len(mg),
                "signal_types": _mix(mg.Customer_Signal) if len(mg) else {},
                "competitors_named": _mix(mg.Competitor) if len(mg) else {},
                "latest_signal": _d(mg.Report_Date.max()) if len(mg) else None,
            },
            "coverage": {
                "sales": has, "receivables": a is not None, "lab": Q is not None,
                "complaints": len(cg) > 0, "crm": len(eg) > 0, "dev_requests": len(dg) > 0,
                "offers": len(og) > 0, "wallet_share": len(wg) > 0, "market_signals": len(mg) > 0,
            },
        }
    return profiles


def add_complaint_impact(D: dict[str, pd.DataFrame], profiles: dict[str, dict],
                         as_of: pd.Timestamp = DEFAULT_AS_OF, window: int = 90) -> None:
    """ارتباط شکایت با رفتار خرید — پرسش صریح صورت‌مسئله.

    حجم خرید در پنجرهٔ ۹۰ روزهٔ پیش از نخستین شکایت را با ۹۰ روز پس از آن
    مقایسه می‌کند. این یک شاهد است نه اثبات علیت؛ ولی به کارشناس می‌گوید کجا
    باید دنبال رابطه بگردد.
    """
    V = as_of_view(D, as_of)
    S, C = V["sales"], V["complaints"]
    for cid, p in profiles.items():
        cg = C[C.Customer_ID == cid]
        if cg.empty:
            p["complaints"]["purchase_impact"] = None
            continue
        first = cg.Created_At.min()
        g = S[S.Customer_ID == cid]
        before = g[(g.date >= first - pd.Timedelta(days=window)) & (g.date < first)].qty.sum()
        after = g[(g.date >= first) & (g.date < first + pd.Timedelta(days=window))].qty.sum()
        # پنجرهٔ «بعد» باید کامل در داده موجود باشد، وگرنه مقایسه گمراه‌کننده است
        complete = (first + pd.Timedelta(days=window)) <= min(as_of, S.date.max())
        p["complaints"]["purchase_impact"] = {
            "first_complaint": _d(first),
            "window_days": window,
            "volume_before": round(float(before), 1),
            "volume_after": round(float(after), 1),
            "change_pct": round(float((after - before) / before * 100), 1) if before > 0 else None,
            "window_complete": bool(complete),
        }


def portfolio_stats(profiles: dict[str, dict], D: dict[str, pd.DataFrame],
                    as_of: pd.Timestamp = DEFAULT_AS_OF) -> dict:
    """آمار کل سبد مشتریان — دستیار هرگز خودش جمع نمی‌زند، این را صدا می‌زند."""
    P = list(profiles.values())
    rev = sum(p["commercial"]["revenue_nominal"] for p in P)
    gp = sum(p["margin"]["gross_profit"] for p in P)
    od = sum(p["receivables"]["uncollected_overdue"] for p in P)
    nyd = sum(p["receivables"]["uncollected_not_yet_due"] for p in P)
    net = sum(p["receivables"]["net_contribution"] for p in P)
    neg = [p for p in P if p["receivables"]["net_contribution"] < 0]
    top10 = sorted(P, key=lambda p: -p["commercial"]["revenue_nominal"])[:10]
    S = as_of_view(D, as_of)["sales"]
    monthly = (S.groupby("month_key").agg(volume=("qty", "sum"), revenue=("line_amount", "sum"),
                                          gross_profit=("gross_profit", "sum"),
                                          customers=("Customer_ID", "nunique"))
                .reset_index())
    monthly["margin_pct"] = (monthly.gross_profit / monthly.revenue * 100).round(2)
    base_v, base_r = monthly.volume.iloc[1], monthly.revenue.iloc[1]
    monthly["volume_index"] = (monthly.volume / base_v * 100).round(0)
    monthly["revenue_index"] = (monthly.revenue / base_r * 100).round(0)

    # ماه‌های ناقص مرزی (نخستین و آخرین ماه بازه) روند را می‌شکنند: ۱۳۹۸/۰۹ تنها
    # ۱۶ روز و ۱۴۰۱/۰۴ تنها ۶ روز داده دارد. علامت‌گذاری می‌شوند تا نمودارها
    # آن‌ها را کنار بگذارند، ولی از جدول داده حذف نمی‌شوند.
    span = S.groupby("month_key").date.agg(["min", "max"])
    partial = []
    for mk, row in span.iterrows():
        first_of = pd.Timestamp(mk + "-01")
        last_of = first_of + pd.offsets.MonthEnd(0)
        if row["min"] > first_of + pd.Timedelta(days=6) or \
                row["max"] < last_of - pd.Timedelta(days=6):
            partial.append(mk)
    monthly["is_partial"] = monthly.month_key.isin(partial)

    # مقایسهٔ فصل بهار سال‌های شمسی — هم‌ارزترین مقایسهٔ ممکن در این داده.
    # هر سه پنجره از ۱ فروردین تا ۱۶ خرداد بریده می‌شوند (آخرین روز داده)، تا
    # نه فصلی‌بودن اثر بگذارد و نه پنجرهٔ ناقص. برچسب هم به تقویم مخاطب است.
    import jalali as _j
    last = S.date.max().date()
    jy_last, jm_last, jd_last = _j.to_jalali(last)
    end_m, end_d = (jm_last, jd_last) if jm_last <= 3 else (3, 31)
    springs = []
    for jy in range(1398, jy_last + 1):
        try:
            a = pd.Timestamp(_j.to_gregorian(jy, 1, 1))
            b = pd.Timestamp(_j.to_gregorian(jy, end_m, end_d))
        except Exception:                                    # noqa: BLE001
            continue
        if a < S.date.min() or b > S.date.max():
            continue
        g = S[(S.date >= a) & (S.date <= b)]
        if len(g) < 100:
            continue
        springs.append({
            "label": f"بهار {jy}", "jyear": jy,
            "window_fa": f"{_j.fmt(a.date(), 'long')} تا {_j.fmt(b.date(), 'long')}",
            "volume": round(float(g.qty.sum()), 0),
            "revenue": round(float(g.line_amount.sum())),
            "gross_profit": round(float(g.gross_profit.sum())),
            "margin_pct": round(float(g.gross_profit.sum() / g.line_amount.sum() * 100), 2),
            "customers": int(g.Customer_ID.nunique()),
            "avg_unit_price": round(float(np.average(g.unit_price, weights=g.qty)), 1)})
    for h in springs:
        b0 = springs[0]
        h["volume_index"] = round(h["volume"] / b0["volume"] * 100)
        h["revenue_index"] = round(h["revenue"] / b0["revenue"] * 100)
        h["customer_index"] = round(h["customers"] / b0["customers"] * 100)
        h["price_index"] = round(h["avg_unit_price"] / b0["avg_unit_price"] * 100)

    return {
        "partial_months": partial,
        "half_years": springs,
        "half_year_note": (f"هر سه پنجره از 1 فروردین تا {end_d} "
                           f"{_j.MONTHS_FA[end_m - 1]} بریده شده‌اند تا دقیقاً هم‌ارز باشند "
                           f"(آخرین روز دادهٔ فروش: {_j.fmt(last, 'long')})."),
        "as_of": str(as_of.date()),
        "customers": len(P),
        "customers_with_sales": sum(1 for p in P if p["coverage"]["sales"]),
        "revenue_nominal": round(rev), "revenue_real": sum(p["commercial"]["revenue_real"] for p in P),
        "volume": round(sum(p["commercial"]["volume"] for p in P), 1),
        "gross_profit": round(gp), "gross_margin_pct": round(gp / rev * 100, 2),
        "overdue": round(od), "not_yet_due": round(nyd),
        "overdue_pct_of_revenue": round(od / rev * 100, 1),
        "overdue_x_gross_profit": round(od / gp, 2),
        "net_contribution": round(net),
        "net_negative_customers": len(neg),
        "net_negative_revenue_share_pct": round(
            sum(p["commercial"]["revenue_nominal"] for p in neg) / rev * 100, 1),
        "top10_revenue_share_pct": round(
            sum(p["commercial"]["revenue_nominal"] for p in top10) / rev * 100, 1),
        "dormant_180d": sum(1 for p in P
                            if (p["commercial"]["days_since_last_purchase"] or 9999) > DORMANCY_DAYS),
        "negative_margin_lines_pct": round(
            sum(p["margin"]["negative_margin_lines"] for p in P) /
            sum(p["commercial"]["order_lines"] for p in P) * 100, 1),
        "realized_cost_share_pct": round(float((S.cost_basis == "realized").mean() * 100), 1),
        "open_complaints": sum(p["complaints"]["open"] for p in P),
        "monthly": monthly.to_dict("records"),
        "segments": {
            seg: {
                "customers": sum(1 for p in P if p["identity"]["segment"] == seg),
                "revenue": round(sum(p["commercial"]["revenue_nominal"] for p in P
                                     if p["identity"]["segment"] == seg)),
                "gross_profit": round(sum(p["margin"]["gross_profit"] for p in P
                                          if p["identity"]["segment"] == seg)),
                "overdue": round(sum(p["receivables"]["uncollected_overdue"] for p in P
                                     if p["identity"]["segment"] == seg)),
            } for seg in ["A", "B", "C"]
        },
    }


def load_all(as_of: pd.Timestamp = DEFAULT_AS_OF):
    D, rep = clean(load_raw())
    profiles = build_profiles(D, as_of)
    add_complaint_impact(D, profiles, as_of)
    return D, profiles, rep


if __name__ == "__main__":
    import json
    import time
    t = time.time()
    D, rep = clean(load_raw())
    print(f"پاک‌سازی در {time.time() - t:.1f} ثانیه")
    for k, v in rep.items():
        print(f"  {k}: {v}")
    t = time.time()
    P = build_profiles(D)
    print(f"{len(P)} پروفایل در {time.time() - t:.1f} ثانیه")
    st = portfolio_stats(P, D)
    print(json.dumps({k: v for k, v in st.items() if k not in ("monthly",)},
                     ensure_ascii=False, indent=2))
