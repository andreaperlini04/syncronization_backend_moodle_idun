import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT description
    FROM timeline
    ORDER BY ts DESC
    LIMIT 30
"""
for row in conn.execute(query):
    print(row)