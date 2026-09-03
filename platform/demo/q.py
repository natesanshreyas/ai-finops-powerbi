#!/usr/bin/env python3
"""Tiny sqlite3-CLI stand-in (the sqlite3 binary isn't always installed).

Usage:
    python3 platform/demo/q.py                         # interactive shell
    python3 platform/demo/q.py "SELECT * FROM fact_ai_usage"   # one query
    python3 platform/demo/q.py .tables                 # list tables
    python3 platform/demo/q.py ".schema fact_ai_usage" # show a table's schema
"""
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(__file__), "finops_demo.db")


def run(cur, sql):
    sql = sql.strip().rstrip(";")
    if not sql:
        return
    if sql == ".tables":
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        for (n,) in cur.fetchall():
            print(n)
        return
    if sql.startswith(".schema"):
        parts = sql.split()
        q = "SELECT sql FROM sqlite_master WHERE type='table'"
        if len(parts) > 1:
            q += " AND name='%s'" % parts[1]
        cur.execute(q)
        for (s,) in cur.fetchall():
            print((s or "") + ";")
        return
    cur.execute(sql)
    if cur.description is None:
        print("OK")
        return
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    w = [len(c) for c in cols]
    srows = [["" if v is None else str(v) for v in r] for r in rows]
    for sr in srows:
        w = [max(a, len(b)) for a, b in zip(w, sr)]
    bar = "+" + "+".join("-" * (x + 2) for x in w) + "+"
    print(bar)
    print("| " + " | ".join(c.ljust(x) for c, x in zip(cols, w)) + " |")
    print(bar)
    for sr in srows:
        print("| " + " | ".join(v.ljust(x) for v, x in zip(sr, w)) + " |")
    print(bar)
    print("(%d rows)" % len(rows))


def main():
    if not os.path.exists(DB):
        sys.exit("DB missing — run: python3 platform/demo/build_demo_db.py")
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    if len(sys.argv) > 1:
        run(cur, " ".join(sys.argv[1:]))
        return
    print("finops_demo.db — type SQL, .tables, .schema <t>, or .quit")
    while True:
        try:
            line = input("finops> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line in (".quit", ".exit", "quit", "exit"):
            break
        try:
            run(cur, line)
        except Exception as e:
            print("Error:", e)


if __name__ == "__main__":
    main()
