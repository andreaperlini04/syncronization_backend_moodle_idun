import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT *
    FROM timeline
    ORDER BY id DESC
    LIMIT 10
"""
for row in conn.execute(query):
    print(row)