#!/usr/bin/env python3
"""
Load the MOCK Bronze CSVs into a Fabric Lakehouse (Bronze layer).

Pipeline (pure REST, no external deps):
  1. Create/find Lakehouse 'bronze_finops' in the workspace.
  2. Upload each platform/fabric/bronze_out/*.csv to OneLake  Files/bronze/<name>.csv
     via the ADLS Gen2 (OneLake DFS) API.
  3. Promote each file to a managed Delta table via the Lakehouse 'Load Table' API.

PREREQUISITE (the current blocker): the signed-in user (or a service principal
added to the workspace) MUST hold a Power BI / Fabric license. Without it every
write returns HTTP 401 'UserNotLicensed'. The tenant already has POWER_BI_STANDARD
(Power BI Free) SKUs available — an admin just needs to assign one to the user.

Run (once licensed):
  az login
  python3 platform/fabric/load_bronze.py --workspace davidshreyasalison
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BRONZE_DIR = os.path.join(HERE, "bronze_out")
FABRIC_RES = "https://api.fabric.microsoft.com"
STORAGE_RES = "https://storage.azure.com"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"


def token(resource):
    out = subprocess.run(
        ["az", "account", "get-access-token", "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"token failed for {resource}: {out.stderr.strip()}")
    return out.stdout.strip()


def req(method, url, tok, data=None, ctype="application/json", raw=False):
    headers = {"Authorization": f"Bearer {tok}"}
    if ctype:
        headers["Content-Type"] = ctype
    r = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r) as resp:
            body = resp.read()
            return resp.status, (body if raw else (json.loads(body) if body else {}))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def find_workspace(tok, name):
    st, body = req("GET", f"{FABRIC_RES}/v1/workspaces", tok)
    if st == 401:
        sys.exit("HTTP 401 UserNotLicensed — assign the user a Power BI license first "
                 "(tenant has POWER_BI_STANDARD available). See module docstring.")
    if st != 200:
        sys.exit(f"list workspaces failed: {st} {body}")
    for w in body["value"]:
        if name in (w.get("displayName"), w.get("id")):
            return w["id"], w["displayName"]
    sys.exit(f"workspace '{name}' not found")


def ensure_lakehouse(tok, ws_id, name):
    st, body = req("GET", f"{FABRIC_RES}/v1/workspaces/{ws_id}/lakehouses", tok)
    if st == 200:
        for lh in body["value"]:
            if lh["displayName"] == name:
                print(f"  = lakehouse '{name}' exists ({lh['id']})")
                return lh["id"]
    st, body = req("POST", f"{FABRIC_RES}/v1/workspaces/{ws_id}/lakehouses", tok,
                   data=json.dumps({"displayName": name,
                                    "description": "AI FinOps Bronze (MOCK)"}).encode())
    if st in (200, 201):
        print(f"  + created lakehouse '{name}' ({body['id']})")
        return body["id"]
    if st == 202:  # long-running
        loc = None
        time.sleep(5)
        st, body = req("GET", f"{FABRIC_RES}/v1/workspaces/{ws_id}/lakehouses", tok)
        for lh in body.get("value", []):
            if lh["displayName"] == name:
                return lh["id"]
    sys.exit(f"create lakehouse failed: {st} {body}")


def upload_onelake(stok, ws_name, lh_name, local_path, rel_path):
    """ADLS Gen2 3-step: create -> append -> flush."""
    base = f"{ONELAKE}/{ws_name}/{lh_name}.Lakehouse/{rel_path}"
    with open(local_path, "rb") as fh:
        data = fh.read()
    # create (empty file)
    st, _ = req("PUT", base + "?resource=file", stok, data=b"", ctype=None, raw=True)
    if st not in (201, 202):
        return st
    # append
    st, _ = req("PATCH", base + "?action=append&position=0", stok, data=data,
                ctype="application/octet-stream", raw=True)
    if st not in (200, 202):
        return st
    # flush
    st, _ = req("PATCH", base + f"?action=flush&position={len(data)}", stok,
                ctype=None, raw=True)
    return st


def load_table(tok, ws_id, lh_id, table, rel_path):
    url = (f"{FABRIC_RES}/v1/workspaces/{ws_id}/lakehouses/{lh_id}"
           f"/tables/{table}/load")
    body = {"relativePath": rel_path, "pathType": "File", "format": "Csv",
            "formatOptions": {"header": True, "delimiter": ","}, "mode": "Overwrite",
            "recursive": False}
    st, resp = req("POST", url, tok, data=json.dumps(body).encode())
    return st, resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="davidshreyasalison")
    ap.add_argument("--lakehouse", default="bronze_finops")
    args = ap.parse_args()

    ftok = token(FABRIC_RES)
    stok = token(STORAGE_RES)

    ws_id, ws_name = find_workspace(ftok, args.workspace)
    print(f"Workspace: {ws_name} ({ws_id})")
    lh_id = ensure_lakehouse(ftok, ws_id, args.lakehouse)

    csvs = sorted(glob.glob(os.path.join(BRONZE_DIR, "*.csv")))
    if not csvs:
        sys.exit(f"no CSVs in {BRONZE_DIR}; run gen_bronze_data.py first")
    print(f"\nUploading {len(csvs)} Bronze files to OneLake + loading Delta tables:")
    for path in csvs:
        table = os.path.splitext(os.path.basename(path))[0]
        rel = f"Files/bronze/{table}.csv"
        st = upload_onelake(stok, ws_name, args.lakehouse, path, rel)
        if st not in (200, 201, 202):
            print(f"  ! {table}: upload HTTP {st}")
            continue
        lst, resp = load_table(ftok, ws_id, lh_id, table, rel)
        ok = "ok" if lst in (200, 201, 202) else f"HTTP {lst}"
        print(f"  {'+' if lst in (200,201,202) else '!'} {table}: uploaded + load {ok}")

    print("\nDone. Open the Lakehouse in Fabric -> Tables to see the Bronze layer.")


if __name__ == "__main__":
    main()
