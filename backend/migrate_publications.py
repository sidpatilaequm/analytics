import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

conn = mysql.connector.connect(
    host=os.environ.get("META_DB_HOST", "localhost"),
    port=int(os.environ.get("META_DB_PORT", 3306)),
    user=os.environ.get("META_DB_USER", "nexd_designer"),
    password=os.environ.get("META_DB_PASSWORD", ""),
    database=os.environ.get("META_DB_NAME", "nexd_designer"),
)

cursor = conn.cursor()

cursor.execute("""
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'process_publications'
      AND COLUMN_NAME = 'role'
""")

exists = cursor.fetchone()[0]

if exists:
    print("Migration skipped: 'role' column already exists.")
else:
    cursor.execute("""
        ALTER TABLE process_publications
        ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT ''
    """)
    conn.commit()
    print("Migration successful: 'role' column added.")

cursor.close()
conn.close()