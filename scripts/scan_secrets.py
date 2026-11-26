"""Local heuristic scan. Output counts only, never file content or matched values."""
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
def git(*args):
    return subprocess.check_output(["git",*args],stderr=subprocess.DEVNULL)
def inspect(data,counts):
    for rule,pattern in RULES.items():
        if pattern.search(data):counts[rule]+=1
def main():
    if git("rev-parse","--is-shallow-repository").strip()!=b"false":
        raise SystemExit("Full reachable history required")
    counts={k:0 for k in RULES}
    tracked=0
    for name in git("ls-files","-z").split(b"\0"):
        if not name:continue
        p=Path(name.decode("utf-8",errors="surrogateescape"))
        if p.is_symlink() or not p.is_file():raise SystemExit("Unscannable tracked path")
        inspect(p.read_bytes(),counts)
        tracked+=1
    print("Tracked files scanned:",tracked,"pattern counts:",counts)
    history={k:0 for k in RULES}
    blobs=0
    objects=git("rev-list","--objects","--all","HEAD").splitlines()
    ids=sorted({line.split(b" ",1)[0].decode("ascii") for line in objects})
    for oid in ids:
        if git("cat-file","-t",oid).strip()!=b"blob":continue
        inspect(git("cat-file","blob",oid),history)
        blobs+=1
    print("Reachable historical blobs scanned:",blobs,"pattern counts:",history)
    return int(any(counts.values()) or any(history.values()))
if __name__=="__main__":
    sys.exit(main())
