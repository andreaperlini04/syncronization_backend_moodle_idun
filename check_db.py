import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT ts, event_type, description
    FROM timeline
    WHERE source = 'moodle'
    ORDER BY id DESC
    LIMIT 30
"""
for row in conn.execute(query):
    print(row)