"""Live check of the bot: your handbook + your notes + real Claude calls, with usage, cost and latency. Costs money:
about $1.3 for the first question with a ~250k-token prompt, a few cents for each next one within 5 minutes (far less
with the small example notes). No Slack connection is made.

Run with the bot's venv, from the repository root:
    .venv/bin/python -X utf8 tools/test_live.py onboarding_bot.py ["question" ...]
The bot reads its settings and keys as usual (~/.onboarding_bot.env or ONBOARDING_BOT_ENV; real env vars win)."""
import importlib.util
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("bot", Path(sys.argv[1]).resolve())
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

last = {}
create = bot.claude.beta.messages.create


def recording_create(**kw):
    r = create(**kw)
    last["usage"], last["model"], last["stop"] = r.usage, r.model, r.stop_reason
    return r


bot.claude.beta.messages.create = recording_create

QUESTIONS = sys.argv[2:] or [  # questions for the example notes; pass your own lab's questions as arguments
    "How much vacation time do I get?",
    "I bought pipette tips with the P-card. Where do I send the receipt, and by when? Please draft the email.",
    "What per diem do I get on the first day of a conference trip?",
    "P-card로 600달러짜리 장비를 사도 돼?",
    "Can I borrow the lab manager's P-card number to order pizza?",
]
total = 0.0
for q in QUESTIONS:
    t0 = time.time()
    a = bot.answer(q)
    dt = time.time() - t0
    u = last["usage"]
    cost = (u.cache_creation_input_tokens * 5.0 + u.cache_read_input_tokens * 0.20 + u.input_tokens * 4.0
            + u.output_tokens * 20.0) / 1e6  # claude-opus-5-5 prices per MTok; update them if MODEL changes
    total += cost
    print(f"\n=== Q: {q}\n--- {dt:.1f}s | cache write {u.cache_creation_input_tokens} | cache read {u.cache_read_input_tokens} "
          f"| uncached in {u.input_tokens} | out {u.output_tokens} | {last['model']} {last['stop']} | ~${cost:.3f}\n{a}")
print(f"\nTOTAL ~${total:.2f}")
