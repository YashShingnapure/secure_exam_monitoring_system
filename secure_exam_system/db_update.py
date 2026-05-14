import sqlite3

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

cursor.execute("ALTER TABLE papers ADD COLUMN paper_name TEXT")

conn.commit()
conn.close()

print("Database updated successfully")
