"""دستیار هوشمند — اتصال Gemini به لایهٔ ابزار با function calling.

سه اصل طراحی:
  ۱. مدل محاسبه نمی‌کند. هر عدد از ابزار می‌آید، پس قابل راستی‌آزمایی است.
  ۲. اگر کلید API نباشد یا شبکه قطع باشد، دستیار به حالت قطعی برمی‌گردد و
     همان ابزارها را با تطبیق قاعده‌محور صدا می‌زند. دموی هکاتون نباید بمیرد.
  ۳. سه هشدار دادهٔ اجباری در پرامپت سیستم قفل شده‌اند: تورم، مبنای بهای
     تمام‌شده، و پرچم نشتی وضعیت مشتری.
"""
from __future__ import annotations

import os
import re
from typing import Any

from store import Store, norm

MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]

SYSTEM_PROMPT = """تو دستیار تحلیل مشتریان یک تولیدکنندهٔ نخ پلی‌استر (POY) هستی.
به پرسش‌های مدیران و کارشناسان فروش دربارهٔ مشتریان پاسخ می‌دهی.

قواعد الزامی:
- هیچ عددی را خودت محاسبه یا حدس نزن. همیشه ابزار مناسب را صدا بزن و فقط
  اعدادی را بگو که ابزار برگردانده است. اگر ابزار عددی نداد، بگو در دسترس نیست.
- پاسخ‌ها را کوتاه و عملیاتی بنویس. جدول یا فهرست نشانه‌دار بهتر از پاراگراف است.
- همیشه فارسی پاسخ بده.
- برای پرسش کلی دربارهٔ کل کسب‌وکار از portfolio_summary استفاده کن، نه جمع‌زدن
  پروفایل‌ها.
- برای یافتن مشتری «که فلان مشکل را دارد» از search_customers با پارامتر
  has_risk یا has_opportunity استفاده کن.
- برای پرسش‌هایی که به متن اشاره دارند (شکایت دربارهٔ فلان موضوع، گزارش
  کارشناس، درخواست فنی) از search_text استفاده کن.

سه هشدار دادهٔ همیشگی — هر بار که این اعداد را نقل می‌کنی، قید کن:
۱. فروش اسمی است و ارزش پول در بازهٔ داده حدود ۱۱٫۷ برابر تغییر کرده است. برای
   روند، حجم (کیلوگرم) یا فروش حقیقی را مبنا بگیر و بگو کدام را استفاده کردی.
۲. حاشیه سود ترکیبی است: ۳۲٪ خطوط بر مبنای هزینهٔ تحقق‌یافته و بقیه بر مبنای
   هزینهٔ برآوردی که حاشیه را حدود ۵ واحد درصد خوش‌بینانه‌تر نشان می‌دهد.
۳. فیلد source_status_LEAKY همان رکود ۱۸۰ روزه است که برچسب دیگری خورده؛ هرگز
   به‌عنوان شاهد استفاده نکن.

تفاوت مطالبات: «معوق» سررسیدگذشته است و ریسک اعتباری؛ «سررسیدنشده» سرمایه در
گردش است و ریسک نیست. مشارکت خالص فقط بخش معوق را کسر می‌کند.

بازهٔ داده تا ۹ تیر ۱۴۰۱ است. هرگز طوری پاسخ نده که گویی از بعد از آن خبر داری.
"""

TOOLS_SPEC = [
    {
        "name": "portfolio_summary",
        "description": "آمار کل سبد مشتریان: فروش، سود، حاشیه، مطالبات معوق، تمرکز، تعداد مشتری راکد و آمار بخش‌ها. برای هر پرسشی که دربارهٔ کل کسب‌وکار است و نه یک مشتری خاص.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_customer_profile",
        "description": "پروفایل کامل یک مشتری: عملکرد تجاری، سودآوری و بهای تمام‌شده، مطالبات، شکایات و کیفیت، تعاملات، درخواست‌های توسعه، آفرها و سهم از سبد.",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string",
                                           "description": "شناسهٔ مشتری، مثل C_937594"}},
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_risks_and_actions",
        "description": "ریسک‌ها، فرصت‌ها و اقدام بعدی پیشنهادی یک مشتری، هر کدام همراه شاهد عددی و واحد مسئول.",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
    },
    {
        "name": "search_customers",
        "description": "رتبه‌بندی و پالایش سبد مشتریان. پیش از get_customer_profile از این استفاده کن تا بفهمی کدام مشتری‌ها را باید بررسی کنی.",
        "parameters": {
            "type": "object",
            "properties": {
                "sort_by": {"type": "string",
                            "enum": ["revenue", "gross_profit", "margin_pct", "overdue",
                                     "net_contribution", "days_since_purchase", "volume",
                                     "complaints", "open_complaints", "wallet_share",
                                     "risk_score", "opportunity_score", "volume_trend",
                                     "collection_rate", "oldest_overdue_days"],
                            "description": "ستون مرتب‌سازی"},
                "ascending": {"type": "boolean", "description": "صعودی؟ برای بدترین‌ها true"},
                "limit": {"type": "integer"},
                "segment": {"type": "string", "enum": ["A", "B", "C"]},
                "has_risk": {"type": "string",
                             "description": "کد ریسک: overdue_exceeds_gp، overdue_aged، bounced_cheques، over_credit_limit، low_collection_rate، dormant، volume_collapse، quality_linked_decline، open_severe_complaint، thin_margin، many_negative_lines، uncontacted_active، no_crm_history، competitor_dominant، market_price_pressure، single_family_dependency"},
                "has_opportunity": {"type": "string",
                                    "description": "کد فرصت: wallet_share_gap، approved_sample_idle، pending_dev_request، pending_offers، offer_responsive، cross_sell، growing، repricing_upside، recovered_trust، win_back"},
                "min_revenue": {"type": "number"},
                "dormant_days_min": {"type": "integer",
                                     "description": "حداقل روز از آخرین خرید"},
            },
        },
    },
    {
        "name": "search_text",
        "description": "جست‌وجو در متن آزاد سازمان: متن شکایت‌های مشتریان، گزارش‌های کارشناسان فروش در CRM و شرح درخواست‌های توسعه محصول. برای پرسش‌هایی مثل «کدام مشتری‌ها از شید رنگ شکایت کردند» یا «چه کسی درخواست بسته‌بندی خاص داشت».",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "عبارت فارسی برای جست‌وجو"},
                "limit": {"type": "integer"},
                "kind": {"type": "string", "enum": ["شکایت", "تعامل CRM", "درخواست توسعه"]},
            },
            "required": ["query"],
        },
    },
    {
        "name": "compare_customers",
        "description": "مقایسهٔ دو تا پنج مشتری روی شاخص‌های تصمیم‌ساز.",
        "parameters": {
            "type": "object",
            "properties": {"customer_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["customer_ids"],
        },
    },
]


class Copilot:
    def __init__(self, store: Store, api_key: str | None = None, model: str | None = None):
        self.store = store
        self.dispatch = {
            "portfolio_summary": lambda **k: store.portfolio_summary(),
            "get_customer_profile": store.get_customer_profile,
            "get_risks_and_actions": store.get_risks_and_actions,
            "search_customers": store.search_customers,
            "search_text": store.search_text,
            "compare_customers": store.compare_customers,
        }
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL") or MODELS[0]
        self.client = None
        self.last_error: str | None = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as exc:                     # noqa: BLE001
                self.last_error = f"راه‌اندازی Gemini ناموفق بود: {exc}"

    @property
    def mode(self) -> str:
        return "gemini" if self.client else "deterministic"

    # ───────────────────────────────────────────────── حالت مدل زبانی
    def _ask_gemini(self, question: str, history: list[dict] | None = None,
                    max_turns: int = 6) -> dict:
        from google.genai import types

        tools = [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t["name"], description=t["description"],
                                      parameters=t["parameters"]) for t in TOOLS_SPEC])]
        cfg = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, tools=tools, temperature=0.2,
            max_output_tokens=2048)

        contents = []
        for h in (history or [])[-6:]:
            contents.append(types.Content(role="user" if h["role"] == "user" else "model",
                                          parts=[types.Part(text=h["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

        trace: list[dict] = []
        for _ in range(max_turns):
            resp = self.client.models.generate_content(
                model=self.model, contents=contents, config=cfg)
            cand = resp.candidates[0] if resp.candidates else None
            parts = list(cand.content.parts or []) if cand and cand.content else []
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not calls:
                text = "".join(p.text for p in parts if getattr(p, "text", None)) or \
                       "پاسخی تولید نشد."
                return {"answer": text, "trace": trace, "mode": "gemini", "model": self.model}

            contents.append(cand.content)
            results = []
            for fc in calls:
                args = dict(fc.args or {})
                try:
                    out = self.dispatch[fc.name](**args)
                except Exception as exc:                 # noqa: BLE001
                    out = f"خطا در اجرای ابزار: {exc}"
                trace.append({"tool": fc.name, "args": args, "chars": len(str(out))})
                results.append(types.Part.from_function_response(
                    name=fc.name, response={"result": str(out)}))
            contents.append(types.Content(role="user", parts=results))
        return {"answer": "به سقف مراحل رسیدیم بدون پاسخ نهایی.", "trace": trace,
                "mode": "gemini", "model": self.model}

    # ─────────────────────────────────── حالت قطعی (پشتیبان بدون شبکه)
    _CID = re.compile(r"\bC[_-]?(\d{4,6})\b", re.I)

    def _ask_deterministic(self, question: str) -> dict:
        """تطبیق قاعده‌محور روی همان ابزارها. برای وقتی شبکه یا کلید نیست."""
        q = norm(question)
        trace: list[dict] = []

        def run(tool: str, **kw):
            trace.append({"tool": tool, "args": kw})
            return self.dispatch[tool](**kw)

        m = self._CID.search(question)
        if m:
            cid = f"C_{m.group(1).zfill(6)}"
            if any(w in q for w in ["ریسک", "فرصت", "اقدام", "خطر", "پیشنهاد", "چه کنم"]):
                return {"answer": run("get_risks_and_actions", customer_id=cid),
                        "trace": trace, "mode": "deterministic"}
            return {"answer": run("get_customer_profile", customer_id=cid),
                    "trace": trace, "mode": "deterministic"}

        def hasw(*words) -> bool:
            return any(norm(w) in q for w in words)

        # الگوهای ترکیبی، مرتب از خاص به عام
        if hasw("شکایت", "کیفیت") and hasw("کم", "کاهش", "افت", "ریزش", "پایین"):
            code = "quality_linked_decline"
        elif hasw("چک برگشتی", "چک"):
            code = "bounced_cheques"
        elif hasw("سقف اعتبار", "اعتبار"):
            code = "over_credit_limit"
        elif hasw("راکد", "بی خرید", "قطع خرید", "برنگشته", "ریزش مشتری", "بازیابی"):
            code = "dormant"
        elif hasw("معوق", "مطالبات", "وصول", "بدهی", "طلب"):
            code = "overdue_exceeds_gp"
        elif hasw("حاشیه", "زیان", "سودآوری", "ضرر", "سود منفی"):
            code = "thin_margin"
        elif hasw("ریزش حجم", "کاهش خرید", "افت حجم", "افت فروش"):
            code = "volume_collapse"
        else:
            code = None
        if code:
            return {"answer": run("search_customers", has_risk=code,
                                  sort_by="revenue", limit=10),
                    "trace": trace, "mode": "deterministic"}

        if hasw("فرصت", "رشد", "سهم از سبد", "نمونه تایید", "فروش مکمل"):
            opp = ("wallet_share_gap" if hasw("سهم از سبد") else
                   "approved_sample_idle" if hasw("نمونه") else
                   "growing" if hasw("رشد") else
                   "cross_sell" if hasw("مکمل") else None)
            return {"answer": run("search_customers", has_opportunity=opp,
                                  sort_by="opportunity_score", limit=10)
                    if opp else run("search_customers", sort_by="opportunity_score", limit=10),
                    "trace": trace, "mode": "deterministic"}

        if hasw("شید رنگ", "پرز", "استحکام", "بسته بندی", "دنیر", "فیلامنت", "رگه",
                "گزارش کارشناس", "متن", "شکایت درباره"):
            return {"answer": run("search_text", query=question, limit=10),
                    "trace": trace, "mode": "deterministic"}

        if hasw("کل سبد", "کل مشتریان", "خلاصه", "وضعیت شرکت", "مجموع", "پرتفو",
                "کل کسب و کار", "وضعیت کلی"):
            return {"answer": run("portfolio_summary"), "trace": trace,
                    "mode": "deterministic"}

        # پیش‌فرض: بدترین مشارکت خالص، چون همیشه پرسش درست کسب‌وکار است
        return {"answer": "پرسش را دقیق‌تر متوجه نشدم؛ این مشتریان بیشترین ارزش‌سوزی را "
                          "دارند:\n\n" + run("search_customers", sort_by="net_contribution",
                                             ascending=True, limit=8),
                "trace": trace, "mode": "deterministic"}

    # ────────────────────────────────────────────────────────── ورودی اصلی
    def ask(self, question: str, history: list[dict] | None = None) -> dict:
        if self.client:
            try:
                return self._ask_gemini(question, history)
            except Exception as exc:                      # noqa: BLE001
                self.last_error = str(exc)
                out = self._ask_deterministic(question)
                out["fallback_reason"] = f"Gemini پاسخ نداد ({type(exc).__name__})؛ " \
                                         "پاسخ از حالت قطعی تولید شد."
                return out
        return self._ask_deterministic(question)


SUGGESTED_QUESTIONS = [
    "وضعیت کل سبد مشتریان چطور است؟",
    "کدام مشتریان بیشترین ارزش‌سوزی را دارند؟",
    "کدام مشتری‌ها بعد از ثبت شکایت خریدشان کم شده؟",
    "پروفایل مشتری C_937594 را نشان بده",
    "کدام مشتری‌های بزرگ راکد شده‌اند و باید بازیابی شوند؟",
    "شکایت‌های مربوط به شید رنگ در کدام مشتری‌ها ثبت شده؟",
    "مشتریان با حاشیه سود منفی را فهرست کن",
    "برای مشتری C_683666 چه اقدامی پیشنهاد می‌کنی؟",
]

if __name__ == "__main__":
    import json
    import sys
    from store import load_store

    st = load_store()
    cp = Copilot(st)
    print(f"حالت دستیار: {cp.mode}" + (f" ({cp.model})" if cp.client else "")
          + (f" | خطا: {cp.last_error}" if cp.last_error else ""))
    qs = sys.argv[1:] or SUGGESTED_QUESTIONS[:3]
    for q in qs:
        print("\n" + "═" * 78 + f"\n❯ {q}\n" + "═" * 78)
        r = cp.ask(q)
        print(r["answer"][:2200])
        if r.get("trace"):
            print("\n[ابزارهای فراخوانی‌شده: " +
                  ", ".join(f"{t['tool']}({json.dumps(t.get('args', {}), ensure_ascii=False)})"
                            for t in r["trace"]) + "]")
        if r.get("fallback_reason"):
            print("[" + r["fallback_reason"] + "]")
