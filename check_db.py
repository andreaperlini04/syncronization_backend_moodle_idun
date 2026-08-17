import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT ts, description, user_id
    FROM timeline
    ORDER BY  ts DESC
    LIMIT 10
"""
for row in conn.execute(query):
    print(row)
    