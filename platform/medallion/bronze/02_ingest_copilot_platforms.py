# Fabric notebook — BRONZE: Copilot family (M365, GitHub, Copilot Studio)
# ---------------------------------------------------------------------------
# These three platforms are MOCK in the PoC because the tenant lacks the SKUs /
# policies (see README "Data provenance"). This notebook is the real connector
# scaffold: swap each mock reader for the documented API and NOTHING downstream
# changes, because provenance is a data column (dim_platform.data_source), not a
# code branch.
#
# Going-live requirements (see README "Going live"):
#   M365 Copilot   -> Graph getMicrosoft365CopilotUsageUserDetail, Reports.Read.All
#   GitHub Copilot -> REST /copilot/metrics + billing/usage, admin:enterprise PAT
#   Copilot Studio -> Dataverse msdyn_aievent (per-environment)
# ---------------------------------------------------------------------------
from pyspark.sql import functions as F

LAKE = "abfss://finops@<lake>.dfs.core.windows.net"


def land(name: str, df, mode="append"):
    (df.withColumn("_ingest_ts", F.current_timestamp())
       .withColumn("_source", F.lit(name))
       .write.format("delta").mode(mode).option("mergeSchema", "true")
       .saveAsTable(f"finops_bronze.{name}_raw"))
    print(f"bronze {mode}: finops_bronze.{name}_raw ({df.count()} rows)")


# --- M365 Copilot -----------------------------------------------------------
# LIVE: call Graph report API (period D7/D30), page through userDetail rows.
# Concealed user names MUST be disabled in M365 admin or UPNs arrive hashed.
#   graph = MsGraphClient(scope="Reports.Read.All")
#   rows  = graph.get_report("getMicrosoft365CopilotUsageUserDetail", period="D30")
# MOCK today: read the PoC extract if present.
m365 = spark.read.option("multiLine", True).json(f"{LAKE}/landing/m365copilot/*.json")
land("m365copilot", m365)

# --- GitHub Copilot ---------------------------------------------------------
# LIVE: /enterprises/{ent}/copilot/metrics (seats, active users) and
# /enterprises/{ent}/settings/billing/usage (premium-request netAmount USD).
gh = spark.read.option("multiLine", True).json(f"{LAKE}/landing/githubcopilot/*.json")
land("githubcopilot", gh)

# --- Copilot Studio ---------------------------------------------------------
# LIVE: Dataverse msdyn_aievent is per-environment; msdyn_creditconsumed is
# already net of zero-rating -> use it directly, do NOT model credits from
# activity counts (README rationale #7). Exclude bring-your-own-model rows to
# avoid double-counting Foundry spend (rationale #6).
studio = spark.read.option("multiLine", True).json(f"{LAKE}/landing/copilotstudio/*.json")
land("copilotstudio", studio)
