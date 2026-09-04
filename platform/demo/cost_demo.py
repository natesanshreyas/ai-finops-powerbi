#!/usr/bin/env python3
# Cost-only walkthrough: how the SAME month of AI cost looks in Bronze (4 native
# billing shapes) -> Silver (conformed per-platform) -> Gold (composite table).
import sqlite3
MONTH="2026-08"
db=sqlite3.connect(":memory:"); c=db.cursor()

def show(sql,title,note=""):
    c.execute(sql); cols=[d[0] for d in c.description]; rows=c.fetchall()
    sr=[["" if v is None else (f"{v:,.2f}" if isinstance(v,float) else str(v)) for v in r] for r in rows]
    w=[len(x) for x in cols]
    for r in sr: w=[max(a,len(b)) for a,b in zip(w,r)]
    bar="+"+"+".join("-"*(x+2) for x in w)+"+"
    print("\n"+title); 
    if note: print(note)
    print(bar); print("| "+" | ".join(c2.ljust(x) for c2,x in zip(cols,w))+" |"); print(bar)
    for r in sr: print("| "+" | ".join(v.ljust(x) for v,x in zip(r,w))+" |")
    print(bar)

# ============================ BRONZE: 4 native billing feeds ==================
# Each platform bills in a DIFFERENT unit, grain, and shape. No common schema.
c.execute("CREATE TABLE bronze_foundry_cost(usage_date TEXT,meter TEXT,tokens INTEGER,cost_usd REAL,tag_app TEXT)")
c.executemany("INSERT INTO bronze_foundry_cost VALUES(?,?,?,?,?)",[
 (MONTH,"gpt-4o Input Tokens",  28900000,361.25,"checkout"),
 (MONTH,"gpt-4o Output Tokens",  9600000,288.00,"checkout"),
 (MONTH,"gpt-4o Input Tokens",  15100000,192.92,"hrbot")])
c.execute("CREATE TABLE bronze_m365_cost(period TEXT,sku TEXT,seats_assigned INTEGER,unit_price_month REAL)")
c.execute("INSERT INTO bronze_m365_cost VALUES(?,?,?,?)",(MONTH,"Microsoft_365_Copilot",250,30.00))
c.execute("CREATE TABLE bronze_ghc_cost(period TEXT,sku TEXT,seats INTEGER,seat_price REAL,included_premium_reqs INTEGER,overage_premium_reqs INTEGER,unit_price REAL,overage_cost REAL)")
c.execute("INSERT INTO bronze_ghc_cost VALUES(?,?,?,?,?,?,?,?)",(MONTH,"copilot_enterprise",120,39.00,120000,7800,0.04,312.00))
c.execute("CREATE TABLE bronze_studio_cost(period TEXT,action_type TEXT,credit_rate INTEGER,interactions INTEGER,credits_consumed INTEGER,cost_usd REAL)")
c.executemany("INSERT INTO bronze_studio_cost VALUES(?,?,?,?,?,?)",[
 (MONTH,"Classic answer",   1,180000,180000,450.00),
 (MONTH,"Generative answer",2,120000,240000,600.00),
 (MONTH,"Agent action",     3, 32000, 96000,240.00)])

print("="*70); print(" BRONZE — 4 native billing feeds (different unit, grain, shape)"); print("="*70)
show("SELECT tag_app,meter,tokens,cost_usd FROM bronze_foundry_cost","Foundry  (Azure Cost Mgmt: per-token, VARIABLE, real $)")
show("SELECT sku,seats_assigned,unit_price_month,seats_assigned*unit_price_month AS monthly_cost FROM bronze_m365_cost","M365 Copilot  (per-SEAT license: FIXED, flat $/seat/mo)")
show("SELECT sku,seats,seats*seat_price AS seat_cost,included_premium_reqs,overage_premium_reqs,unit_price,overage_cost FROM bronze_ghc_cost","GitHub Copilot  (seats FIXED + premium-request overage VARIABLE @ $0.04 x model-multiplier)")
show("SELECT action_type,credit_rate,interactions,credits_consumed,cost_usd FROM bronze_studio_cost","Copilot Studio  (Copilot CREDITS by action type: pure consumption)")

# ============================ SILVER: conformed per-platform ==================
# Normalize every feed to ONE cost schema: platform, cost_type, native unit,
# actual $, discount %, discounted $. Now they're comparable.
c.execute("""CREATE TABLE silver_platform_cost(
  period TEXT,platform TEXT,billing_model TEXT,cost_type TEXT,native_unit TEXT,
  native_qty REAL,actual_cost REAL,discount_pct REAL,discounted_cost REAL)""")
rows=[
 (MONTH,"Foundry","Consumption","Variable","token",53600000, 842.17,0.15,None),
 (MONTH,"M365Copilot","Per-seat","Fixed","seat_month",250,     7500.00,0.00,None),
 (MONTH,"GitHubCopilot","Seat+overage","Fixed","seat_month",120,4680.00,0.05,None),
 (MONTH,"GitHubCopilot","Seat+overage","Variable","premium_request",7800,312.00,0.05,None),
 (MONTH,"CopilotStudio","Consumption","Variable","copilot_credit",516000,1290.00,0.20,None)]
rows=[r[:8]+(round(r[6]*(1-r[7]),2),) for r in rows]
c.executemany("INSERT INTO silver_platform_cost VALUES(?,?,?,?,?,?,?,?,?)",rows)
print("\n"+"="*70); print(" SILVER — conformed to ONE cost schema (comparable across platforms)"); print("="*70)
show("SELECT platform,cost_type,native_unit,native_qty,actual_cost,discount_pct,discounted_cost FROM silver_platform_cost",
    "silver_platform_cost")

# ============================ GOLD: composite cost table ======================
# One row per platform: actual, discounted, fixed/variable split, forecast,
# % of total. This is what the CFO page reads.
c.execute("""CREATE TABLE gold_cost_summary AS
 SELECT platform,
        SUM(actual_cost)                                   AS actual_cost,
        SUM(discounted_cost)                               AS discounted_cost,
        SUM(CASE WHEN cost_type='Fixed'    THEN actual_cost ELSE 0 END) AS fixed_cost,
        SUM(CASE WHEN cost_type='Variable' THEN actual_cost ELSE 0 END) AS variable_cost
 FROM silver_platform_cost GROUP BY platform""")
print("\n"+"="*70); print(" GOLD — composite cost table (one row per platform + forecast + % total)"); print("="*70)
show("""SELECT platform,actual_cost,discounted_cost,fixed_cost,variable_cost,
        ROUND(actual_cost*1.08,2) AS forecast_next_mo,
        ROUND(100.0*actual_cost/(SELECT SUM(actual_cost) FROM gold_cost_summary),1) AS pct_of_total
     FROM gold_cost_summary ORDER BY actual_cost DESC""","gold_cost_summary")
show("""SELECT 'ALL PLATFORMS' AS total,
        ROUND(SUM(actual_cost),2) AS actual,
        ROUND(SUM(discounted_cost),2) AS discounted,
        ROUND(SUM(actual_cost)-SUM(discounted_cost),2) AS discount_savings,
        ROUND(SUM(fixed_cost),2) AS fixed,
        ROUND(SUM(variable_cost),2) AS variable,
        ROUND(SUM(actual_cost)*1.08,2) AS forecast_next_mo
     FROM gold_cost_summary""","GRAND TOTAL (the headline CFO numbers)")
