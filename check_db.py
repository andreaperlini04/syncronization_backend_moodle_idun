import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT *
    FROM timeline
    ORDER BY ts DESC
    LIMIT 170
"""
for row in conn.execute(query):
    print(row)