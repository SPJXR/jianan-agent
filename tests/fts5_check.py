import sqlite3
con = sqlite3.connect(":memory:")
try:
    con.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
    print("FTS5: AVAILABLE, sqlite", sqlite3.sqlite_version)
except Exception as e:
    print("FTS5: NOT AVAILABLE:", e)
try:
    con.enable_load_extension(True)
    print("loadable_extension: AVAILABLE")
except Exception as e:
    print("loadable_extension:", e)
