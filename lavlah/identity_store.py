"""Offline identity boundary. Dedicated trusted service login; no arbitrary SQL."""
import os
import ipaddress
from contextlib import contextmanager, closing
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict
from lavlah.synthetic_identity import validate, configured_key

def check_connection(c,login):
    row=c.execute("""SELECT current_database() AS db, session_user AS login,
        inet_server_addr()::text AS addr, current_setting('lavlah.pilot_only',true) AS marker,
        (SELECT rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb FROM pg_roles WHERE rolname=session_user) AS privileged""").fetchone()
    if row["db"]!="lavlah_pilot_test" or row["login"]!=login or row["marker"]!="yes" or row["privileged"] is not False:
        raise ValueError("Pilot database identity mismatch")
    if not row["addr"]:
        raise ValueError("Pilot TCP server required")
    actual=ipaddress.ip_interface(row["addr"]).ip
    if not actual.is_loopback:
        private=any(actual in ipaddress.ip_network(net) for net in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"))
        if not (private and os.getenv("LAVLAH_PILOT_INTEGRATION")=="1" and os.getenv("LAVLAH_PILOT_CONTAINER_IP")==str(actual)):
            raise ValueError("Pilot server mismatch")

def checked_dsn(name,login):
    if os.getenv("LAVLAH_ENV")!="pilot" or os.getenv("LAVLAH_PILOT_ONLY")!="1":
        raise ValueError("Pilot disabled")
    try:
        dsn=os.environ[name]
        opts=conninfo_to_dict(dsn)
    except (KeyError, ValueError, psycopg.Error):
        raise ValueError("Invalid pilot database configuration") from None
    if opts.get("host")!="127.0.0.1" or opts.get("dbname")!="lavlah_pilot_test" or opts.get("user")!=login or set(opts)-{"host","port","dbname","user","password","sslmode"}:
        raise ValueError("Pilot DSN mismatch")
    if opts.get("port", "5432") != "5432" or opts.get("sslmode", "prefer") not in ("disable", "prefer", "require", "verify-ca", "verify-full"):
        raise ValueError("Unexpected pilot connection option")
    if any(k in os.environ for k in ("PGHOSTADDR","PGSERVICE","PGSERVICEFILE","PGOPTIONS","PGPORT","PGTARGETSESSIONATTRS","PGLOADBALANCEHOSTS")):
        raise ValueError("Unexpected database environment")
    return dsn

@contextmanager
def identity_transaction(token,*,revoke=False):
    claims=validate(token,configured_key())
    dsn=checked_dsn("LAVLAH_IDENTITY_DSN","lavlah_identity_login")
    with closing(psycopg.connect(dsn,hostaddr="127.0.0.1",port=5432,connect_timeout=5,row_factory=dict_row)) as c:
        with c.transaction():
            c.execute("SET LOCAL statement_timeout='3s'")
            check_connection(c,"lavlah_identity_login")
            c.execute("SET LOCAL ROLE lavlah_identity")
            # Serialize revocation and use of each token until transaction ends.
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,10))",(claims["jti"],))
            validate(token,configured_key())
            if c.execute("SELECT 1 FROM lavlah.identity_revocations WHERE jti=%s",(claims["jti"],)).fetchone():
                raise ValueError("Session revoked")
            user=c.execute("SELECT id FROM lavlah.users WHERE auth_subject=%s",(claims["sub"],)).fetchone()
            if not user:raise ValueError("Unknown subject")
            if revoke:
                c.execute("INSERT INTO lavlah.identity_revocations VALUES (%s,to_timestamp(%s))",(claims["jti"],claims["exp"]))
                yield None
            else:
                c.execute("SET LOCAL ROLE lavlah_request")
                c.execute("SELECT set_config('lavlah.user_id',%s,true)",(str(user["id"]),))
                yield c

def profile(token):
    with identity_transaction(token) as c:
        return {"organizations":c.execute("""SELECT o.id,o.name,m.role FROM lavlah.organizations o
            JOIN lavlah.memberships m ON m.organization_id=o.id ORDER BY o.id""").fetchall(),
            "user":c.execute("SELECT id,display_name FROM lavlah.users").fetchone()}

def revoke_token(token):
    with identity_transaction(token,revoke=True):pass
