"""Synthetic fixtures only; never contact sources or seed an existing database."""
import argparse
import os
import ipaddress
from uuid import UUID
from contextlib import closing
import psycopg
from psycopg.conninfo import conninfo_to_dict

RECORDS=(
 ("ТУРШИЛТ — Алтан нар засвар","services","Зохиомол цахилгаан засварын үйлчилгээ","valid"),
 ("ТУРШИЛТ — Хөх тэнгэр худалдаа","trade","Зохиомол тоног төхөөрөмжийн худалдаа","valid"),
 ("ТУРШИЛТ — Ногоон тал сургалт","services","Зохиомол сургалтын үйлчилгээ","unapproved"),
 ("ТУРШИЛТ — Цагаан уул хүргэлт","services","Зохиомол хүргэлтийн үйлчилгээ","expired"),
)
def identifier(n):
    return UUID(int=0x8f100000000040008000000000000000+n)

def guard(c):
    db=c.execute("SELECT current_database(),inet_server_addr()::text").fetchone()
    if db[0]!="lavlah_pilot_test" or not db[1]:
        raise ValueError("Dedicated loopback pilot database required")
    actual=ipaddress.ip_interface(db[1]).ip
    if actual.is_loopback:
        return
    # Docker port forwarding: the client still connects to numeric loopback.
    # Accept only an explicitly pinned RFC1918 service address in integration CI.
    expected=os.environ.get("LAVLAH_PILOT_CONTAINER_IP")
    private=any(actual in ipaddress.ip_network(net) for net in
                ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"))
    if not (os.environ.get("LAVLAH_PILOT_INTEGRATION")=="1" and private and expected==str(actual)):
        raise ValueError("Dedicated loopback pilot database required")

def validate_dsn(dsn):
    options=conninfo_to_dict(dsn)
    if options.get("dbname")!="lavlah_pilot_test" or options.get("host") not in ("127.0.0.1","::1"):
        raise ValueError("Dedicated numeric loopback pilot DSN required")
    if set(options)-{"dbname","host","port","user","password","sslmode"}:
        raise ValueError("Unexpected pilot connection options")

def apply(dsn,*,reset=False):
    validate_dsn(dsn)
    if os.environ.get("LAVLAH_PILOT_ONLY")!="1":
        raise ValueError("Explicit pilot opt-in required")
    # Explicit hostaddr also prevents inherited PGHOSTADDR overriding loopback.
    host=conninfo_to_dict(dsn)["host"]
    with closing(psycopg.connect(dsn,hostaddr=host,connect_timeout=5)) as c:
        with c.transaction():
            guard(c)
            if c.execute("SELECT current_setting('lavlah.pilot_only', true)").fetchone()[0]!="yes":
                raise ValueError("Pilot database marker required")
            c.execute("SELECT pg_advisory_xact_lock(8041001)")
            ids=[identifier(100+i) for i in range(len(RECORDS))]
            if c.execute("SELECT 1 FROM lavlah.organizations WHERE NOT (id=ANY(%s)) LIMIT 1",(ids,)).fetchone():
                raise ValueError("Non-pilot organizations present")
            if c.execute("SELECT 1 FROM lavlah.users WHERE NOT (id=ANY(%s)) LIMIT 1",([identifier(1),identifier(2)],)).fetchone():
                raise ValueError("Non-pilot users present")
            if c.execute("SELECT 1 FROM lavlah.sources WHERE NOT (id=ANY(%s)) OR authorization_reference<>'SYNTHETIC ONLY' LIMIT 1",([identifier(200+i) for i in range(len(RECORDS))],)).fetchone():
                raise ValueError("Non-pilot sources present")
            c.execute("DELETE FROM lavlah.public_listings WHERE organization_id=ANY(%s)",(ids,))
            c.execute("DELETE FROM lavlah.sources WHERE organization_id=ANY(%s)",(ids,))
            c.execute("DELETE FROM lavlah.organizations WHERE id=ANY(%s)",(ids,))
            c.execute("DELETE FROM lavlah.users WHERE id=ANY(%s)",([identifier(1),identifier(2)],))
            if reset: return 0
            for i in (1,2):
                c.execute("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,%s,%s)",(identifier(i),"synthetic-pilot-"+str(i),"Туршилтын хэрэглэгч"))
            c.execute("INSERT INTO lavlah.categories VALUES ('services','Үйлчилгээ'),('trade','Худалдаа') ON CONFLICT DO NOTHING")
            for i,(name,category,desc,status) in enumerate(RECORDS):
                org,source=ids[i],identifier(200+i)
                url="https://pilot.example.test/"+str(i)
                c.execute("INSERT INTO lavlah.organizations(id,name,category_slug,description) VALUES (%s,%s,%s,%s)",(org,name,category,desc))
                c.execute("""INSERT INTO lavlah.sources(id,organization_id,submitted_by,source_url,authorization_reference,observed_at,verified_by,verified_at,expires_at)
                VALUES (%s,%s,%s,%s,'SYNTHETIC ONLY',now()-interval '3 days',%s,now()-interval '2 days',now()+%s::interval)""",
                (source,org,identifier(1),url,identifier(2),"-1 day" if status=="expired" else "2 days"))
                if status!="unapproved":
                    c.execute("INSERT INTO lavlah.public_listings(organization_id,source_id,name,category_slug,description,public_source_url) VALUES (%s,%s,%s,%s,%s,%s)",(org,source,name,category,desc,url))
            return len(RECORDS)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=["seed","reset"])
    args=parser.parse_args()
    if os.environ.get("LAVLAH_PILOT_ONLY")!="1":
        parser.error("Explicit pilot opt-in required")
    print(apply(os.environ["LAVLAH_PILOT_DSN"],reset=args.action=="reset"))
