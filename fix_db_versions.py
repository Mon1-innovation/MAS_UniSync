import sqlite3
conn = sqlite3.connect(r"E:\GithubKu\MAS_UniSync\data\mas_unisync.db")
c = conn.cursor()

# Check before
c.execute("SELECT id,profile_id,renpy_version,mas_version FROM persistent_versions WHERE renpy_version LIKE '<%' OR mas_version LIKE '<%'")
rows = c.fetchall()
print("Corrupted rows:", len(rows))
for row in rows:
    print(row)

# Fix
c.execute("UPDATE persistent_versions SET renpy_version=NULL WHERE renpy_version LIKE '<%'")
r1 = c.rowcount
c.execute("UPDATE persistent_versions SET mas_version=NULL WHERE mas_version LIKE '<%'")
r2 = c.rowcount
conn.commit()
print(f"Fixed: {r1} renpy_version, {r2} mas_version")

# Verify
c.execute("SELECT id,profile_id,renpy_version,mas_version FROM persistent_versions WHERE renpy_version LIKE '<%' OR mas_version LIKE '<%'")
remaining = c.fetchall()
print("Remaining corrupted:", len(remaining))
conn.close()
