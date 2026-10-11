# -*- coding: utf-8 -*-
"""环境自检：FTS5 trigram 中文检索 / pywin32 Word COM"""
import sqlite3, sys

con = sqlite3.connect(":memory:")
ver = sqlite3.sqlite_version
print("sqlite:", ver)
try:
    con.execute("CREATE VIRTUAL TABLE t USING fts5(body, tokenize='trigram')")
    con.execute("INSERT INTO t VALUES ('临边防护栏杆的上杆距地高度应为1.2m')")
    rows = con.execute("SELECT body FROM t WHERE t MATCH '防护栏杆'").fetchall()
    print("trigram CJK search ok:", rows)
    rows2 = con.execute("SELECT body FROM t WHERE t MATCH '栏杆高度'").fetchall()
    print("trigram cross-word ok:", len(rows2), "hits")
except Exception as e:
    print("trigram FAIL:", e)

try:
    import win32com.client  # noqa
    print("pywin32 import ok")
except Exception as e:
    print("pywin32 FAIL:", e)
