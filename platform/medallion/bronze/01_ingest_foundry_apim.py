# Fabric notebook — BRONZE: Azure AI Foundry via APIM AI Gateway
# ---------------------------------------------------------------------------
# Source of fidelity: the ONLY per-user Foundry attribution path is the APIM
# gateway (Entra JWT claims -> DCR -> Log Analytics). Azure Monitor token
# metrics carry no identity dimension, so we never use them for attribution.
#
# Bronze rule: land raw, append-only, source columns preserved, one file per
# extract. NO reshaping here beyond adding lineage columns. This is the
# historical system of record; silver/gold are always rebuildable from it.
#
# Real extract shape (data/foundry_gateway_raw.json), all values arrive as text:
#   ApiName, Appid, ClientId, Oid, BusinessUnitClaim, CostCenterClaim,
#   ModelName, ModelVersion, PromptTokens, CompletionTokens, CachedPromptTokens,
#   IsError, IsStreaming, StatusCode, OperationName, DeploymentRegion,
#   RequestId, TimeGenerated, BackendId
# ---------------------------------------------------------------------------
from pyspark.sql import functions as F

# Parameterised at pipeline runtime (Log Analytics export, ADLS landing, etc.)
RAW_PATH   = "abfss://finops@<lake>.dfs.core.windows.net/landing/foundry/*.json"
BRONZE_TBL = "finops_bronze.foundry_gateway_raw"
EXTRACT_ID = spark.conf.get("finops.extract_id", "manual")   # pipeline run id

raw = (
    spark.read.option("multiLine", True).json(RAW_PATH)
    # lineage / retention columns — the only additions bronze is allowed to make
    .withColumn("_ingest_ts",  F.current_timestamp())
    .withColumn("_extract_id", F.lit(EXTRACT_ID))
    .withColumn("_source",     F.lit("apim_ai_gateway"))
)

# Append-only: bronze retains full history. Partition by ingest day so that
# incremental Cost-Management/LA exports (which REPLACE month-to-date) never
# overwrite prior days.
(raw.write
    .format("delta")
    .mode("append")
    .partitionBy("_source")
    .option("mergeSchema", "true")
    .saveAsTable(BRONZE_TBL))

print(f"bronze append complete: {raw.count()} rows -> {BRONZE_TBL}")

# Companion reference extracts (small, overwrite latest snapshot is fine):
#   ApimClientOwnership_CL  -> identity/app ownership
#   ApimModelRate_CL        -> effective per-1k model rates
#   ApimTeamBudget_CL       -> team budgets
for name, path in [
    ("client_ownership", "landing/foundry/ownership/*.json"),
    ("model_rate",       "landing/foundry/rates/*.json"),
    ("team_budget",      "landing/foundry/budgets/*.json"),
]:
    (spark.read.option("multiLine", True)
        .json(f"abfss://finops@<lake>.dfs.core.windows.net/{path}")
        .withColumn("_ingest_ts", F.current_timestamp())
        .write.format("delta").mode("overwrite").option("overwriteSchema", "true")
        .saveAsTable(f"finops_bronze.foundry_{name}"))
    print(f"bronze snapshot: finops_bronze.foundry_{name}")
