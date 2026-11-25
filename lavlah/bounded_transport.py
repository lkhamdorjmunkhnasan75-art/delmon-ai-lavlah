"""Process-isolated transport; never read an incomplete child response."""
import multiprocessing as mp
import tempfile
import time
from pathlib import Path
from lavlah.https_adapter import fetch_json, MAX_BYTES
from lavlah.ingestion import IngestionError

def _worker(path,url,fetch):
    try:
        data=fetch(url)
        if not isinstance(data,bytes) or len(data)>MAX_BYTES:
            raise ValueError()
        Path(path).write_bytes(b"O"+data)
    except BaseException:
        Path(path).write_bytes(b"E")

def bounded_fetch(url,fetch=fetch_json,timeout=20):
    if not 0<timeout<=30:
        raise ValueError("Invalid transport deadline")
    deadline=time.monotonic()+timeout
    with tempfile.TemporaryDirectory(prefix="lavlah-fetch-") as root:
        path=Path(root)/"result"
        proc=mp.get_context("spawn").Process(target=_worker,args=(str(path),url,fetch),daemon=True)
        try:
            proc.start()
            proc.join(max(0,deadline-time.monotonic()))
            if proc.is_alive() or time.monotonic()>deadline:
                raise IngestionError("timeout")
            if proc.exitcode!=0 or not path.is_file():
                raise IngestionError("collection_failed")
            with path.open("rb") as handle:
                msg=handle.read(MAX_BYTES+2)
            if len(msg)>MAX_BYTES+1 or not msg.startswith(b"O"):
                raise IngestionError("collection_failed")
            return msg[1:]
        finally:
            if proc.pid is not None:
                if proc.is_alive(): proc.kill()
                proc.join(timeout=1)
                if not proc.is_alive(): proc.close()
