# Fabric deployment — cost, unblock steps, and one-command deploy

This folder deploys the AI FinOps accelerator into **your** Microsoft Fabric
tenant: a workspace, a lakehouse, the medallion notebooks (bronze→silver→gold),
and your `data/*.csv` uploaded to OneLake. It is dependency-free (Python stdlib)
and authenticates through the Azure CLI you already have (`az login`).

---

## 1. Why it isn't deployed yet (the blocker)

Your signed-in user (`snatesan@MngEnvMCAP025145.onmicrosoft.com`) currently has
**no Power BI / Fabric license**, and you are a **Global Reader** (read-only),
so the Fabric REST API rejects every call with `UserNotLicensed`. The tenant has
no Fabric capacity provisioned. Nothing about this is a code problem — it is
pure licensing, and it is fixed by you in **2 one-time browser clicks**.

## 2. Unblock — 2 clicks, $0

1. **Get a free Power BI license.** Open <https://app.fabric.microsoft.com> and
   sign in with your work account. This self-service-provisions a **free Power BI
   license** for your user (no admin needed; it's the standard sign-up flow).
2. **Start the Fabric Trial.** In the Fabric portal top-right **Account manager
   ▸ Start trial**. You get a **60-day Fabric trial capacity (~F64 power, $0)**.

That's it. Re-run the preflight and it will go green:

```bash
python3 platform/deploy/fabric_deploy.py --steps preflight
```

> If self-service trials are disabled by your tenant admin, ask an admin to
> either enable trials or assign you a Pro license + an F-SKU capacity.

## 3. Cost — so you don't burn your account

Fabric bills on **capacity compute time**, not per query. Storage in OneLake is
trivial. Key numbers:

| Option | Compute cost | Notes |
|---|---|---|
| **Fabric Trial (recommended)** | **$0 for 60 days** | ~F64 power. Perfect for the demo. Auto-expires — no runaway bill. |
| **F2 (smallest paid)** | ~$0.36 / hr → **~$262/mo if left on 24×7** | Enough for this model. **Pause when idle** ⇒ $0. |
| **F2 paused** | **$0 compute** | Pausing an F-SKU stops all compute billing; state is preserved. |
| **OneLake storage** | ~$0.023 / GB / mo | This dataset is a few MB ⇒ effectively $0. |
| **Copilot in Fabric** | included on F2+ | consumes capacity units while running; negligible for demo use. |

**How to not burn the account:**
- Use the **Trial** for the demo → $0.
- If you go paid, buy **F2**, and **pause it** whenever you're not demoing.
- Run this deployer with **`--delete-after`** to tear the workspace down when done.
- The Trial hard-expires at 60 days, so a forgotten trial can't cost you money.

## 4. One-command deploy (after unblocking)

```bash
# dry check first
python3 platform/deploy/fabric_deploy.py --steps preflight

# full deploy: workspace + lakehouse + CSV upload + notebooks + run
python3 platform/deploy/fabric_deploy.py

# deploy, demo, then remove everything ($0 residual)
python3 platform/deploy/fabric_deploy.py --delete-after
```

Run a subset of stages with `--steps` (e.g. `--steps workspace lakehouse upload`).
Override names with env vars `FINOPS_WORKSPACE` / `FINOPS_LAKEHOUSE`.

### What each step does
| step | action |
|---|---|
| `preflight` | verify `az` login + Fabric token + that you're licensed |
| `capacity` | find an active capacity (prefers the Trial), else guidance |
| `workspace` | create/reuse `AI FinOps Accelerator`, assign to capacity |
| `lakehouse` | create/reuse `finops_lakehouse` |
| `upload` | push all `data/*.csv` to `Files/bronze` via OneLake (ADLS Gen2) |
| `notebooks` | import bronze/silver/gold notebooks (`.py` → single-cell `.ipynb`) |
| `run` | execute bronze → silver → gold in order, polling to completion |
| teardown | `--delete-after` deletes the workspace |

## 5. Publishing the semantic model + report

The deployer builds the **lakehouse + gold tables**. To publish the
`AIFinOps.SemanticModel` + `AIFinOps.Report` on top, use either:

- **(a) Fabric Git integration** — in the workspace, *Workspace settings ▸ Git
  integration*, connect this GitHub repo, and *Update from Git*. Fabric imports
  the PBIP items natively. Best for a repeatable, source-controlled customer
  accelerator.
- **(b) Power BI Desktop Publish** — open `AIFinOps.pbip`, *Publish* to the
  `AI FinOps Accelerator` workspace. Fastest for a one-off demo.

Hand-crafting PBIP definition REST payloads is intentionally avoided (brittle);
Git integration is the supported, durable path for the accelerator.

## 6. Demo storyline this enables

1. **Collect** — bronze notebooks show raw platform telemetry landing in OneLake.
2. **Land in Fabric** — lakehouse Files/Tables, one place for all AI platforms.
3. **Conform** — silver/gold build the unified FinOps star (identity/app/BU/cost).
4. **Persona dashboards** — the 10-page report (CFO → Governance → Engineering →
   App Owner → License Optimization → **Extractable Data Spectrum**).
5. **Optimize** — idle licenses, expensive-model usage, budget overruns, chargeback.

Real vs mock provenance never blurs — `dim_platform.data_source`,
`fact.cost_is_estimated`, and the catalog's `availability` column keep REAL,
AVAILABLE, MOCK, and ROADMAP signals clearly labeled.
