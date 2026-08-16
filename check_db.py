import sqlite3

conn = sqlite3.connect("sessions/timeline.db")
query = """
    SELECT event_type, COUNT(*) FROM timeline
WHERE ts > 1786868595.987
GROUP BY event_type;
"""
for row in conn.execute(query):
    print(row)
    