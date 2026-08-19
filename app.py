"""سرور دستیار هوشمند مشتریان — FastAPI

اجرا:
    export GEMINI_API_KEY=...          # اختیاری؛ بدون آن حالت قطعی کار می‌کند
    python -m uvicorn app:app --reload --port 8000
سپس http://127.0.0.1:8000
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import insights as I
import jalali
from copilot import SUGGESTED_QUESTIONS, Copilot
from store import load_store, norm, render_profile_fa

BASE = Path(__file__).parent
STATIC = BASE / "static"

app = FastAPI(title="دستیار هوشمند مشتریان — نفیس نخ", docs_url="/api/docs")

print("بارگذاری پروفایل‌ها…")
STORE = load_store()
COPILOT = Copilot(STORE)
print(f"آماده: {len(STORE.P)} پروفایل | حالت دستیار: {COPILOT.mode}")


# ────────────────────────────────────────────────────────────────── مدل‌ها
class ChatRequest(BaseModel):
    question: str
    history: list[dict] = []


# ────────────────────────────────────────────────────────────────── صفحات
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ────────────────────────────────────────────────────────────────── API
@app.get("/api/meta")
def meta():
    s = STORE.portfolio
    return {
        "as_of": s["as_of"],
        "as_of_fa": jalali.fmt(s["as_of"], "long"),
        "customers": s["customers"],
        "text_records": len(STORE.text_index),
        "copilot_mode": COPILOT.mode,
        "copilot_model": COPILOT.model if COPILOT.client else None,
        "copilot_error": COPILOT.last_error,
        "suggested_questions": SUGGESTED_QUESTIONS,
        "risk_codes": RISK_CODES,
        "opportunity_codes": OPP_CODES,
        "sort_options": SORT_OPTIONS,
        "data_caveats": _caveats(s),
    }


def _caveats(s: dict) -> list[str]:
    h = s.get("half_years") or []
    price = (f"قیمت میانگین واحد در مقایسهٔ هم‌ارز {h[0]['label']} تا {h[-1]['label']} "
             f"{h[-1]['price_index'] / 100:.1f} برابر شده") if len(h) >= 2 else "قیمت‌ها به‌شدت تغییر کرده‌اند"
    return [
        f"فروش اسمی است و واحد پول در فایل منبع مشخص نشده. {price}؛ پس برای هر تحلیل روند، "
        "حجم (کیلوگرم) یا فروش حقیقی مبناست، نه فروش اسمی.",
        f"حاشیه سود ترکیبی است: {s['realized_cost_share_pct']}٪ خطوط بر مبنای هزینهٔ تحقق‌یافته "
        "و بقیه بر مبنای هزینهٔ برآوردی محصول-ماه. مبنای برآوردی حاشیه را حدود ۵ واحد درصد "
        "خوش‌بینانه‌تر نشان می‌دهد، پس همیشه سهم مبنا را کنار عدد حاشیه بخوانید.",
        "«معوق» سررسیدگذشته و ریسک اعتباری است؛ «سررسیدنشده» سرمایه در گردش است و ریسک نیست. "
        "مشارکت خالص فقط بخش معوق را از سود ناخالص کسر می‌کند.",
        "فیلد وضعیت مشتری در فایل منبع (Customer_Status) تقریباً همان رکود ۱۸۰ روزه است: "
        "از ۲۴۳ مشتری خریدار، هیچ‌کدام «غیرفعال» علامت نخورده‌اند و از ۴۰۱ مشتری راکد، ۳۷۱ "
        "مورد «غیرفعال»اند (هم‌خطی ۹۵٪). یعنی این فیلد اطلاعات تازه‌ای بر رکود نمی‌افزاید و "
        "به‌کارگیری‌اش در مدل‌سازی ریزش، استدلال دایره‌وار است. قرنطینه شده و در هیچ تحلیلی به‌کار نرفته.",
        "۵۲ ردیف با شناسهٔ SL-CMP در شیت فروش، رکورد ردیابی شکایت‌اند نه فروش (تاریخ ۱۴۰۴–۱۴۰۵ "
        "و تنها ردیف‌های دارای همبافت). این ردیف‌ها از تمام محاسبات فروش جدا شده‌اند.",
    ]


RISK_CODES = [
    {"code": "overdue_exceeds_gp", "label": "معوق بیش از سود ناخالص"},
    {"code": "overdue_aged", "label": "معوق کهنه (+۱ سال)"},
    {"code": "bounced_cheques", "label": "چک برگشتی"},
    {"code": "over_credit_limit", "label": "عبور از سقف اعتبار"},
    {"code": "low_collection_rate", "label": "نرخ وصول پایین"},
    {"code": "dormant", "label": "مشتری راکد"},
    {"code": "volume_collapse", "label": "ریزش حجم خرید"},
    {"code": "quality_linked_decline", "label": "کاهش خرید پس از شکایت"},
    {"code": "open_severe_complaint", "label": "شکایت باز با شدت زیاد"},
    {"code": "thin_margin", "label": "حاشیه سود نازک"},
    {"code": "many_negative_lines", "label": "خطوط زیان‌ده زیاد"},
    {"code": "uncontacted_active", "label": "فعال بدون تماس"},
    {"code": "no_crm_history", "label": "بدون سابقه در CRM"},
    {"code": "competitor_dominant", "label": "سهم غالب رقیب"},
    {"code": "single_family_dependency", "label": "وابستگی تک‌محصولی"},
]

OPP_CODES = [
    {"code": "wallet_share_gap", "label": "شکاف سهم از سبد"},
    {"code": "approved_sample_idle", "label": "نمونهٔ تأییدشده بلااستفاده"},
    {"code": "pending_dev_request", "label": "درخواست توسعهٔ بی‌پاسخ"},
    {"code": "pending_offers", "label": "آفر بی‌پاسخ"},
    {"code": "offer_responsive", "label": "پاسخ‌ده به آفر"},
    {"code": "cross_sell", "label": "فروش مکمل"},
    {"code": "growing", "label": "رشد حجم خرید"},
    {"code": "repricing_upside", "label": "ظرفیت اصلاح قیمت"},
    {"code": "win_back", "label": "بازیابی مشتری بزرگ"},
    {"code": "recovered_trust", "label": "شکایت رسیدگی‌شده و خرید پایدار"},
]

SORT_OPTIONS = [
    {"key": "revenue", "label": "فروش", "asc": False},
    {"key": "gross_profit", "label": "سود ناخالص", "asc": False},
    {"key": "margin_pct", "label": "حاشیه سود", "asc": True},
    {"key": "net_contribution", "label": "مشارکت خالص", "asc": True},
    {"key": "overdue", "label": "مطالبات معوق", "asc": False},
    {"key": "oldest_overdue_days", "label": "عمر معوق", "asc": False},
    {"key": "days_since_purchase", "label": "روز از آخرین خرید", "asc": False},
    {"key": "volume_trend", "label": "روند حجم", "asc": True},
    {"key": "risk_score", "label": "امتیاز ریسک", "asc": False},
    {"key": "opportunity_score", "label": "امتیاز فرصت", "asc": False},
    {"key": "open_complaints", "label": "شکایت باز", "asc": False},
    {"key": "wallet_share", "label": "سهم از سبد", "asc": True},
]


@app.get("/api/portfolio")
def portfolio():
    s = dict(STORE.portfolio)
    f = STORE.frame
    s["text_records"] = len(STORE.text_index)
    s["risk_counts"] = [
        {"code": r["code"], "label": r["label"],
         "customers": int(f["risk_codes"].str.contains(r["code"], na=False).sum()),
         "revenue": float(f.loc[f["risk_codes"].str.contains(r["code"], na=False), "revenue"].sum()),
         "overdue": float(f.loc[f["risk_codes"].str.contains(r["code"], na=False), "overdue"].sum())}
        for r in RISK_CODES]
    s["opportunity_counts"] = [
        {"code": o["code"], "label": o["label"],
         "customers": int(f["opp_codes"].str.contains(o["code"], na=False).sum()),
         "revenue": float(f.loc[f["opp_codes"].str.contains(o["code"], na=False), "revenue"].sum())}
        for o in OPP_CODES]
    s["risk_counts"].sort(key=lambda x: -x["customers"])
    s["opportunity_counts"].sort(key=lambda x: -x["customers"])
    return s


@app.get("/api/customers")
def customers(q: str = "", sort_by: str = "revenue", ascending: bool = False,
              segment: str = "", risk: str = "", opportunity: str = "", limit: int = 200):
    f = STORE.frame.copy()
    if q:
        qq = norm(q)
        f = f[[qq in norm(i) for i in f.index]]
    if segment:
        f = f[f.segment == segment]
    if risk:
        f = f[f["risk_codes"].str.contains(risk, na=False)]
    if opportunity:
        f = f[f["opp_codes"].str.contains(opportunity, na=False)]
    if sort_by not in f.columns:
        raise HTTPException(400, f"ستون «{sort_by}» وجود ندارد")
    f = f.sort_values(sort_by, ascending=ascending, na_position="last").head(int(limit))
    cols = ["segment", "revenue", "revenue_rank", "gross_profit", "margin_pct", "overdue",
            "net_contribution", "days_since_purchase", "volume_trend", "open_complaints",
            "risk_score", "opportunity_score", "top_risk", "top_opportunity", "next_action",
            "wallet_share", "collection_rate", "volume"]
    out = f[cols].reset_index().rename(columns={"index": "customer_id"})
    return JSONResponse(content={"total": int(len(STORE.frame)), "shown": len(out),
                                 "rows": _clean(out.to_dict("records"))})


def _clean(obj: Any) -> Any:
    """NaN را به None تبدیل می‌کند تا JSON معتبر بماند."""
    import math
    if isinstance(obj, list):
        return [_clean(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


@app.get("/api/customer/{customer_id}")
def customer(customer_id: str):
    p = STORE.P.get(customer_id.strip().upper())
    if not p:
        raise HTTPException(404, "مشتری یافت نشد")
    return JSONResponse(content=_clean({
        **p,
        "profile_text": render_profile_fa(p),
        "dates_fa": {
            "relationship_start": jalali.fmt(p["identity"]["relationship_start"]),
            "first_purchase": jalali.fmt(p["commercial"]["first_purchase"]),
            "last_purchase": jalali.fmt(p["commercial"]["last_purchase"]),
            "last_interaction": jalali.fmt(p["engagement"]["last_interaction"]),
            "last_complaint": jalali.fmt(p["complaints"]["last_complaint"]),
        },
    }))


@app.get("/api/search_text")
def search_text(q: str, limit: int = 25, kind: str = ""):
    terms = [t for t in norm(q).split() if len(t) > 2]
    if not terms:
        return {"hits": [], "note": "عبارت جست‌وجو خیلی کوتاه است."}
    hits = []
    for d in STORE.text_index:
        if kind and d["kind"] != kind:
            continue
        score = sum(1 for t in terms if t in d["_n"])
        if score:
            hits.append({"score": score, "customer_id": d["customer_id"], "kind": d["kind"],
                         "date": d["date"], "date_fa": jalali.fmt(d["date"]),
                         "title": d["title"], "meta": d["meta"], "text": str(d["text"])[:500]})
    hits.sort(key=lambda x: (-x["score"], x["date"] or ""))
    by_cust: dict[str, int] = {}
    for h in hits:
        by_cust[h["customer_id"]] = by_cust.get(h["customer_id"], 0) + 1
    return {"total": len(hits), "customers": len(by_cust),
            "top_customers": sorted(by_cust.items(), key=lambda x: -x[1])[:8],
            "hits": hits[:int(limit)]}


@app.post("/api/chat")
def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "پرسش خالی است")
    r = COPILOT.ask(req.question, req.history)
    return r


@app.get("/api/health")
def health():
    return {"ok": True, "profiles": len(STORE.P), "mode": COPILOT.mode}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
