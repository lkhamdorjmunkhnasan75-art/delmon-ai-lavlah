"""Local heuristic scan. Output counts only, never file content or matched values."""
import argparse
from hashlib import sha256
import re
import subprocess
import sys
from pathlib import Path

RULES={
 "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
 "github_token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
 "aws_access_id": re.compile(rb"(?:AKIA|ASIA)[A-Z0-9]{16}"),
 "openai_key": re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}"),
 "credential_url": re.compile(rb"https?://[^\s/@:]+:[^\s/@]+@[^\s/]+"),
}
# Human approval on 2026-11-27 in the Codex conversation for draft PR #31.
# Provenance and the approval scope are recorded in docs/t10-3-5-secret-scan.md.
# Each record identifies one historical credential_url match.
REVIEWED_HISTORY = {
    "30c1cddf74b553e5922797e025c64f36ad33f7a9": (
        "6efa73df2f906277291abe7ffb540f390d087281cdc65e74d7ffff80ddeb3a70",
        "5e0e55ac398c6facecd8325e799b69762b516fc3", "tests/test_grounded_ai.py", 25,
    ),
    "dc0cf3dce5e56776ed1ba7ee68a02540f60972cd": (
        "5b578fadf24767557cbfbfe06ea57301e12cdbd1ed8ff6ae7b70a738719a258e",
        "7eeef220f2b49c21d36aace37260c8bf0215fc0f", "tests/test_grounded_ai.py", 26,
    ),
}


def git(*args):
    return subprocess.check_output(["git",*args],stderr=subprocess.DEVNULL)
def inspect(data,counts,location):
    for rule,pattern in RULES.items():
        matches=list(pattern.finditer(data))
        if not matches:continue
        counts[rule]+=1
        # Location is a tracked path fingerprint or blob ID; never print matched text.
        if rule=="credential_url":
            from urllib.parse import urlsplit
            categories=set()
            for m in matches:
                try:
                    u=urlsplit(m.group().decode("ascii"))
                    host=u.hostname or ""
                    categories.add("reserved-test-host" if host.endswith(".test") or host in ("localhost","127.0.0.1","::1") else "other-or-unknown-host")
                except (ValueError,UnicodeError):
                    categories.add("unparseable")
            print("Credential URL candidate:",location,"classification:",",".join(sorted(categories)),"matches:",len(matches))
def is_reviewed(oid, data, disposition):
    digest, commit, path, line = disposition
    matches = list(RULES["credential_url"].finditer(data))
    if (sha256(data).hexdigest() != digest or len(matches) != 1
            or data.count(b"\n", 0, matches[0].start()) + 1 != line):
        return False
    if git("rev-parse", f"{commit}:{path}").strip() != oid.encode("ascii"):
        return False

    # A blob can appear at many paths. Check changes relative to every merge
    # parent, including additions of the identical bytes at a different path.
    changes = git("log", "--all", "HEAD", "--root", "-m", "--format=",
                  "--raw", "--no-abbrev", "--no-renames", "-z", f"--find-object={oid}")
    paths = changes.rstrip(b"\0").split(b"\0")[1::2]
    return bool(paths) and all(candidate == path.encode("utf-8") for candidate in paths)


def main(apply_reviewed_history=False):
    if git("rev-parse","--is-shallow-repository").strip()!=b"false":
        raise SystemExit("Full reachable history required")
    counts={k:0 for k in RULES}
    tracked=0
    for name in git("ls-files","-z").split(b"\0"):
        if not name:continue
        p=Path(name.decode("utf-8",errors="surrogateescape"))
        if p.is_symlink() or not p.is_file():raise SystemExit("Unscannable tracked path")
        inspect(p.read_bytes(),counts,'tracked path sha256='+sha256(name).hexdigest())
        tracked+=1
    print("Tracked files scanned:",tracked,"pattern counts:",counts)
    history={k:0 for k in RULES}
    blobs=0
    reviewed = set()
    objects=git("rev-list","--objects","--all","HEAD").splitlines()
    ids=sorted({line.split(b" ",1)[0].decode("ascii") for line in objects})
    for oid in ids:
        if git("cat-file","-t",oid).strip()!=b"blob":continue
        data = git("cat-file", "blob", oid)
        inspect(data, history, "historical blob="+oid)
        if apply_reviewed_history and oid in REVIEWED_HISTORY:
            if is_reviewed(oid, data, REVIEWED_HISTORY[oid]):
                reviewed.add(oid)
                print("Reviewed historical credential URL:", oid)
        blobs+=1
    print("Reachable historical blobs scanned:",blobs,"pattern counts:",history)
    if apply_reviewed_history and reviewed != REVIEWED_HISTORY.keys():
        print("Historical disposition did not match:", ", ".join(sorted(REVIEWED_HISTORY.keys() - reviewed)))
        return 1
    unresolved = sum(history.values()) - len(reviewed)
    return int(any(counts.values()) or unresolved != 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-reviewed-history", action="store_true",
                        help="Apply the two reviewed historical dispositions to the exit status")
    sys.exit(main(parser.parse_args().apply_reviewed_history))
