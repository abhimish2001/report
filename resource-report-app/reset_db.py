import sqlite3
import os
import shutil

base_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(base_dir, "data", "reports.db")

print(f"Clearing database: {db_path}...")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

tables = ["uploads", "tasks", "normalization_log", "reports"]
for t in tables:
    cursor.execute(f"DELETE FROM {t}")
    try:
        cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{t}'")
    except sqlite3.OperationalError:
        pass

conn.commit()
conn.execute("VACUUM")

print("\n--- Verifying Row Counts ---")
for t in tables:
    cursor.execute(f"SELECT count(*) FROM {t}")
    print(f"{t}: {cursor.fetchone()[0]} rows")

conn.close()

# Clean temporary upload files
tmp_dir = os.path.join(base_dir, "data", "tmp_uploads")
if os.path.exists(tmp_dir):
    shutil.rmtree(tmp_dir)
os.makedirs(tmp_dir, exist_ok=True)
print("Cleared data/tmp_uploads/ folder.")

# Clean output folder
out_dir = os.path.join(base_dir, "output")
if os.path.exists(out_dir):
    for fname in os.listdir(out_dir):
        fpath = os.path.join(out_dir, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
print("Cleared output/ folder.")
print("\nDATABASE AND OUTPUT FOLDERS ARE NOW COMPLETELY AT ZERO!")
