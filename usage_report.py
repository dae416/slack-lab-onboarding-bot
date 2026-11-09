"""Print what the onboarding bot has cost, from Anthropic's own billing data (Usage & Cost Admin API).

Run:   .venv\\Scripts\\python usage_report.py            # last 30 days
       .venv\\Scripts\\python usage_report.py --days 7
Keys:  reads ANTHROPIC_ADMIN_KEY (an Admin API key from an organization admin) or else ANTHROPIC_API_KEY, plus
       ANTHROPIC_WORKSPACE_ID, from ~/.onboarding_bot.env (same file as the bot; or the
       file ONBOARDING_BOT_ENV names).
Note:  the remaining prepaid credit balance is NOT exposed by any API; see https://platform.claude.com/settings/billing
       These report endpoints need an Admin API key; an ordinary API key gets HTTP 403 (no organization permission).
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENV_FILE = Path(os.environ.get("ONBOARDING_BOT_ENV") or Path.home() / ".onboarding_bot.env").expanduser()
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

API_KEY = os.environ.get("ANTHROPIC_ADMIN_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")
WORKSPACE = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
BASE = "https://api.anthropic.com/v1/organizations/"
BILLING_URL = "https://platform.claude.com/settings/billing"

days = 30
if "--days" in sys.argv:
    days = max(1, min(31, int(sys.argv[sys.argv.index("--days") + 1])))


def get(path: str, params: dict, with_workspace: bool = False) -> dict:
    req = urllib.request.Request(BASE + path + "?" + urllib.parse.urlencode(params, doseq=True))
    req.add_header("x-api-key", API_KEY)
    req.add_header("anthropic-version", "2023-06-01")
    if with_workspace and WORKSPACE:
        req.add_header("anthropic-workspace-id", WORKSPACE)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if not with_workspace and "workspace" in body.lower() and e.code == 400:
            return get(path, params, with_workspace=True)  # identity-linked keys must name the workspace
        if e.code in (401, 403):
            sys.exit(f"HTTP {e.code}: this API key may not read organization reports.\n{body}\n"
                     f"Use the Console instead: usage https://platform.claude.com/usage, cost https://platform.claude.com/cost, "
                     f"balance {BILLING_URL}")
        sys.exit(f"HTTP {e.code}: {body}")


if not API_KEY:
    sys.exit(f"ANTHROPIC_API_KEY not found in {ENV_FILE}")

now = datetime.now(timezone.utc)
start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
window = {"starting_at": start.isoformat().replace("+00:00", "Z"), "ending_at": now.isoformat().replace("+00:00", "Z"),
          "bucket_width": "1d", "limit": 31}

# 1) Cost in USD per day: the bot's workspace vs the whole organization
cost = get("cost_report", {**window, "group_by[]": ["workspace_id"]})
bot_by_day, org_by_day = defaultdict(float), defaultdict(float)
for bucket in cost["data"]:
    day = bucket["starting_at"][:10]
    for item in bucket["results"]:
        dollars = float(item["amount"]) / 100  # amount is in cents
        org_by_day[day] += dollars
        if item.get("workspace_id") == WORKSPACE:
            bot_by_day[day] += dollars

print(f"Cost (USD) from Anthropic billing data, last {days} days, UTC days. Bot workspace = {WORKSPACE or '(none)'}")
print(f"  {'day':10}  {'bot workspace':>13}  {'whole org':>10}")
for day in sorted(org_by_day):
    if org_by_day[day] or bot_by_day[day]:
        print(f"  {day:10}  {bot_by_day[day]:>13.4f}  {org_by_day[day]:>10.4f}")
print(f"  {'total':10}  {sum(bot_by_day.values()):>13.4f}  {sum(org_by_day.values()):>10.4f}")

# 2) Tokens by model for the bot's workspace (shows whether prompt caching is working)
usage = get("usage_report/messages", {**window, "group_by[]": ["model"], **({"workspace_ids[]": [WORKSPACE]} if WORKSPACE else {})})
tok = defaultdict(lambda: defaultdict(int))
for bucket in usage["data"]:
    for item in bucket["results"]:
        t = tok[item.get("model") or "?"]
        t["uncached_in"] += item["uncached_input_tokens"]
        t["cache_write"] += item["cache_creation"]["ephemeral_5m_input_tokens"] + item["cache_creation"]["ephemeral_1h_input_tokens"]
        t["cache_read"] += item["cache_read_input_tokens"]
        t["output"] += item["output_tokens"]
print(f"\nTokens in the bot workspace, last {days} days:")
print(f"  {'model':22} {'uncached in':>12} {'cache write':>12} {'cache read':>12} {'output':>10}")
for model, t in sorted(tok.items()):
    print(f"  {model:22} {t['uncached_in']:>12,} {t['cache_write']:>12,} {t['cache_read']:>12,} {t['output']:>10,}")
if not tok:
    print("  (no usage in this period)")

print(f"\nRemaining prepaid balance: not available through the API. See {BILLING_URL}")
