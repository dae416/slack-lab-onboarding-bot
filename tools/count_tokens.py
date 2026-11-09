"""Token count (free count_tokens endpoint) for the handbook plus every knowledge file, per file and in total.
Usage: python count_tokens.py HANDBOOK_TXT DIR [DIR ...]   (never prints the API key)
HANDBOOK_TXT: the handbook as text, e.g. onboarding_cache.txt (written when DOC_URL is set) or examples/handbook.md.
Reads the API key from ~/.onboarding_bot.env (or the file ONBOARDING_BOT_ENV names); real env vars win."""
import os
import sys
from pathlib import Path

import anthropic

ENV_FILE = Path(os.environ.get("ONBOARDING_BOT_ENV") or Path.home() / ".onboarding_bot.env").expanduser()
for line in (ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else "").splitlines():
    key, _, value = line.partition("=")
    if key.strip() and value.strip() and not key.startswith("#"):
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
ws = os.environ.get("ANTHROPIC_WORKSPACE_ID")
client = anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)
MODEL = "claude-opus-5-5"  # keep equal to MODEL in onboarding_bot.py


def count(text: str) -> int:
    r = client.messages.count_tokens(model=MODEL, system=[{"type": "text", "text": text}],
                                     messages=[{"role": "user", "content": "hi"}])
    return r.input_tokens


base = count("x")
handbook = Path(sys.argv[1]).read_text(encoding="utf-8")
total_text, rows = [handbook], [(f"handbook ({Path(sys.argv[1]).name})", len(handbook), count(handbook) - base)]
for d in sys.argv[2:]:
    for f in sorted(Path(d).glob("*")):
        if f.suffix.lower() in (".md", ".txt"):
            t = f.read_text(encoding="utf-8-sig")
            total_text.append(t)
            rows.append((f"{Path(d).name}/{f.name}", len(t), count(t) - base))
for name, chars, toks in rows:
    print(f"{toks:7d} tok {chars:8d} chars  {name}")
all_tokens = count("\n\n".join(total_text)) - base
print(f"TOTAL {all_tokens} tokens, {sum(r[1] for r in rows)} chars")
w, r = 6.25, 0.50  # claude-opus-5 $/MTok: 5-minute cache write (1.25x of $5), cache read (0.1x)
print(f"claude-opus-5 per question: cold (cache write) ${all_tokens * w / 1e6:.2f}, warm (cache read) ${all_tokens * r / 1e6:.3f}")
print(f"claude-opus-5-5 per question: cold ${all_tokens * 5.0 / 1e6:.2f}, warm ${all_tokens * 0.20 / 1e6:.3f}")
