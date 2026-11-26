"""Generate a reviewable Linux/Python 3.12 lock candidate, never auto-commit."""
import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

def main():
    if sys.version_info[:2] != (3,12) or sys.platform!="linux":
        raise SystemExit("Linux Python 3.12 required")
    with TemporaryDirectory() as tmp:
        report=Path(tmp)/"report.json"
        subprocess.run([sys.executable,"-m","pip","--isolated","install","--dry-run","--ignore-installed","--only-binary=:all:","--index-url","https://pypi.org/simple","--report",str(report),"-r","requirements-ci.in"],check=True)
        items=json.loads(report.read_text())["install"]
        lines=[]
        names=set()
        for item in items:
            meta=item["metadata"]
            name=re.sub(r"[-_.]+","-",meta["name"]).lower()
            version=meta["version"]
            info=item["download_info"]
            url=urlsplit(info["url"])
            digest=info["archive_info"]["hashes"]["sha256"]
            if not re.fullmatch(r"[a-z0-9-]+",name) or not re.fullmatch(r"[A-Za-z0-9.+!-]+",version) or not re.fullmatch(r"[a-f0-9]{64}",digest) or url.scheme!="https" or url.hostname!="files.pythonhosted.org" or url.username or url.password or name in names:
                raise ValueError("Unexpected resolver metadata")
            names.add(name)
            lines.append(f"{name}=={version} --hash=sha256:{digest}")
        if not {"fastapi","psycopg","psycopg-binary","uvicorn","httpx","playwright","pip-audit"}<=names:
            raise ValueError("Incomplete lock")
        target=Path(sys.argv[1])
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text("# Linux x86_64, Python 3.12; review before commit.\n"+"\n".join(sorted(lines))+"\n")
if __name__=="__main__":
    main()
