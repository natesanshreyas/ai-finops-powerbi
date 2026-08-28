#!/usr/bin/env python3
"""
Emit AIFinOps.Report/report.json — four pages with visuals pre-placed.

Power BI's report layout JSON is version-sensitive. If Desktop refuses to open
it, delete report.json, reopen the .pbip (Desktop regenerates a blank report
against the same semantic model) and drag the measures on manually. The
semantic model is the durable artifact; visuals are 10 minutes of work.
"""
import json
from pathlib import Path

RP = Path(__file__).parent / "AIFinOps.Report"
RP.mkdir(parents=True, exist_ok=True)

W, H = 1280, 720


def q(table, col=None, measure=None, agg=None):
    e = {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": col}} if col \
        else {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": measure}}
    return e


def visual(vtype, x, y, w, h, projections, title=None, z=0):
    cfg = {
        "name": f"v{abs(hash((vtype, x, y, title))) % 10**8}",
        "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": z, "width": w, "height": h}}],
        "singleVisual": {
            "visualType": vtype,
            "projections": projections,
            "prototypeQuery": {"Version": 2, "From": [], "Select": []},
            "drillFilterOtherVisuals": True,
            "objects": {},
        },
    }
    if title:
        cfg["singleVisual"]["vcObjects"] = {
            "title": [{"properties": {"text": {"expr": {"Literal": {"Value": f"'{title}'"}}},
                                      "show": {"expr": {"Literal": {"Value": "true"}}}}}]
        }
    return cfg


def measure_proj(role, table, name):
    return {role: [{"queryRef": f"{table}.{name}", "active": True}]}


def card(x, y, w, h, table, measure, title):
    return visual("card", x, y, w, h,
                  {"Values": [{"queryRef": f"{table}.{measure}"}]}, title)


def chart(vtype, x, y, w, h, cat_ref, val_refs, title):
    return visual(vtype, x, y, w, h,
                  {"Category": [{"queryRef": cat_ref}],
                   "Y": [{"queryRef": r} for r in val_refs]}, title)


def tbl(x, y, w, h, refs, title):
    return visual("tableEx", x, y, w, h,
                  {"Values": [{"queryRef": r} for r in refs]}, title)


F = "fact_ai_usage"

pages = [
    {"name": "ReportSection1", "displayName": "1 · Spend Overview", "ordinal": 0, "visuals": [
        card(16, 16, 240, 120, F, "Total AI Cost", "Total AI Spend"),
        card(272, 16, 240, 120, F, "Fixed Cost", "Fixed (licences)"),
        card(528, 16, 240, 120, F, "Variable Cost", "Variable (consumption)"),
        card(784, 16, 240, 120, F, "Cost Confidence %", "Billed vs Modelled"),
        card(1040, 16, 224, 120, F, "Cost (30d run-rate)", "30-day run-rate"),
        chart("clusteredColumnChart", 16, 152, 624, 280,
              "dim_platform.platform_name",
              [f"{F}.Total AI Cost"], "Spend by platform"),
        chart("lineChart", 656, 152, 608, 280,
              "dim_date.date_key", [f"{F}.Total AI Cost"], "Daily spend trend"),
        tbl(16, 448, 1248, 250,
            ["dim_platform.platform_name", "dim_platform.billing_model",
             "dim_platform.native_unit", "dim_platform.data_source",
             f"{F}.Total AI Cost", f"{F}.Cost Confidence %"],
            "Platform capability matrix — note data_source: REAL vs MOCK"),
    ]},
    {"name": "ReportSection2", "displayName": "2 · Foundry Tokenomics (REAL)", "ordinal": 1, "visuals": [
        card(16, 16, 240, 120, F, "Total Tokens", "Total tokens"),
        card(272, 16, 240, 120, F, "Input Tokens", "Input"),
        card(528, 16, 240, 120, F, "Output Tokens", "Output"),
        card(784, 16, 240, 120, F, "Cache Hit Rate", "Cache hit rate"),
        card(1040, 16, 224, 120, F, "Cost per 1K Tokens", "$ / 1K tokens"),
        chart("clusteredBarChart", 16, 152, 624, 280, "dim_model.model_name",
              [f"{F}.Total Tokens"], "Tokens by model"),
        chart("clusteredBarChart", 656, 152, 608, 280, "dim_identity.team",
              [f"{F}.Total AI Cost"], "Foundry cost by team"),
        tbl(16, 448, 1248, 250,
            ["dim_model.model_name", f"{F}.Input Tokens", f"{F}.Output Tokens",
             f"{F}.Cached Tokens", f"{F}.Requests", f"{F}.Avg Latency (ms)",
             f"{F}.Total AI Cost"], "Per-model detail"),
    ]},
    {"name": "ReportSection3", "displayName": "3 · Waste & Utilisation", "ordinal": 2, "visuals": [
        card(16, 16, 300, 140, F, "Idle Licensed Users", "Idle licensed users (28d)"),
        card(332, 16, 300, 140, F, "Idle Seat Waste (monthly)", "Recoverable / month"),
        card(648, 16, 300, 140, F, "Licensed Seats", "Total paid seats"),
        card(964, 16, 300, 140, F, "Cost per Active User", "Cost / active user"),
        tbl(16, 172, 1248, 300,
            ["dim_identity.display_name", "dim_identity.team", "dim_identity.business_unit",
             f"{F}.Licensed Seats", f"{F}.M365 Prompts", f"{F}.Premium Requests",
             f"{F}.Total AI Cost"],
            "Per-user activity — zero prompts + a paid seat = reclaim candidate"),
        chart("clusteredColumnChart", 16, 488, 1248, 210, "dim_cost_center.cost_center_name",
              [f"{F}.Total AI Cost"], "Spend by cost centre"),
    ]},
    {"name": "ReportSection4", "displayName": "4 · Rate Card (edit me)", "ordinal": 3, "visuals": [
        tbl(16, 16, 1248, 420,
            ["dim_rate_card.platform", "dim_rate_card.unit_type", "dim_rate_card.model",
             "dim_rate_card.unit_price_usd", "dim_rate_card.source", "dim_rate_card.note"],
            "dim_rate_card — the single customer-supplied input. Every modelled $ derives from here."),
        chart("clusteredBarChart", 16, 452, 1248, 246, "dim_platform.platform_name",
              [f"{F}.Billed Cost", f"{F}.Modelled Cost"],
              "Billed vs modelled by platform — how much of the number is real"),
    ]},
]

layout = {
    "id": 0,
    "resourcePackages": [],
    "config": json.dumps({
        "version": "5.43",
        "themeCollection": {"baseTheme": {"name": "CY24SU06"}},
        "activeSectionIndex": 0,
        "settings": {"useStylableVisualContainerHeader": True},
    }),
    "layoutOptimization": 0,
    "sections": [{
        "id": i,
        "name": p["name"],
        "displayName": p["displayName"],
        "ordinal": p["ordinal"],
        "width": W, "height": H,
        "displayOption": 1,
        "config": json.dumps({}),
        "filters": "[]",
        "visualContainers": [{
            "x": v["layouts"][0]["position"]["x"],
            "y": v["layouts"][0]["position"]["y"],
            "z": v["layouts"][0]["position"]["z"],
            "width": v["layouts"][0]["position"]["width"],
            "height": v["layouts"][0]["position"]["height"],
            "config": json.dumps(v),
            "filters": "[]",
        } for v in p["visuals"]],
    } for i, p in enumerate(pages)],
    "filters": "[]",
    "pods": [],
}

(RP / "report.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")
print(f"  AIFinOps.Report/report.json  ({len(pages)} pages, "
      f"{sum(len(p['visuals']) for p in pages)} visuals)")
