import os
from contextlib import contextmanager
from unittest.mock import patch
from lavlah.public_api import security
PASSWORD="synthetic-test-only-password-123"
@contextmanager
def pilot_auth(client):
    with patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_PILOT_ONLY":"1","LAVLAH_PILOT_PASSWORD":PASSWORD,"LAVLAH_PUBLIC_DSN":os.getenv("LAVLAH_PUBLIC_DSN","postgresql://lavlah_integration_login@127.0.0.1/lavlah_pilot_test")}):
        security.sessions.clear()
        security.attempts.clear()
        res=client.post("/v1/pilot/login",json={"password":PASSWORD})
        assert res.status_code==200,res.text
        client.headers["Authorization"]="Bearer "+res.json()["token"]
        try:yield
        finally:
            client.headers.pop("Authorization",None)
            security.sessions.clear()
            security.attempts.clear()
