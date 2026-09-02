#!/usr/bin/env python3
"""
Fabric deployment automation for the AI FinOps accelerator.

Dependency-free (stdlib urllib). Idempotent where the Fabric API allows it.
Auth uses the Azure CLI: you must be `az login`ed as a user that HAS a Power BI
/ Fabric license (see platform/deploy/README.md → "Unblock" for the 2 one-time
browser steps). The script fails fast with a clear message if you are not
licensed, so it will never silently do the wrong thing against your account.

What it does (each step is independently selectable via --steps):
  preflight  verify az login + Fabric token + that the user is licensed
  capacity   find a usable capacity (Trial or an F-SKU); print guidance if none
  workspace  create (or reuse) the target workspace, assign it to the capacity
  lakehouse  create (or reuse) the lakehouse
  upload     push all data/*.csv to Lakehouse Files/bronze via OneLake (ADLS)
  notebooks  import the 3 medallion notebooks (bronze/silver/gold)
  run        run bronze -> silver -> gold in order, polling to completion
  teardown   delete the workspace (honours --delete-after)

Publishing the semantic model + report: the robust path is Fabric Git
integration or "Publish" from Power BI Desktop — see README.md. This script
deliberately does NOT hand-craft PBIP definition payloads (brittle); it builds
the Lakehouse + gold tables that a Direct Lake / import model then consumes.

USAGE
  python3 platform/deploy/fabric_deploy.py --steps preflight
  python3 platform/deploy/fabric_deploy.py            # full deploy
  python3 platform/deploy/fabric_deploy.py --delete-after   # deploy then remove
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

FABRIC = "https://api.fabric.microsoft.com/v1"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "AIFinOps.SemanticModel", "data")
NB_DIR = os.path.join(REPO_ROOT, "platform", "medallion")

WORKSPACE_NAME = os.environ.get("FINOPS_WORKSPACE", "AI FinOps Accelerator")
LAKEHOUSE_NAME = os.environ.get("FINOPS_LAKEHOUSE", "finops_lakehouse")

NOTEBOOKS = [
    ("01_bronze_ingest", os.path.join(NB_DIR, "bronze", "01_ingest_foundry_apim.py")),
    ("02_bronze_copilot", os.path.join(NB_DIR, "bronze", "02_ingest_copilot_platforms.py")),
    ("10_silver_conform", os.path.join(NB_DIR, "silver", "10_conform_usage.py")),
    ("20_gold_star", os.path.join(NB_DIR, "gold", "20_build_star.py")),
]


# --------------------------------------------------------------------------- auth
def az_token(resource):
    try:
        out = subprocess.check_output(
            ["az", "account", "get-access-token", "--resource", resource,
             "--query", "accessToken", "-o", "tsv"],
            stderr=subprocess.PIPE)
        return out.decode().strip()
    except FileNotFoundError:
        die("Azure CLI (`az`) not found. Install it and run `az login`.")
    except subprocess.CalledProcessError as e:
        die("`az` could not get a token. Run `az login` first.\n" + e.stderr.decode())


def die(msg, code=1):
    print("\nERROR: " + msg, file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- http
def _req(method, url, token, body=None, ctype="application/json", raw=False):
    data = None
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        if raw:
            data = body if isinstance(body, bytes) else body.encode()
            if ctype:
                headers["Content-Type"] = ctype
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(r)
        payload = resp.read()
        # Fabric long-running ops return 202 + Operation-Location header
        loc = resp.headers.get("Location") or resp.headers.get("Operation-Location")
        return resp.status, (json.loads(payload) if payload and not raw else payload), loc
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="replace")
        return e.code, body_txt, None


def fab(method, path, token, body=None):
    return _req(method, FABRIC + path, token, body)


def poll_lro(loc, token, label, timeout=1800):
    """Poll a Fabric long-running operation URL until it succeeds/fails."""
    if not loc:
        return
    start = time.time()
    while time.time() - start < timeout:
        status, payload, _ = _req("GET", loc, token)
        state = (payload or {}).get("status") if isinstance(payload, dict) else None
        if state in ("Succeeded", "Completed"):
            return payload
        if state in ("Failed", "Cancelled"):
            die("%s failed: %s" % (label, json.dumps(payload)))
        time.sleep(5)
    die("%s timed out after %ss" % (label, timeout))


# --------------------------------------------------------------------------- steps
def step_preflight():
    print("• preflight: getting Fabric token via az ...")
    token = az_token("https://api.fabric.microsoft.com")
    status, payload, _ = fab("GET", "/workspaces", token)
    if status == 200:
        print("  ✓ licensed — Fabric REST reachable (%d workspaces visible)"
              % len(payload.get("value", [])))
        return token
    if isinstance(payload, str) and "UserNotLicensed" in payload:
        die("You are signed in but have NO Power BI/Fabric license, so the "
            "Fabric REST API rejects every call (UserNotLicensed).\n\n"
            "Fix it with 2 one-time browser steps (see platform/deploy/README.md):\n"
            "  1. Go to https://app.fabric.microsoft.com and sign in — this "
            "self-service-provisions a free Power BI license for your user.\n"
            "  2. In the Fabric portal: Account manager ▸ 'Start trial' (Fabric "
            "60-day trial, ~F64, $0), OR have an admin assign an F-SKU capacity.\n\n"
            "Then re-run this script. Nothing here charges your account until a "
            "paid capacity runs — the Trial is free.")
    die("Unexpected Fabric response (%s): %s" % (status, payload))


def step_capacity(token):
    print("• capacity: looking for a usable capacity ...")
    status, payload, _ = fab("GET", "/capacities", token)
    if status != 200:
        die("Could not list capacities: %s" % payload)
    caps = payload.get("value", [])
    active = [c for c in caps if c.get("state", "").lower() == "active"]
    for c in active:
        sku = c.get("sku", "?")
        print("  found capacity: %s (sku=%s, id=%s)" % (c.get("displayName"), sku, c.get("id")))
    if not active:
        die("No ACTIVE capacity found. Start the Fabric Trial (free) from the "
            "portal Account manager, or create/assign an F-SKU. Re-run after.")
    # Prefer a Trial capacity if present, else first active.
    trial = [c for c in active if "trial" in (c.get("sku", "") + c.get("displayName", "")).lower()]
    chosen = (trial or active)[0]
    print("  ✓ using capacity: %s (id=%s)" % (chosen.get("displayName"), chosen["id"]))
    return chosen["id"]


def _find_item(token, ws_id, kind, name):
    status, payload, _ = fab("GET", "/workspaces/%s/items?type=%s" % (ws_id, kind), token)
    if status == 200:
        for it in payload.get("value", []):
            if it.get("displayName") == name:
                return it["id"]
    return None


def step_workspace(token, capacity_id):
    print("• workspace: ensuring '%s' ..." % WORKSPACE_NAME)
    status, payload, _ = fab("GET", "/workspaces", token)
    for ws in payload.get("value", []):
        if ws.get("displayName") == WORKSPACE_NAME:
            print("  ✓ reusing workspace id=%s" % ws["id"])
            ws_id = ws["id"]
            break
    else:
        status, payload, loc = fab("POST", "/workspaces", token,
                                   {"displayName": WORKSPACE_NAME})
        if status not in (200, 201):
            die("Create workspace failed: %s" % payload)
        ws_id = payload["id"]
        print("  ✓ created workspace id=%s" % ws_id)
    # assign to capacity (idempotent)
    status, payload, _ = fab("POST", "/workspaces/%s/assignToCapacity" % ws_id, token,
                             {"capacityId": capacity_id})
    if status in (200, 202):
        print("  ✓ assigned to capacity")
    return ws_id


def step_lakehouse(token, ws_id):
    print("• lakehouse: ensuring '%s' ..." % LAKEHOUSE_NAME)
    lh_id = _find_item(token, ws_id, "Lakehouse", LAKEHOUSE_NAME)
    if lh_id:
        print("  ✓ reusing lakehouse id=%s" % lh_id)
        return lh_id
    status, payload, loc = fab("POST", "/workspaces/%s/lakehouses" % ws_id, token,
                               {"displayName": LAKEHOUSE_NAME})
    if status == 202:
        payload = poll_lro(loc, token, "create lakehouse")
    if status not in (200, 201, 202):
        die("Create lakehouse failed: %s" % payload)
    lh_id = _find_item(token, ws_id, "Lakehouse", LAKEHOUSE_NAME)
    print("  ✓ created lakehouse id=%s" % lh_id)
    return lh_id


def step_upload(ws_id, lh_id):
    print("• upload: pushing data/*.csv to Files/bronze via OneLake ...")
    st = az_token("https://storage.azure.com")
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".csv"))
    base = "%s/%s/%s.Lakehouse/Files/bronze" % (ONELAKE, ws_id, lh_id)
    for f in files:
        with open(os.path.join(DATA_DIR, f), "rb") as fh:
            content = fh.read()
        url = "%s/%s" % (base, f)
        # ADLS Gen2: create file, append bytes, flush.
        s1, _, _ = _req("PUT", url + "?resource=file", st, b"", None, raw=True)
        s2, _, _ = _req("PATCH", url + "?action=append&position=0", st,
                        content, "application/octet-stream", raw=True)
        s3, _, _ = _req("PATCH", "%s?action=flush&position=%d" % (url, len(content)),
                        st, b"", None, raw=True)
        ok = s1 in (200, 201) and s2 in (200, 202) and s3 in (200)
        print("  %s %s (%d bytes) [%s/%s/%s]" %
              ("✓" if ok else "✗", f, len(content), s1, s2, s3))


def _py_to_ipynb(path):
    """Wrap a .py medallion script as a single-cell Fabric notebook (ipynb)."""
    with open(path) as fh:
        src = fh.read()
    nb = {
        "cells": [{"cell_type": "code", "source": src.splitlines(keepends=True),
                   "metadata": {}, "outputs": [], "execution_count": None}],
        "metadata": {"language_info": {"name": "python"},
                     "kernelspec": {"name": "synapse_pyspark", "language": "Python",
                                    "display_name": "Synapse PySpark"}},
        "nbformat": 4, "nbformat_minor": 5,
    }
    return json.dumps(nb).encode()


def step_notebooks(token, ws_id, lh_id):
    print("• notebooks: importing medallion notebooks ...")
    ids = {}
    for name, path in NOTEBOOKS:
        existing = _find_item(token, ws_id, "Notebook", name)
        if existing:
            print("  ✓ reusing notebook %s" % name)
            ids[name] = existing
            continue
        payload64 = base64.b64encode(_py_to_ipynb(path)).decode()
        body = {"displayName": name, "definition": {
            "format": "ipynb",
            "parts": [{"path": "notebook-content.ipynb", "payload": payload64,
                       "payloadType": "InlineBase64"}]}}
        status, resp, loc = fab("POST", "/workspaces/%s/notebooks" % ws_id, token, body)
        if status == 202:
            poll_lro(loc, token, "import " + name)
        elif status not in (200, 201):
            die("Import notebook %s failed: %s" % (name, resp))
        ids[name] = _find_item(token, ws_id, "Notebook", name)
        print("  ✓ imported notebook %s" % name)
    return ids


def step_run(token, ws_id, nb_ids):
    print("• run: executing bronze -> silver -> gold ...")
    for name, _ in NOTEBOOKS:
        nb_id = nb_ids.get(name)
        if not nb_id:
            die("notebook %s not found; run 'notebooks' step first" % name)
        url = "/workspaces/%s/items/%s/jobs/instances?jobType=RunNotebook" % (ws_id, nb_id)
        status, resp, loc = fab("POST", url, token, {})
        if status not in (200, 201, 202):
            die("Run %s failed: %s" % (name, resp))
        print("  ▶ %s submitted" % name)
        poll_lro(loc, token, "run " + name)
        print("  ✓ %s completed" % name)


def step_teardown(token, ws_id):
    print("• teardown: deleting workspace %s ..." % ws_id)
    status, resp, _ = fab("DELETE", "/workspaces/%s" % ws_id, token)
    if status in (200, 202, 204):
        print("  ✓ workspace deleted — $0 residual compute")
    else:
        print("  ✗ delete returned %s: %s" % (status, resp))


# --------------------------------------------------------------------------- main
ALL_STEPS = ["preflight", "capacity", "workspace", "lakehouse",
             "upload", "notebooks", "run"]


def main():
    ap = argparse.ArgumentParser(description="Deploy AI FinOps accelerator to Fabric")
    ap.add_argument("--steps", nargs="+", default=ALL_STEPS,
                    help="subset of: %s (default: all)" % " ".join(ALL_STEPS))
    ap.add_argument("--delete-after", action="store_true",
                    help="delete the workspace after a successful run ($0 residual)")
    args = ap.parse_args()

    token = step_preflight()
    if args.steps == ["preflight"]:
        print("\npreflight OK — you are licensed and ready to deploy.")
        return

    capacity_id = step_capacity(token) if "capacity" in args.steps else None
    ws_id = step_workspace(token, capacity_id) if "workspace" in args.steps else None
    lh_id = step_lakehouse(token, ws_id) if "lakehouse" in args.steps else None
    if "upload" in args.steps:
        step_upload(ws_id, lh_id)
    nb_ids = step_notebooks(token, ws_id, lh_id) if "notebooks" in args.steps else {}
    if "run" in args.steps:
        step_run(token, ws_id, nb_ids)

    print("\n✓ Fabric deploy complete.")
    print("  Next: publish the semantic model + report — either")
    print("   (a) connect this repo via Fabric Git integration, or")
    print("   (b) open AIFinOps.pbip in Power BI Desktop and Publish to '%s'."
          % WORKSPACE_NAME)
    if args.delete_after:
        step_teardown(token, ws_id)


if __name__ == "__main__":
    main()
