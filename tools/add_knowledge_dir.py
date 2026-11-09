"""Add one folder to KNOWLEDGE_DIRS in ~/.onboarding_bot.env, or the file ONBOARDING_BOT_ENV names (restart the bot
afterwards).

Usage:  <python> -I -X utf8 add_knowledge_dir.py "C:\\full\\path\\to\\folder"
Prints only the resulting folder list. Every other line of the env file (secrets) is kept byte for byte and never
printed; the file is replaced atomically. Refuses to change anything unless there is exactly one KNOWLEDGE_DIRS line."""
import os
import stat
import sys
from pathlib import Path

BOM = "\ufeff"

if len(sys.argv) != 2:
    sys.exit(__doc__)
new_dir = Path(sys.argv[1]).expanduser().resolve()
if not new_dir.is_dir() or any(c in str(new_dir) for c in ";=\r\n"):
    sys.exit(f"not a usable folder: {new_dir}; nothing changed")

env = Path(os.environ.get("ONBOARDING_BOT_ENV") or Path.home() / ".onboarding_bot.env").expanduser()
lines = env.read_bytes().decode("utf-8").splitlines(keepends=True)  # each line keeps its own ending, as the bot splits
hits = [i for i, line in enumerate(lines) if line.partition("=")[0].strip() in ("KNOWLEDGE_DIRS", BOM + "KNOWLEDGE_DIRS")]
if len(hits) != 1:
    sys.exit(f"found {len(hits)} KNOWLEDGE_DIRS lines, need exactly one; nothing changed")
line = lines[hits[0]]
if line.startswith(BOM):
    sys.exit("KNOWLEDGE_DIRS is the first line after a byte-order mark, which the bot does not read; move it; nothing changed")
body = line.rstrip("\r\n")
key, _, value = body.partition("=")
dirs = [d.strip().strip("\"'").strip() for d in value.strip().strip("\"'").split(";") if d.strip().strip("\"'").strip()]
if os.path.normcase(str(new_dir)) not in {os.path.normcase(str(Path(d))) for d in dirs}:
    dirs.append(str(new_dir))
lines[hits[0]] = key + "=" + ";".join(dirs) + line[len(body):]

tmp = env.with_name(env.name + ".tmp")
tmp.write_bytes("".join(lines).encode("utf-8"))
if os.name == "nt":  # ReplaceFileW keeps the env file's own access rights (ACL); os.replace would not
    import ctypes
    if not ctypes.windll.kernel32.ReplaceFileW(str(env), str(tmp), None, 0, None, None):
        error = ctypes.WinError()
        tmp.unlink(missing_ok=True)
        raise error
else:
    os.chmod(tmp, stat.S_IMODE(env.stat().st_mode))  # keep the env file's permissions (600)
    os.replace(tmp, env)
print("KNOWLEDGE_DIRS now lists:", *dirs, sep="\n  ")
