# Maintenance tools

None of these is needed to run the bot. Run them with the bot's venv from the repository root. On Windows add
`-X utf8` (with `-I`, `PYTHONUTF8` is ignored and non-ASCII output can fail on the console).

| Script | What it does |
|---|---|
| `test_offline.py` | 312 offline checks of the bot (no Slack, no Claude call, no network), against `examples/`: knowledge folders, limits, the system prompt, conversation memory, learning (the remember and forget tools, `remember:`, approvals, removal requests, channel posts, profiles, conversation deletion) and files, with fake Slack and Claude clients. `python -I -B -X utf8 tools/test_offline.py [path/to/onboarding_bot.py]`. Expect `ALL PASS`. It ignores your env file and sets its own fictional settings. |
| `test_live.py` | Real questions through the bot code with usage, cost and latency (real Claude calls; no Slack): `python -X utf8 tools/test_live.py onboarding_bot.py "question" ...`. Without questions it asks five about the example notes. |
| `check_notes.py` | Gate before notes go live: loads folders with the bot's own loader (counts, the `MAX_NOTES_CHARS` limit) and scans every line for secret-looking text (in `_Learned` also with the bot's own patterns, `bot-rule`). Exit code 1 on a problem. `python -I -B -X utf8 tools/check_notes.py onboarding_bot.py DIR [DIR ...]`; `--hash FILE:LINE` prints an allowlist entry. Flagged lines are reported by file, line and rule only, never their text. |
| `secret_allowlist.txt` | SHA-256 hashes of owner-approved lines the scan would flag (never the values), one file each. |
| `count_tokens.py` | Token count of the handbook plus all notes, per file and in total, with the cost per question (free `count_tokens` endpoint; reads the API key from the env file and never prints it): `python tools/count_tokens.py HANDBOOK.txt DIR [DIR ...]`. Update its model and prices if `MODEL` changes. |
| `add_knowledge_dir.py` | Adds a folder to `KNOWLEDGE_DIRS` in the env file, printing only that line (secrets are kept byte for byte and never printed): `python -I -X utf8 tools/add_knowledge_dir.py "/full/path/to/folder"`. Restart the bot afterwards. |
| `snap.py` | Saves public web pages (university rules, finance and travel pages) as a Markdown note: `python tools/snap.py OUT.md URL [URL ...]`, or `--links URL` to list a page's body links. Downloads are cached in `tools/raw/` (git-ignored). Needs `requests beautifulsoup4 markdownify html5lib` (a separate venv is fine). Add site rules (`BODY`) for your university's pages. |

`../usage_report.py` prints the bot's cost per day from Anthropic's Usage and Cost Admin API (needs
`ANTHROPIC_ADMIN_KEY`).
