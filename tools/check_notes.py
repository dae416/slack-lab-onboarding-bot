"""Staging gate for the onboarding bot's reference notes (no Slack, no Claude call, no Google fetch).

Loads the given folders with the bot's own loader, reports what the bot would read, then scans every note line for text
that looks like a secret (in the bot's _Learned folder, facts taught in Slack, also with the bot's own wider rules,
reported as "bot-rule"). Run with the bot's venv:

    <bot venv python> -I -B -X utf8 check_notes.py <path to onboarding_bot.py> DIR [DIR ...]
    <bot venv python> -I -B -X utf8 check_notes.py --hash FILE:LINE    # allowlist entry for one line

Exit code 0: every note file loads, no folder is empty, the total is under MAX_NOTES_CHARS, and no unapproved
secret-looking line was found. Exit code 1: otherwise. Phone numbers are listed for review but do not fail the check.
Owner-approved lines (README.md, privacy rules) are allowlisted in secret_allowlist.txt next to this file as
"<SHA-256 of the stripped line>  <folder>/<file>  # why": the secret itself is never copied, and an entry approves that
line in that file only. Flagged lines are reported by file, line number and rule names only, never their text. Line
numbers are the editor's.
"""
import contextlib
import hashlib
import importlib.util
import io
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWLIST = HERE / "secret_allowlist.txt"

# Checked on the raw line, because these secrets sit inside links (on_ = an API key prefix).
RAW_SECRETS = [
    ("url", re.compile(r"(?i)[?&][\w-]*?(?:pwd|pass(?:word)?|token|key|sig|secret)=([^\s&>)|]+)|//[^/\s:@]+:([^\s/@]+)@|"
                       r"((?:hooks\.slack\.com/services|hc-ping\.com)/[^\s>|)]+)")),
    ("token", re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}|sk-ant-[A-Za-z0-9_-]{10,}|"
                         r"AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|on_[A-Za-z0-9]{16,})")),
]
# Checked after links and email addresses are blanked out (they carry long IDs that are not secrets).
LINKS = re.compile(r"<?https?://[^\s>|)\]]+|<mailto:[^>]+>|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SECRETS = [
    ("keyword", re.compile(r"(?i)\b(?:pass(?:word|wd|code|phrase)?s?|pw|pwd|pin|secret|api[ _-]?key|access[ _-]?key|"
                           r"secret[ _-]?key|token)\b\s{0,3}[:=]\s{0,3}(?!(?:ask|see|contact|your)\b)(\S+)")),
    ("keyword", re.compile(r"(?i)\b(?:pass(?:word|wd|code|phrase)?|pw|pwd|pin)\s+is\s+(?=\S*[\d!@#$%^&*])(\S+)")),
    ("keyword", re.compile(r"(?i)\b(?:secret|api|access)[ _-]?key\s+(\S{16,})")),
    ("phrase", re.compile(r"(?i)(?:\b(?:pass(?:word|code)?|pw|pwd|pin)\b|비밀번호|암호)\s*(?:is|[:=|])?\s*[`'\"]?"
                          r"((?=[^\s`'\"|]*\d)[^\s`'\"|]{4,})")),
    ("code", re.compile(r"(?i)\b(?:access|print(?:er|ing)?|copier|door|lock(?:box|er)?|key(?:pad)?|gate|alarm|pin)s?\b"
                        r"(?:\s+(?:pass)?(?:code|key|number)s?)?[^\n\d]{0,20}?(?<![\d/-])(\d{4,8})(?![\d/-])")),
    ("code", re.compile(r"(?i)\b(?:print(?:er|ing)?|door|lock(?:box|er)?|key(?:pad)?|gate|alarm|garage|copier|wi-?fi|"
                        r"access)\s+(?:code|combination|combo|pin)\b\D{0,12}?(\d[\d -]{2,10}\d)")),
    ("pair", re.compile(r"(?i)\b(?:login|user(?:name)?|account)\b[^\n/]{0,40}?\s/\s*(\S{6,})")),
    ("hex", re.compile(r"\b([0-9a-f]{32,})\b")),
    ("random", re.compile(r"(?<![\w/.-])((?=[\w+=-]*[a-z])(?=[\w+=-]*[A-Z])(?=[\w+=-]*\d)[\w+=-]{24,})(?![\w/-]|\.\w)")),
]
LABEL_ONLY = re.compile(r"(?i)\b(?:pass(?:word|wd|code)?|pw|pwd|pin|key|token)s?\s*:\s*$")  # value on the next line
PHONE = re.compile(r"(?<![\d-])(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}(?![\d-])")


def line_hash(line: str) -> str:
    return hashlib.sha256(line.strip().encode("utf-8")).hexdigest()


def note_lines(path: Path) -> list[str]:
    """The file's lines as an editor numbers them, decoded like onboarding_bot.read_note (UTF-16 or UTF-8)."""
    data = path.read_bytes()
    text = data.decode("utf-16") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def findings(lines: list[str], number: int) -> list[str]:
    """Names of the rules that flag line `number` (1-based) as a possible secret."""
    line = lines[number - 1]
    scan = LINKS.sub(lambda m: " " * len(m.group()), line)
    kinds = {name for name, rx in RAW_SECRETS if rx.search(line)} | {name for name, rx in SECRETS if rx.search(scan)}
    if number > 1 and LABEL_ONLY.search(LINKS.sub(" ", lines[number - 2])) and line.strip():
        kinds.add("next-line")
    return sorted(kinds)


def load_allowlist() -> dict[str, str]:
    """Hash -> "<folder>/<file>". An entry without a file name is ignored (it would approve the line in any file)."""
    entries = {}
    if ALLOWLIST.exists():
        for row in ALLOWLIST.read_text(encoding="utf-8-sig").splitlines():
            fields = row.split("#", 1)[0].split()
            if len(fields) >= 2:
                entries[fields[0]] = fields[1]
            elif fields:
                print(f"note allowlist entry {fields[0][:12]}... has no folder/file name and is ignored")
    return entries


def load_bot(bot_path: Path, dirs: list[Path]):
    os.environ["DOC_URL"] = ""  # real env vars win over the env file: onboarding.docx, no network
    os.environ["KNOWLEDGE_DIRS"] = os.pathsep.join(str(d) for d in dirs)
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        spec = importlib.util.spec_from_file_location("onboarding_bot_checked", bot_path)
        bot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bot)
    return bot, log.getvalue()


def note_files(bot, folder: Path) -> list[Path]:
    """The files the bot reads from `folder` (same rules as onboarding_bot.load_notes)."""
    return [f for f in sorted(folder.iterdir())
            if not f.is_symlink() and f.is_file() and f.suffix.lower() in bot.NOTE_TYPES
            and not f.name.startswith((".", "~")) and "conflicted copy" not in f.name]


def hash_entry(arg: str) -> int:
    path, _, number = arg.rpartition(":")
    if not path or not number.isdigit():
        print("usage: check_notes.py --hash FILE:LINE")
        return 1
    if not Path(path).is_file():
        print(f"not a file: {path}")
        return 1
    file, lines = Path(path), note_lines(Path(path))
    if not 1 <= int(number) <= len(lines):
        print(f"{file.name} has {len(lines)} lines")
        return 1
    kinds = findings(lines, int(number))
    print(f"{line_hash(lines[int(number) - 1])}  {file.parent.name}/{file.name}  "
          f"# line {number}: {', '.join(kinds) or 'no rule matched'}; why approved: ...")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--hash":
        return hash_entry(argv[1])
    if len(argv) < 2:
        print(__doc__)
        return 1
    bot_path = Path(argv[0]).resolve()
    dirs = list(dict.fromkeys(Path(d).resolve() for d in argv[1:]))
    missing = [d for d in dirs if not d.is_dir()]
    for d in missing:
        print(f"FAIL folder not found: {d}")
    if missing:
        return 1
    bot, log = load_bot(bot_path, dirs)
    failed = False
    for line in log.splitlines():
        if "[warning]" in line or "[error]" in line:
            print("FAIL bot log:", line)
            failed = True
    files = [(d, f) for d in dirs for f in note_files(bot, d)]
    for d in dirs:
        if not any(folder == d for folder, _ in files):
            print(f"FAIL no note files in {d}")
            failed = True
    loaded = set(re.findall(r'^<document name="([^"]+)">$', bot.NOTES, re.M))
    expected = {f"{d.name}/{f.name}" for d, f in files}
    for name in sorted(expected ^ loaded):
        print("FAIL", "not loaded by the bot:" if name in expected else "loaded but not scanned:", name)
        failed = True
    share = 100 * len(bot.NOTES) / bot.MAX_NOTES_CHARS
    print(f"Loaded {len(loaded)} files, {len(bot.NOTES)} chars ({share:.0f}% of MAX_NOTES_CHARS {bot.MAX_NOTES_CHARS})")

    allowed, used, secrets, phones = load_allowlist(), set(), 0, 0
    for d, f in files:
        name = f"{d.name}/{f.name}"
        taught = d.name == getattr(bot, "LEARNED_DIR", None) and hasattr(bot, "looks_secret")
        try:
            lines = note_lines(f)
        except (OSError, UnicodeError) as e:
            print(f"FAIL {name} not readable: {e}")
            failed = True
            continue
        numbers = []
        for number, line in enumerate(lines, 1):
            kinds = findings(lines, number)
            if taught and bot.looks_secret(line):
                kinds = sorted(set(kinds) | {"bot-rule"})
            if kinds:
                digest = line_hash(line)
                if allowed.get(digest) == name:
                    used.add(digest)
                    print(f"ok   {name}:{number}  allowlisted ({', '.join(kinds)})")
                else:
                    secrets += 1
                    print(f"FAIL {name}:{number}  {', '.join(kinds)} (text not shown; open the file at this line)")
            numbers += [m.group().strip() for m in PHONE.finditer(LINKS.sub(" ", line))]
        if numbers:
            phones += len(numbers)
            print(f"note {name}: {len(numbers)} phone numbers: {', '.join(dict.fromkeys(numbers))}")
    scanned = {d.name for d in dirs}
    for digest, where in allowed.items():
        if digest not in used and where.split("/")[0] in scanned:
            print(f"note allowlist entry {digest[:12]}... ({where}) matched nothing; remove it if stale")
    print(f"Secret scan: {secrets} unapproved, {len(used)} allowlisted. Phone numbers: {phones} (check that new ones are "
          "work numbers)")
    return 1 if failed or secrets else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
