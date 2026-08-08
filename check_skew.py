import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT ts, skew_ms, uncertainty_ms, rtt_min_ms
    FROM clock_skew
    ORDER BY id DESC
    LIMIT 15
"""
for row in conn.execute(query):
    print(row)