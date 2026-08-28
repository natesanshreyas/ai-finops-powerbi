#!/usr/bin/env python3
"""
Build the AI FinOps star-schema CSVs.

Foundry slice  = REAL data exported from law-apim-finops / ApimAiGateway_CL.
Other three    = MOCK, clearly flagged via dim_platform[data_source].

Every cost figure is quantity x dim_rate_card[unit_price_usd]. The rate card is
the single customer-supplied input: PTU vs PAYG, EA/MCA discounts, credit pack
tier and GitHub volume pricing all land there and nowhere else.
"""
import json, csv, random, datetime as dt
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
OUT = ROOT / "AIFinOps.SemanticModel" / "data"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20260828)

def write(name, rows, cols):
    with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {name}.csv  {len(rows):>5} rows")

# ---------------------------------------------------------------- rate card
# CUSTOMER EDITS THIS. Foundry rows are the real ones pulled from ApimModelRate_CL.
rate_card = []
for r in json.loads((DATA / "ApimModelRate_CL.json").read_text()):
    for unit, price in (("input_token", r["InputPer1k"]),
                        ("output_token", r["OutputPer1k"]),
                        ("cached_token", r["CachedInputPer1k"])):
        rate_card.append({
            "rate_key": f"Foundry|{unit}|{r['ModelName']}",
            "platform": "Foundry", "unit_type": unit, "model": r["ModelName"],
            "unit_price_usd": float(price) / 1000.0,   # rate card is per 1K
            "effective_from": r["EffectiveFrom"][:10], "currency": "USD",
            "source": "REAL - ApimModelRate_CL",
            "note": "Replace with your PTU-blended or EA-discounted effective rate",
        })
rate_card += [
    {"rate_key": "M365Copilot|seat_day|", "platform": "M365Copilot", "unit_type": "seat_day",
     "model": "", "unit_price_usd": 30.0/30, "effective_from": "2026-01-01", "currency": "USD",
     "source": "LIST PRICE", "note": "$30/user/mo enterprise annual commitment. Use your contract rate."},
    {"rate_key": "CopilotStudio|copilot_credit|", "platform": "CopilotStudio", "unit_type": "copilot_credit",
     "model": "", "unit_price_usd": 0.008, "effective_from": "2026-01-01", "currency": "USD",
     "source": "LIST PRICE", "note": "25,000-credit pack $200/mo = $0.008. PAYG = $0.01."},
    {"rate_key": "GitHubCopilot|seat_day|", "platform": "GitHubCopilot", "unit_type": "seat_day",
     "model": "", "unit_price_usd": 39.0/30, "effective_from": "2026-01-01", "currency": "USD",
     "source": "LIST PRICE", "note": "Copilot Enterprise $39/user/mo. Use your volume tier."},
    {"rate_key": "GitHubCopilot|premium_request|", "platform": "GitHubCopilot", "unit_type": "premium_request",
     "model": "", "unit_price_usd": 0.04, "effective_from": "2026-01-01", "currency": "USD",
     "source": "LIST PRICE", "note": "Overage rate. Billed amount comes from netAmount when available."},
    {"rate_key": "M365Copilot|prompt|", "platform": "M365Copilot", "unit_type": "prompt",
     "model": "", "unit_price_usd": 0.0, "effective_from": "2026-01-01", "currency": "USD",
     "source": "N/A", "note": "M365 Copilot prompts are NOT billable. Usage signal only."},
]
write("dim_rate_card", rate_card,
      ["rate_key","platform","unit_type","model","unit_price_usd","effective_from",
       "currency","source","note"])

def _i(v):
    """Log Analytics JSON export emits the string 'None' for nulls."""
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def price(platform, unit_type, model=""):
    for r in rate_card:
        if r["platform"] == platform and r["unit_type"] == unit_type and r["model"] == model:
            return r["unit_price_usd"]
    return 0.0

# ---------------------------------------------------------- identity + org
own = {o["ClientId"]: o for o in json.loads((DATA / "ApimClientOwnership_CL.json").read_text())}
identities, cost_centers, seen_cc = [], [], set()

for o in own.values():
    identities.append({"identity_key": o["ClientId"], "display_name": o["AppName"],
                       "principal_type": "ServicePrincipal", "upn": "", "github_login": "",
                       "team": o["Team"], "business_unit": o["BusinessUnit"],
                       "cost_center_key": o["CostCenter"]})
    if o["CostCenter"] not in seen_cc:
        seen_cc.add(o["CostCenter"])
        cost_centers.append({"cost_center_key": o["CostCenter"], "cost_center_name": o["Team"],
                             "business_unit": o["BusinessUnit"], "owner_upn": ""})

# mock humans for the three non-live platforms
MOCK_PEOPLE = [
    ("aisha.rahman",  "Aisha Rahman",  "Underwriting", "Insurance", "CC-1000"),
    ("marco.silva",   "Marco Silva",   "Claims",       "Insurance", "CC-1000"),
    ("jenny.oyelaran","Jenny Oyelaran","Platform",     "Technology","CC-3000"),
    ("dev.patel",     "Dev Patel",     "Platform",     "Technology","CC-3000"),
    ("sam.chen",      "Sam Chen",      "Search",       "Discovery", "CC-2000"),
    ("robin.hale",    "Robin Hale",    "Checkout",     "Retail",    "CC-1000"),
    ("lee.novak",     "Lee Novak",     "Data",         "Technology","CC-3000"),
    ("kim.arroyo",    "Kim Arroyo",    "Actuarial",    "Insurance", "CC-4000"),
]
for upn, name, team, bu, cc in MOCK_PEOPLE:
    identities.append({"identity_key": upn, "display_name": name, "principal_type": "User",
                       "upn": f"{upn}@contoso.com", "github_login": upn.replace(".", "-"),
                       "team": team, "business_unit": bu, "cost_center_key": cc})
    if cc not in seen_cc:
        seen_cc.add(cc)
        cost_centers.append({"cost_center_key": cc, "cost_center_name": team,
                             "business_unit": bu, "owner_upn": ""})

write("dim_identity", identities,
      ["identity_key","display_name","principal_type","upn","github_login",
       "team","business_unit","cost_center_key"])
write("dim_cost_center", cost_centers,
      ["cost_center_key","cost_center_name","business_unit","owner_upn"])

# ------------------------------------------------------------- dim_platform
write("dim_platform", [
 {"platform_key":"Foundry","platform_name":"Azure AI Foundry","billing_model":"Consumption (tokens)",
  "native_unit":"token","has_token_telemetry":"TRUE","has_native_cost":"TRUE",
  "is_variable_cost":"TRUE","data_source":"REAL - APIM gateway / Log Analytics"},
 {"platform_key":"GitHubCopilot","platform_name":"GitHub Copilot Enterprise","billing_model":"Seats + premium requests",
  "native_unit":"premium_request","has_token_telemetry":"FALSE","has_native_cost":"TRUE",
  "is_variable_cost":"TRUE","data_source":"MOCK - needs classic PAT (manage_billing:copilot)"},
 {"platform_key":"CopilotStudio","platform_name":"Microsoft Copilot Studio","billing_model":"Copilot Credits",
  "native_unit":"copilot_credit","has_token_telemetry":"FALSE","has_native_cost":"FALSE",
  "is_variable_cost":"TRUE","data_source":"MOCK - needs Dataverse SP + env URL"},
 {"platform_key":"M365Copilot","platform_name":"Microsoft 365 Copilot","billing_model":"Per-seat licence",
  "native_unit":"seat_day","has_token_telemetry":"FALSE","has_native_cost":"FALSE",
  "is_variable_cost":"FALSE","data_source":"MOCK - needs Graph app (Reports.Read.All)"},
], ["platform_key","platform_name","billing_model","native_unit","has_token_telemetry",
    "has_native_cost","is_variable_cost","data_source"])

# ------------------------------------------------------- FACT: Foundry (REAL)
gw = json.loads((DATA / "foundry_gateway_raw.json").read_text())
facts, models, seen_m = [], [], set()

for r in gw:
    d = r["TimeGenerated"][:10]
    m = r["ModelName"] or "unknown"
    if m not in seen_m:
        seen_m.add(m)
        models.append({"model_key": m, "model_name": m, "model_version": r.get("ModelVersion",""),
                       "provider": "Azure OpenAI", "modality": "text"})
    ident = r.get("ClientId") or r.get("Oid") or "unknown"
    o = own.get(ident, {})
    pt  = _i(r.get("PromptTokens"))
    ct  = _i(r.get("CompletionTokens"))
    cch = _i(r.get("CachedPromptTokens"))
    billable_in = max(pt - cch, 0)
    cost = (billable_in * price("Foundry","input_token",m)
            + ct  * price("Foundry","output_token",m)
            + cch * price("Foundry","cached_token",m))
    facts.append({
        "usage_date": d, "platform_key": "Foundry", "identity_key": ident, "model_key": m,
        "cost_center_key": o.get("CostCenter",""), "unit_type": "token",
        "quantity": pt + ct, "input_tokens": pt, "output_tokens": ct, "cached_tokens": cch,
        "requests": 1, "cost_usd": round(cost, 8), "cost_is_estimated": "FALSE",
        "is_error": r.get("IsError","False"), "latency_ms": r.get("TotalLatencyMs") if str(r.get("TotalLatencyMs")) not in ("None","") else 0,
    })

# ------------------------------------------------- FACT: three mocked slices
# Real Foundry rows keep their true timestamps (they are all from one load-test
# day). The mocked platforms span a 60-day window so the trend visuals are usable.
real_days = sorted({f["usage_date"] for f in facts})
d1 = dt.date.today()
d0 = d1 - dt.timedelta(days=59)
days = [d0 + dt.timedelta(days=i) for i in range(60)]
start, end = d0.isoformat(), d1.isoformat()
print(f"  real Foundry activity on: {', '.join(real_days)}")

for m in ["gpt-4.1", "claude-sonnet-4.5", "gpt-4.1-mini"]:
    if m not in seen_m:
        seen_m.add(m)
        models.append({"model_key": m, "model_name": m, "model_version": "",
                       "provider": "GitHub Copilot", "modality": "text"})

# M365 Copilot: every licensed user costs the same every day. Two are deliberately idle.
M365_USERS = MOCK_PEOPLE[:6]
IDLE = {"lee.novak", "kim.arroyo"}
for day in days:
    for upn, _n, _t, _bu, cc in MOCK_PEOPLE:
        facts.append({"usage_date": day.isoformat(), "platform_key": "M365Copilot",
            "identity_key": upn, "model_key": "", "cost_center_key": cc,
            "unit_type": "seat_day", "quantity": 1, "input_tokens": 0, "output_tokens": 0,
            "cached_tokens": 0, "requests": 0,
            "cost_usd": round(price("M365Copilot","seat_day"), 6),
            "cost_is_estimated": "TRUE", "is_error": "False", "latency_ms": 0})
        prompts = 0 if upn in IDLE else random.randint(3, 45)
        if prompts:
            facts.append({"usage_date": day.isoformat(), "platform_key": "M365Copilot",
                "identity_key": upn, "model_key": "", "cost_center_key": cc,
                "unit_type": "prompt", "quantity": prompts, "input_tokens": 0,
                "output_tokens": 0, "cached_tokens": 0, "requests": prompts,
                "cost_usd": 0.0, "cost_is_estimated": "TRUE",
                "is_error": "False", "latency_ms": 0})

# Copilot Studio: credits, weekday-weighted
for day in days:
    weekday = day.weekday() < 5
    for upn, _n, _t, _bu, cc in MOCK_PEOPLE[:5]:
        credits = random.randint(400, 2600) if weekday else random.randint(20, 200)
        facts.append({"usage_date": day.isoformat(), "platform_key": "CopilotStudio",
            "identity_key": upn, "model_key": "", "cost_center_key": cc,
            "unit_type": "copilot_credit", "quantity": credits, "input_tokens": 0,
            "output_tokens": 0, "cached_tokens": 0, "requests": 0,
            "cost_usd": round(credits * price("CopilotStudio","copilot_credit"), 6),
            "cost_is_estimated": "TRUE", "is_error": "False", "latency_ms": 0})

# GitHub Copilot: seats every day + premium requests on weekdays
for day in days:
    for upn, _n, _t, _bu, cc in MOCK_PEOPLE[2:8]:
        facts.append({"usage_date": day.isoformat(), "platform_key": "GitHubCopilot",
            "identity_key": upn, "model_key": "", "cost_center_key": cc,
            "unit_type": "seat_day", "quantity": 1, "input_tokens": 0, "output_tokens": 0,
            "cached_tokens": 0, "requests": 0,
            "cost_usd": round(price("GitHubCopilot","seat_day"), 6),
            "cost_is_estimated": "TRUE", "is_error": "False", "latency_ms": 0})
        if day.weekday() < 5 and random.random() > 0.25:
            n = random.randint(5, 90)
            mdl = random.choice(["gpt-4.1", "claude-sonnet-4.5"])
            facts.append({"usage_date": day.isoformat(), "platform_key": "GitHubCopilot",
                "identity_key": upn, "model_key": mdl, "cost_center_key": cc,
                "unit_type": "premium_request", "quantity": n, "input_tokens": 0,
                "output_tokens": 0, "cached_tokens": 0, "requests": n,
                "cost_usd": round(n * price("GitHubCopilot","premium_request"), 6),
                "cost_is_estimated": "FALSE", "is_error": "False", "latency_ms": 0})

write("fact_ai_usage", facts,
      ["usage_date","platform_key","identity_key","model_key","cost_center_key","unit_type",
       "quantity","input_tokens","output_tokens","cached_tokens","requests","cost_usd",
       "cost_is_estimated","is_error","latency_ms"])
write("dim_model", models, ["model_key","model_name","model_version","provider","modality"])

# ---------------------------------------------------------------- dim_date
cal = []
c = d0 - dt.timedelta(days=d0.weekday())
while c <= d1 + dt.timedelta(days=7):
    cal.append({"date_key": c.isoformat(), "year": c.year, "quarter": f"Q{(c.month-1)//3+1}",
                "month": c.month, "month_name": c.strftime("%b %Y"), "day": c.day,
                "day_name": c.strftime("%a"), "is_weekday": "TRUE" if c.weekday() < 5 else "FALSE",
                "year_month": c.strftime("%Y-%m")})
    c += dt.timedelta(days=1)
write("dim_date", cal, ["date_key","year","quarter","month","month_name","day",
                        "day_name","is_weekday","year_month"])

real = sum(f["cost_usd"] for f in facts if f["cost_is_estimated"] == "FALSE")
est  = sum(f["cost_usd"] for f in facts if f["cost_is_estimated"] == "TRUE")
print(f"\n  window          {start} -> {end}")
print(f"  billed  (real)  ${real:,.2f}")
print(f"  modelled (est)  ${est:,.2f}")
print(f"  confidence      {real/(real+est)*100:.1f}% of spend is billed, not modelled")
