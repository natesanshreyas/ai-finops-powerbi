#!/usr/bin/env python3
"""
Build a REAL, runnable SQLite database that shows the SAME reality represented
three ways: Bronze (raw, per-source, messy) -> Silver (conformed, identity
resolved, cost reconciled) -> Gold (star schema the BI/report consumes).

Run it:
    python3 platform/demo/build_demo_db.py          # build + print every table
    sqlite3 platform/demo/finops_demo.db            # then poke around yourself

Everything here is illustrative MOCK data, but it is a working database: the
columns, keys, and transformations mirror the production medallion design in
docs/medallion-tables.md. Show your coworkers the three prints side by side —
the "differences" between layers are the whole point.
"""
import os
import sqlite3

DB = os.path.join(os.path.dirname(__file__), "finops_demo.db")
DAY = "2026-08-07"


def build(cur):
    cur.executescript("DROP TABLE IF EXISTS bronze_ghc_seats;"
                       "DROP TABLE IF EXISTS bronze_m365_usage;"
                       "DROP TABLE IF EXISTS bronze_azure_cost;"
                       "DROP TABLE IF EXISTS silver_identity;"
                       "DROP TABLE IF EXISTS silver_usage_unified;"
                       "DROP TABLE IF EXISTS fact_ai_usage;"
                       "DROP TABLE IF EXISTS dim_identity;"
                       "DROP TABLE IF EXISTS dim_business_unit;")

    # ---------------------------------------------------------------- BRONZE
    # Raw, exactly as each source hands it over. Note the problems a BI tool
    # can't use directly: different identity keys per source (github login vs
    # UPN), no cost on the usage feeds, idle rows (null last activity), and
    # cost that isn't tied to a person at all.
    cur.execute("""CREATE TABLE bronze_ghc_seats(
        github_login TEXT, seat_created TEXT, last_activity_at TEXT,
        last_activity_editor TEXT, plan_type TEXT)""")
    cur.executemany("INSERT INTO bronze_ghc_seats VALUES(?,?,?,?,?)", [
        ("pnair",  "2026-01-15", "2026-08-06T18:44:00Z", "vscode",  "enterprise"),
        ("rkhan",  "2026-01-15", "2026-08-07T09:02:00Z", "vscode",  "enterprise"),
        ("jdoe",   "2026-01-15", None,                    None,      "enterprise"),  # idle
        ("mlee",   "2026-03-01", None,                    None,      "enterprise"),  # idle
    ])

    cur.execute("""CREATE TABLE bronze_m365_usage(
        report_refresh_date TEXT, user_principal_name TEXT, display_name TEXT,
        last_activity_date TEXT, teams_last TEXT, excel_last TEXT, outlook_last TEXT)""")
    cur.executemany("INSERT INTO bronze_m365_usage VALUES(?,?,?,?,?,?,?)", [
        (DAY, "priya.nair@contoso.com", "Priya Nair", "2026-08-06", "2026-08-06", "2026-08-05", "2026-08-06"),
        (DAY, "raj.khan@contoso.com",   "Raj Khan",   "2026-08-07", "2026-08-07", None,         "2026-08-07"),
        (DAY, "sam.oketch@contoso.com", "Sam Oketch", None,         None,         None,         None),  # idle
    ])

    # Cost feed: authoritative $, but keyed to resource/tags, NOT to a user.
    cur.execute("""CREATE TABLE bronze_azure_cost(
        usage_date TEXT, meter_name TEXT, quantity REAL, cost_usd REAL,
        resource_id TEXT, tag_app TEXT, tag_env TEXT)""")
    cur.executemany("INSERT INTO bronze_azure_cost VALUES(?,?,?,?,?,?,?)", [
        (DAY, "gpt-4o Input Tokens",  184000, 0.46, ".../aoai-prod", "checkout", "prod"),
        (DAY, "gpt-4o Output Tokens",  42000, 0.63, ".../aoai-prod", "checkout", "prod"),
        (DAY, "gpt-4o Input Tokens",   90000, 0.23, ".../aoai-prod", "hrbot",    "prod"),
    ])

    # ---------------------------------------------------------------- SILVER
    # Conformed. The big win: github_login + UPN collapse into ONE identity_key,
    # non-humans get classified, and usage from every platform lands on ONE
    # daily grain with cost attached. This is where "relevant, clean" lives.
    cur.execute("""CREATE TABLE silver_identity(
        identity_key TEXT PRIMARY KEY, display_name TEXT, principal_type TEXT,
        upn TEXT, github_login TEXT, is_human INTEGER, business_unit_key TEXT)""")
    cur.executemany("INSERT INTO silver_identity VALUES(?,?,?,?,?,?,?)", [
        ("id-priya", "Priya Nair", "User",             "priya.nair@contoso.com", "pnair", 1, "BU-TECH"),
        ("id-raj",   "Raj Khan",   "User",             "raj.khan@contoso.com",   "rkhan", 1, "BU-TECH"),
        ("id-sam",   "Sam Oketch", "User",             "sam.oketch@contoso.com", None,    1, "BU-FIN"),
        ("id-jdoe",  "J Doe",      "User",             "j.doe@contoso.com",      "jdoe",  1, "BU-FIN"),
        ("id-mlee",  "M Lee",      "User",             "m.lee@contoso.com",      "mlee",  1, "BU-RETAIL"),
        ("id-hrbot", "HR Helpdesk Bot", "Agent",       None,                     None,    0, "BU-HR"),
        ("id-chk",   "checkout-service", "ServicePrincipal", None,               None,    0, "BU-RETAIL"),
    ])

    cur.execute("""CREATE TABLE silver_usage_unified(
        usage_date TEXT, platform TEXT, identity_key TEXT, application_key TEXT,
        unit_type TEXT, quantity REAL, requests INTEGER, cost_usd REAL,
        cost_is_estimated INTEGER, licensed INTEGER, active INTEGER)""")
    cur.executemany("INSERT INTO silver_usage_unified VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
        # Foundry usage -> attributed to the service principal / agent via tags
        (DAY, "Foundry",       "id-chk",   "APP-CHECKOUT", "token", 226000, 920, 1.09, 0, 0, 1),
        (DAY, "Foundry",       "id-hrbot", "APP-HRBOT",    "token",  90000, 300, 0.23, 0, 0, 1),
        # M365 seats -> one seat_day per licensed user; idle ones marked active=0
        (DAY, "M365Copilot",   "id-priya", "APP-M365", "seat_day", 1, 0, 1.00, 0, 1, 1),
        (DAY, "M365Copilot",   "id-raj",   "APP-M365", "seat_day", 1, 0, 1.00, 0, 1, 1),
        (DAY, "M365Copilot",   "id-sam",   "APP-M365", "seat_day", 1, 0, 1.00, 0, 1, 0),  # idle
        # GitHub seats
        (DAY, "GitHubCopilot", "id-priya", "APP-GHC",  "seat_day", 1, 0, 1.28, 0, 1, 1),
        (DAY, "GitHubCopilot", "id-raj",   "APP-GHC",  "seat_day", 1, 0, 1.28, 0, 1, 1),
        (DAY, "GitHubCopilot", "id-jdoe",  "APP-GHC",  "seat_day", 1, 0, 1.28, 0, 1, 0),  # idle
        (DAY, "GitHubCopilot", "id-mlee",  "APP-GHC",  "seat_day", 1, 0, 1.28, 0, 1, 0),  # idle
        # Copilot Studio messages
        (DAY, "CopilotStudio", "id-hrbot", "APP-HRBOT", "message", 1290, 540, 3.23, 0, 0, 1),
    ])

    # ---------------------------------------------------------------- GOLD
    # The star the Power BI model binds to. Same facts, now with full FK keys
    # and thin conformed dimensions -> every persona page slices this.
    cur.execute("""CREATE TABLE dim_business_unit(
        business_unit_key TEXT PRIMARY KEY, business_unit_name TEXT,
        division TEXT, monthly_budget_usd REAL, is_mock_budget INTEGER)""")
    cur.executemany("INSERT INTO dim_business_unit VALUES(?,?,?,?,?)", [
        ("BU-TECH",   "Technology",      "Product & Eng", 25000, 1),
        ("BU-FIN",    "Finance",         "Corporate",      8000, 1),
        ("BU-RETAIL", "Retail",          "Commercial",    15000, 1),
        ("BU-HR",     "Human Resources", "Corporate",      4000, 1),
    ])

    cur.execute("""CREATE TABLE dim_identity(
        identity_key TEXT PRIMARY KEY, display_name TEXT, principal_type TEXT,
        upn TEXT, github_login TEXT, identity_class TEXT, is_human INTEGER,
        home_business_unit_key TEXT)""")
    cur.execute("""INSERT INTO dim_identity
        SELECT identity_key, display_name, principal_type, upn, github_login,
               principal_type, is_human, business_unit_key FROM silver_identity""")

    cur.execute("""CREATE TABLE fact_ai_usage(
        usage_date TEXT, platform_key TEXT, identity_key TEXT, application_key TEXT,
        business_unit_key TEXT, unit_type TEXT, quantity REAL, requests INTEGER,
        cost_usd REAL, cost_is_estimated INTEGER)""")
    cur.execute("""INSERT INTO fact_ai_usage
        SELECT u.usage_date, u.platform, u.identity_key, u.application_key,
               i.business_unit_key, u.unit_type, u.quantity, u.requests,
               u.cost_usd, u.cost_is_estimated
        FROM silver_usage_unified u
        JOIN silver_identity i ON i.identity_key = u.identity_key""")


def show(cur, sql, title):
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    widths = [len(c) for c in cols]
    strrows = []
    for r in rows:
        sr = ["" if v is None else str(v) for v in r]
        strrows.append(sr)
        widths = [max(w, len(v)) for w, v in zip(widths, sr)]
    line = "+".join("-" * (w + 2) for w in widths)
    print("\n" + title)
    print("+" + line + "+")
    print("| " + " | ".join(c.ljust(w) for c, w in zip(cols, widths)) + " |")
    print("+" + line + "+")
    for sr in strrows:
        print("| " + " | ".join(v.ljust(w) for v, w in zip(sr, widths)) + " |")
    print("+" + line + "+")


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    build(cur)
    conn.commit()

    print("=" * 78)
    print(" BRONZE  —  raw, one shape per source. Not BI-ready:")
    print("   • GitHub is keyed by github_login; M365 by UPN — no common key")
    print("   • usage feeds carry NO cost; the cost feed carries NO user")
    print("   • idle seats show up as NULL last-activity")
    print("=" * 78)
    show(cur, "SELECT * FROM bronze_ghc_seats", "bronze_ghc_seats  (GitHub Copilot seats API)")
    show(cur, "SELECT * FROM bronze_m365_usage", "bronze_m365_usage  (Graph Copilot usage report)")
    show(cur, "SELECT * FROM bronze_azure_cost", "bronze_azure_cost  (Azure Cost Management — the $ authority)")

    print("\n" + "=" * 78)
    print(" SILVER  —  conformed. github_login + UPN collapse to ONE identity_key,")
    print("   non-humans classified, every platform on ONE daily grain WITH cost.")
    print("=" * 78)
    show(cur, "SELECT identity_key,display_name,principal_type,upn,github_login,is_human,business_unit_key FROM silver_identity",
         "silver_identity  (the identity graph — pnair & priya.nair are now one row)")
    show(cur, "SELECT * FROM silver_usage_unified", "silver_usage_unified  (all 4 platforms, one grain, cost attached)")

    print("\n" + "=" * 78)
    print(" GOLD  —  the star the Power BI report binds to (fact + dimensions).")
    print("=" * 78)
    show(cur, "SELECT * FROM fact_ai_usage", "fact_ai_usage  (grain: date × platform × identity × app × BU)")
    show(cur, "SELECT identity_key,display_name,identity_class,is_human,home_business_unit_key FROM dim_identity",
         "dim_identity  (conformed lookup)")
    show(cur, "SELECT * FROM dim_business_unit", "dim_business_unit  (conformed lookup + budget)")

    print("\n" + "=" * 78)
    print(" WHAT THE REPORT COMPUTES from Gold (the payoff):")
    print("=" * 78)
    show(cur, """SELECT bu.business_unit_name AS business_unit,
                        ROUND(SUM(f.cost_usd),2) AS total_ai_cost,
                        bu.monthly_budget_usd AS monthly_budget
                 FROM fact_ai_usage f JOIN dim_business_unit bu
                   ON bu.business_unit_key=f.business_unit_key
                 GROUP BY 1 ORDER BY 2 DESC""",
         "Total AI Cost by Business Unit")
    show(cur, """SELECT u.platform, i.display_name AS idle_user, u.cost_usd AS wasted_seat_cost_per_day
                 FROM silver_usage_unified u JOIN dim_identity i ON i.identity_key=u.identity_key
                 WHERE u.licensed=1 AND u.active=0
                 ORDER BY u.platform""",
         "Idle Licensed Users  (paying for a seat, zero activity = reclaim these)")

    conn.commit()
    conn.close()
    print("\nDatabase written to: %s" % DB)
    print("Explore it:  sqlite3 %s '.tables'" % DB)


if __name__ == "__main__":
    main()
