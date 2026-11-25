"""Process-isolated HTTPS fetch; deadline includes DNS, TLS and response reads."""
import multiprocessing as mp
from lavlah.https_adapter import fetch_json, MAX_BYTES
from lavlah.ingestion import IngestionError

def _worker(pipe,url,fetch):
    try:
        data=fetch(url)
        if not isinstance(data,bytes) or len(data)>MAX_BYTES:
            raise ValueError()
        pipe.send_bytes(b"O"+data)
    except BaseException:
        pipe.send_bytes(b"E")
    finally:
        pipe.close()

def bounded_fetch(url,fetch=fetch_json,timeout=20):
    if not 0<timeout<=30:
        raise ValueError("Invalid transport deadline")
    ctx=mp.get_context("spawn")
    recv,send=ctx.Pipe(duplex=False)
    proc=ctx.Process(target=_worker,args=(send,url,fetch),daemon=True)
    try:
        proc.start()
        send.close()
        if not recv.poll(timeout):
            raise IngestionError("timeout")
        try:
            msg=recv.recv_bytes(MAX_BYTES+1)
        except (EOFError,OSError):
            raise IngestionError("collection_failed") from None
        if not msg.startswith(b"O"):
            raise IngestionError("collection_failed")
        return msg[1:]
    finally:
        recv.close()
        send.close()
        if proc.pid is not None:
            if proc.is_alive(): proc.kill()
            proc.join(timeout=1)
            if not proc.is_alive(): proc.close()
