import subprocess
result = subprocess.run(
    ["sudo", "docker", "exec", "-i", "mas-unisync-postgres-1", "psql", "-U", "mas_unisync", "-d", "mas_unisync"],
    input=b"UPDATE persistent_versions SET renpy_version = NULL WHERE renpy_version IS NOT NULL AND renpy_version LIKE '<%';\nUPDATE persistent_versions SET mas_version = NULL WHERE mas_version IS NOT NULL AND mas_version LIKE '<%';\n",
    capture_output=True
)
print(result.stdout.decode())
