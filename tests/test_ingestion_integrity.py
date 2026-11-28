import os
import unittest
import socket
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import psycopg
from lavlah.ingestion import IngestionError
from lavlah.authenticated_ingestion import AuthenticatedIngestion
from lavlah.collection import LocalJSONAdapter
from lavlah.https_adapter import public_addresses,collect_registered
from lavlah.pilot_fixtures import apply,identifier
from test_identity_isolation import token,KEY

class IntegrityUnit(unittest.TestCase):
    def test_translation_addresses(self):
        for ip in ("64:ff9b::a00:1","64:ff9b:1::1"):
            with self.assertRaises(IngestionError):
                public_addresses("example.test",lambda *a,**k:[(socket.AF_INET6,socket.SOCK_STREAM,6,"",(ip,443,0,0))])
    def test_symlink_and_fifo(self):
        with TemporaryDirectory() as root:
            pid=uuid4()
            p=Path(root)/(str(pid)+".json")
            other=Path(root)/"other"
            other.write_text("[]")
            p.symlink_to(other)
            with self.assertRaises(IngestionError):LocalJSONAdapter(root).collect({"id":pid})
            p.unlink()
            os.mkfifo(p)
            with self.assertRaises(IngestionError):LocalJSONAdapter(root).collect({"id":pid})
    def test_no_implicit_network(self):
        with self.assertRaises(IngestionError):collect_registered("unused",uuid4(),uuid4())
    def test_explicit_strict_mode(self):
        with patch.dict(os.environ,{"LAVLAH_INGESTION_STRICT":"0"}):
            with self.assertRaises(IngestionError):AuthenticatedIngestion()

    def test_reviewer_configuration_rejects_collector_login(self):
        collector_dsn = "postgresql://lavlah_ingest_test@127.0.0.1/lavlah_pilot_test"
        with patch.dict(os.environ, {
            "LAVLAH_ENV": "pilot",
            "LAVLAH_PILOT_ONLY": "1",
            "LAVLAH_INGESTION_STRICT": "1",
            "LAVLAH_INGESTION_DSN": collector_dsn,
            "LAVLAH_REVIEW_DSN": collector_dsn,
        }, clear=True):
            with self.assertRaisesRegex(ValueError, "Pilot DSN mismatch"):
                AuthenticatedIngestion()

    def test_expired_token_rejected_before_reviewer_connection(self):
        expires_at = int(time.time())
        expired_token = token(sub="synthetic-pilot-2", iat=expires_at - 60, exp=expires_at)
        with patch.dict(os.environ, {
            "LAVLAH_ENV": "pilot",
            "LAVLAH_PILOT_ONLY": "1",
            "LAVLAH_INGESTION_STRICT": "1",
            "LAVLAH_SYNTHETIC_KEY": KEY.hex(),
            "LAVLAH_INGESTION_DSN": "postgresql://lavlah_ingest_test@127.0.0.1/lavlah_pilot_test",
            "LAVLAH_REVIEW_DSN": "postgresql://lavlah_review_test@127.0.0.1/lavlah_pilot_test",
        }, clear=True), patch("psycopg.connect") as connect:
            with self.assertRaisesRegex(ValueError, "Invalid synthetic identity"):
                AuthenticatedIngestion().review(
                    expired_token, uuid4(), approve=True, evidence="synthetic"
                )
            connect.assert_not_called()

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class IntegrityDB(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(self.dsn)
        self.pid=uuid4()
        self.org=identifier(102)
        self.actor=identifier(1)
        self.reviewer=identifier(2)
        self.sql("INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days) VALUES (%s,%s,'https://example.test/feed','synthetic',%s,now()+interval '2 days',1)",(self.pid,self.org,self.reviewer))
        self.sql("INSERT INTO lavlah.ingestion_actor_grants VALUES (%s,%s,'collect'),(%s,%s,'review')",(self.pid,self.actor,self.pid,self.reviewer))
        self.addCleanup(self.cleanup)
        flag=patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_INGESTION_STRICT":"1","LAVLAH_SYNTHETIC_KEY":KEY.hex()})
        flag.start()
        self.addCleanup(flag.stop)
        self.sql("""INSERT INTO lavlah.reviewer_login_bindings(login_oid,login_name,user_id)
                    SELECT oid,rolname,%s FROM pg_roles WHERE rolname='lavlah_review_test'""",
                 (self.reviewer,))
        self.s=AuthenticatedIngestion()
    def sql(self,q,args=()):
        with psycopg.connect(self.dsn) as c:
            cur=c.execute(q,args)
            return cur.fetchall() if cur.description else None
    def cleanup(self):
        with psycopg.connect(self.dsn) as c:
            c.execute("DELETE FROM lavlah.publication_audit WHERE permission_id=%s",(self.pid,))
            c.execute("DELETE FROM lavlah.public_listings WHERE organization_id=%s AND source_id IN (SELECT source_id FROM lavlah.ingestion_reviews WHERE candidate_id IN (SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s))",(self.org,self.pid))
            sources=c.execute("SELECT source_id FROM lavlah.ingestion_reviews WHERE candidate_id IN (SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s) AND source_id IS NOT NULL",(self.pid,)).fetchall()
            c.execute("DELETE FROM lavlah.ingestion_reviews WHERE candidate_id IN (SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s)",(self.pid,))
            for (source,) in sources:c.execute("DELETE FROM lavlah.sources WHERE id=%s",(source,))
            c.execute("DELETE FROM lavlah.ingestion_candidates WHERE permission_id=%s",(self.pid,))
            c.execute("DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s",(self.pid,))
            c.execute("DELETE FROM lavlah.ingestion_permissions WHERE id=%s",(self.pid,))
        apply(self.dsn,reset=True)
    def submit(self,name):
        return self.s.submit(token(),self.pid,[{"name":name,"category_slug":"services","description":"synthetic"}])[0]["id"]
    def review(self,candidate):
        return self.s.review(token(sub="synthetic-pilot-2"),candidate,approve=True,evidence="checked")
    def test_actor_permissions(self):
        with self.assertRaises(IngestionError):
            self.s.submit(token(sub="synthetic-pilot-2"),self.pid,[{"name":"fake","category_slug":"services","description":""}])
        candidate=self.submit("fresh")
        with self.assertRaises(IngestionError):
            self.s.review(token(),candidate,approve=True,evidence="self")
        self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[("approved",)])
    def test_newer_wins(self):
        older=self.submit("old")
        self.sql("UPDATE lavlah.ingestion_candidates SET observed_at=now()-interval '1 hour' WHERE id=%s",(older,))
        newer=self.submit("new")
        self.review(newer)
        with self.assertRaises(IngestionError):self.review(older)
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[("new",)])
    def test_concurrent_reviews(self):
        older=self.submit("old")
        self.sql("UPDATE lavlah.ingestion_candidates SET observed_at=now()-interval '1 hour' WHERE id=%s",(older,))
        newer=self.submit("new")
        def run(cid):
            try:self.review(cid)
            except IngestionError:pass
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[older,newer]))
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[("new",)])
    def test_revocation(self):
        candidate=self.submit("new")
        self.review(candidate)
        self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[])
        with self.assertRaises(IngestionError):self.submit("other")

    def test_reviewer_grant_revoked(self):
        candidate=self.submit("fresh")
        self.sql("DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s AND user_id=%s",(self.pid,self.reviewer))
        with self.assertRaises(IngestionError):self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_direct_reviewer_timestamp_denied(self):
        candidate=self.submit("fresh")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence,reviewed_at) VALUES (%s,%s,'rejected','synthetic',now())",(candidate,self.reviewer))
        self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[("approved",)])

    def test_request_role_cannot_lock_grants(self):
        from lavlah.identity_store import identity_transaction
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with identity_transaction(token()) as c:
                c.execute("SELECT lavlah.lock_actor_grant(%s,%s,'review')",(self.pid,self.reviewer))

    def test_admin_revocation_serializes_with_review(self):
        from threading import Event
        from lavlah.ingestion import require_actor
        candidate=self.submit("fresh")
        authorized=Event()
        release=Event()
        def hold(c,pid,actor,capability):
            require_actor(c,pid,actor,capability)
            if capability=="review":
                authorized.set()
                if not release.wait(4):raise RuntimeError("test synchronization timeout")
        with patch("lavlah.ingestion.require_actor",side_effect=hold):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.review,candidate)
                try:
                    self.assertTrue(authorized.wait(3))
                    for sql,args in (
                        ("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,)),
                        ("DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s AND user_id=%s",(self.pid,self.reviewer)),
                    ):
                        with self.assertRaises(psycopg.errors.LockNotAvailable):
                            with psycopg.connect(self.dsn) as c:
                                c.execute("SET LOCAL lock_timeout='150ms'")
                                c.execute(sql,args)
                finally:
                    release.set()
                self.assertEqual(future.result(timeout=8)["decision"],"approved")
        self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[])

    def test_admin_first_revocation_blocks_waiting_review(self):
        from threading import Event
        from lavlah.ingestion import permission
        candidate=self.submit("fresh")
        entered=Event()
        def entering(c,pid):
            entered.set()
            return permission(c,pid)
        with patch("lavlah.ingestion.permission",side_effect=entering):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with psycopg.connect(self.dsn) as admin:
                    admin.execute("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
                    future=pool.submit(self.review,candidate)
                    self.assertTrue(entered.wait(3))
                    # Admin commits before the pending lock acquisition may succeed.
                with self.assertRaises(IngestionError):future.result(timeout=8)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_permission_expires_during_review(self):
        from lavlah.ingestion import require_actor
        candidate=self.submit("fresh")
        self.sql("UPDATE lavlah.ingestion_permissions SET valid_until=clock_timestamp()+interval '1 second' WHERE id=%s",(self.pid,))
        def expire(c,pid,actor,capability):
            require_actor(c,pid,actor,capability)
            c.execute("SELECT pg_sleep(1.1)")
        with patch("lavlah.ingestion.require_actor",side_effect=expire):
            with self.assertRaises((IngestionError,psycopg.errors.InsufficientPrivilege)):self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.ingestion_reviews WHERE candidate_id=%s",(candidate,)),[])
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_direct_publication_without_review_denied(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("UPDATE lavlah.public_listings SET name='forged' WHERE organization_id=%s",(identifier(100),))
        candidate=self.submit("fresh")
        self.assertEqual(self.review(candidate)["decision"],"approved")

    def test_direct_audit_recorded_at_denied(self):
        candidate=self.submit("fresh")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("""INSERT INTO lavlah.publication_audit(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,recorded_at)
                SELECT id,permission_id,%s,%s,digest,observed_at,'rejected',now() FROM lavlah.ingestion_candidates WHERE id=%s""",(self.org,self.reviewer,candidate))
        self.assertEqual(self.review(candidate)["decision"],"approved")

    def test_definer_catalog_permissions(self):
        rows=self.sql("""SELECT p.proname,p.prosecdef,p.proconfig,
          pg_has_role('lavlah_request',p.proowner,'MEMBER'),
          has_function_privilege('lavlah_request',p.oid,'EXECUTE'),
          EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='lavlah' AND p.proname IN ('lock_memberships','lock_active_permission','lock_actor_grant')""")
        self.assertEqual(len(rows),3)
        for name,definer,config,owner_member,request_exec,public_exec in rows:
            self.assertTrue(definer)
            self.assertIn("search_path=pg_catalog",config)
            self.assertFalse(owner_member or request_exec or public_exec,name)

    def test_direct_forged_review_and_audit_denied(self):
        candidate=self.submit("fresh")
        for query,args in (
            ("INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence) VALUES (%s,%s,'rejected','forged')",(candidate,self.reviewer)),
            ("INSERT INTO lavlah.publication_audit(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision) SELECT id,permission_id,%s,%s,digest,observed_at,'rejected' FROM lavlah.ingestion_candidates WHERE id=%s",(self.org,self.reviewer,candidate)),
            ("INSERT INTO lavlah.sources(organization_id,submitted_by,source_url,authorization_reference) VALUES (%s,%s,'https://example.test/fake','forged')",(self.org,self.actor)),
        ):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                    c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                    c.execute(query,args)
        self.assertEqual(self.review(candidate)["decision"],"approved")

    def test_atomic_function_denies_wrong_actor(self):
        candidate=self.submit("fresh")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("SELECT lavlah.atomic_review(%s,%s,true,'forged')",(candidate,self.actor))
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_atomic_rejection_and_duplicate(self):
        candidate=self.submit("fresh")
        result=self.s.review(token(sub="synthetic-pilot-2"),candidate,approve=False,evidence="checked")
        self.assertEqual(result,{"decision":"rejected","source_id":None})
        self.assertEqual(self.sql("SELECT decision,source_id FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[("rejected",None)])
        with self.assertRaises(IngestionError):self.review(candidate)

    def test_atomic_owner_and_acl(self):
        rows=self.sql("""SELECT r.rolname,r.rolcanlogin,r.rolsuper,r.rolbypassrls,r.rolcreaterole,r.rolcreatedb,
          p.prosecdef,p.proconfig,pg_has_role('lavlah_ingestion_reviewer',r.oid,'MEMBER'),
          has_function_privilege('lavlah_request',p.oid,'EXECUTE'),
          has_schema_privilege(r.oid,'lavlah','CREATE'),
          EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner
          WHERE n.nspname='lavlah' AND p.proname='atomic_review'""")
        self.assertEqual(len(rows),1)
        name,login,superuser,bypass,createrole,createdb,definer,config,member,request_exec,create,public_exec=rows[0]
        self.assertEqual(name,"lavlah_publication_owner")
        self.assertTrue(definer)
        self.assertIn("search_path=pg_catalog",config)
        self.assertFalse(any((login,superuser,bypass,createrole,createdb,member,request_exec,create,public_exec)))

    def test_bound_login_requires_matching_authenticated_reviewer(self):
        candidate = self.submit("reviewer binding")
        self.sql("UPDATE lavlah.reviewer_login_bindings SET user_id=%s WHERE user_id=%s",
                 (self.actor, self.reviewer))
        with self.assertRaisesRegex(IngestionError, "Atomic review denied"):
            self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",
                                  (candidate,)), [])
        self.sql("UPDATE lavlah.reviewer_login_bindings SET user_id=%s WHERE user_id=%s",
                 (self.reviewer, self.actor))
        source = self.review(candidate)["source_id"]
        self.assertEqual(self.sql("SELECT reviewer_id FROM lavlah.ingestion_reviews WHERE candidate_id=%s",
                                  (candidate,)), [(self.reviewer,)])
        self.assertEqual(self.sql("SELECT reviewer_id FROM lavlah.publication_audit WHERE candidate_id=%s",
                                  (candidate,)), [(self.reviewer,)])
        self.assertEqual(self.sql("SELECT verified_by FROM lavlah.sources WHERE id=%s",
                                  (source,)), [(self.reviewer,)])

    def test_missing_binding_denies_authorized_reviewer(self):
        candidate = self.submit("unbound reviewer")
        self.sql("DELETE FROM lavlah.reviewer_login_bindings WHERE user_id=%s", (self.reviewer,))
        with self.assertRaisesRegex(IngestionError, "Atomic review denied"):
            self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.ingestion_reviews WHERE candidate_id=%s",
                                  (candidate,)), [])

    def test_binding_and_internal_review_privileges(self):
        for role in ("lavlah_ingestion_reviewer", "lavlah_review_test", "lavlah_request",
                     "lavlah_ingestion", "lavlah_identity"):
            with self.subTest(role=role):
                rows = self.sql("""
                    SELECT has_table_privilege(%s,'lavlah.reviewer_login_bindings',
                                               'SELECT, INSERT, UPDATE, DELETE, TRUNCATE'),
                           has_function_privilege(%s,'lavlah.atomic_review_internal(uuid,uuid,boolean,text)',
                                                  'EXECUTE')
                """, (role, role))
                self.assertEqual(rows, [(False, False)])

    def test_reviewer_database_disables_prepared_transactions(self):
        with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
            self.assertEqual(reviewer.execute("SHOW max_prepared_transactions").fetchone(), ("0",))
            with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
                reviewer.execute("PREPARE TRANSACTION 'lavlah_ci_prepared_disabled'")
            reviewer.rollback()

    def test_reviewer_group_and_publication_owner_are_nologin(self):
        rows = self.sql("""
            SELECT rolname, rolcanlogin
            FROM pg_roles
            WHERE rolname IN ('lavlah_ingestion_reviewer', 'lavlah_publication_owner')
            ORDER BY rolname
        """)
        self.assertEqual(rows, [
            ("lavlah_ingestion_reviewer", False),
            ("lavlah_publication_owner", False),
        ])

    def _raw_review(self, conn, candidate, approve=True):
        return conn.execute(
            "SELECT lavlah.atomic_review(%s,%s,%s,'synthetic transaction check')",
            (candidate, self.reviewer, approve),
        ).fetchone()[0]

    def _wait_for_blocker(self, waiter, holder):
        from time import monotonic, sleep

        deadline = monotonic() + 4
        while monotonic() < deadline:
            if self.sql("SELECT %s = ANY(pg_blocking_pids(%s))", (holder, waiter))[0][0]:
                return
            sleep(0.025)
        self.fail(f"PostgreSQL backend {waiter} did not wait for {holder}")

    def _assert_no_review_writes(self, candidate):
        self.assertEqual(self.sql("""
            SELECT
                EXISTS(SELECT 1 FROM lavlah.ingestion_reviews WHERE candidate_id=%s),
                EXISTS(SELECT 1 FROM lavlah.publication_audit WHERE candidate_id=%s),
                EXISTS(SELECT 1 FROM lavlah.public_listings WHERE organization_id=%s),
                EXISTS(SELECT 1 FROM lavlah.sources WHERE organization_id=%s AND id<>%s)
        """, (candidate, candidate, self.org, self.org, identifier(202))), [(False, False, False, False)])

    def test_binding_revocation_commits_before_waiting_review(self):
        candidate = self.submit("admin revokes first")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with psycopg.connect(self.dsn) as admin, psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
                admin.execute("DELETE FROM lavlah.reviewer_login_bindings WHERE user_id=%s", (self.reviewer,))
                reviewer.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                reviewer.execute("SET LOCAL statement_timeout='6s'")
                future = pool.submit(self._raw_review, reviewer, candidate)
                self._wait_for_blocker(reviewer.info.backend_pid, admin.info.backend_pid)
                admin.commit()
                with self.assertRaisesRegex(psycopg.errors.InsufficientPrivilege, "identity binding"):
                    future.result(timeout=7)
                reviewer.rollback()
        self._assert_no_review_writes(candidate)

    def test_binding_revocation_waits_for_review_commit(self):
        candidate = self.submit("review locks first")
        next_candidate = self.submit("review after revocation")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with psycopg.connect(self.dsn) as admin, psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
                reviewer.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                self.assertIsNotNone(self._raw_review(reviewer, candidate))
                admin.execute("SET LOCAL statement_timeout='6s'")
                future = pool.submit(
                    admin.execute, "DELETE FROM lavlah.reviewer_login_bindings WHERE user_id=%s", (self.reviewer,)
                )
                self._wait_for_blocker(admin.info.backend_pid, reviewer.info.backend_pid)
                reviewer.commit()
                self.assertEqual(future.result(timeout=7).rowcount, 1)
                admin.commit()
        self.assertEqual(
            self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s", (candidate,)),
            [("approved",)],
        )
        with self.assertRaisesRegex(IngestionError, "Atomic review denied"):
            self.review(next_candidate)

    def test_stale_transaction_snapshots_fail_closed(self):
        for isolation in ("REPEATABLE READ", "SERIALIZABLE"):
            with self.subTest(isolation=isolation):
                candidate = self.submit(f"old snapshot {isolation}")
                with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
                    reviewer.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
                    reviewer.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                    reviewer.execute("SELECT count(*) FROM lavlah.ingestion_candidates").fetchone()
                    self.sql("DELETE FROM lavlah.reviewer_login_bindings WHERE user_id=%s", (self.reviewer,))
                    with self.assertRaisesRegex(psycopg.errors.InsufficientPrivilege, "READ COMMITTED"):
                        self._raw_review(reviewer, candidate)
                    reviewer.rollback()
                self._assert_no_review_writes(candidate)
                self.sql("""INSERT INTO lavlah.reviewer_login_bindings(login_oid,login_name,user_id)
                            SELECT oid,rolname,%s FROM pg_roles WHERE rolname='lavlah_review_test'""",
                         (self.reviewer,))

    def test_permission_expiry_at_commit_rolls_back_atomic_review(self):
        candidate = self.submit("permission expires after review")
        [(expiry,)] = self.sql("""
            UPDATE lavlah.ingestion_permissions SET valid_until=clock_timestamp()+interval '3 seconds'
            WHERE id=%s RETURNING valid_until
        """, (self.pid,))
        with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
            reviewer.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
            self.assertIsNone(self._raw_review(reviewer, candidate, approve=False))
            reviewer.execute("SELECT pg_sleep_until(%s)", (expiry,))
            with self.assertRaisesRegex(psycopg.errors.InsufficientPrivilege, "authorization no longer valid"):
                reviewer.commit()
        self._assert_no_review_writes(candidate)

    def test_source_expiry_at_commit_rolls_back_publication(self):
        candidate = self.submit("source expires after review")
        [(expiry,)] = self.sql("""
            UPDATE lavlah.ingestion_candidates
            SET observed_at=clock_timestamp()-interval '1 day'+interval '3 seconds'
            WHERE id=%s RETURNING observed_at+interval '1 day'
        """, (candidate,))
        with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
            reviewer.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
            self.assertIsNotNone(self._raw_review(reviewer, candidate))
            reviewer.execute("SELECT pg_sleep_until(%s)", (expiry,))
            with self.assertRaisesRegex(psycopg.errors.InsufficientPrivilege, "source expired"):
                reviewer.commit()
        self._assert_no_review_writes(candidate)

    def test_role_membership_revocation_before_commit(self):
        candidate = self.submit("database role revoked")
        with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as reviewer:
            reviewer.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
            self.assertIsNotNone(self._raw_review(reviewer, candidate))
            self.sql("REVOKE lavlah_ingestion_reviewer FROM lavlah_review_test")
            try:
                with self.assertRaisesRegex(psycopg.errors.InsufficientPrivilege, "authorization no longer valid"):
                    reviewer.commit()
            finally:
                self.sql("GRANT lavlah_ingestion_reviewer TO lavlah_review_test")
        self._assert_no_review_writes(candidate)

    def test_older_review_waiting_on_organization_sees_new_publication(self):
        older, newer = self.submit("older observation"), self.submit("newer observation")
        other_permission = uuid4()
        self.sql("""
            INSERT INTO lavlah.ingestion_permissions
                (id, organization_id, source_url, evidence, granted_by, valid_until, freshness_days)
            SELECT %s, organization_id, source_url, evidence, granted_by, valid_until, freshness_days
            FROM lavlah.ingestion_permissions WHERE id=%s
        """, (other_permission, self.pid))
        self.addCleanup(self.sql, "DELETE FROM lavlah.ingestion_permissions WHERE id=%s", (other_permission,))
        self.sql("INSERT INTO lavlah.ingestion_actor_grants VALUES (%s,%s,'review')",
                 (other_permission, self.reviewer))
        self.addCleanup(self.sql, "DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s",
                        (other_permission,))
        self.sql("""
            UPDATE lavlah.ingestion_candidates
            SET permission_id=%s, observed_at=clock_timestamp()-interval '1 hour' WHERE id=%s
        """, (other_permission, older))
        self.addCleanup(self.sql, "UPDATE lavlah.ingestion_candidates SET permission_id=%s WHERE id=%s",
                        (self.pid, older))
        self.addCleanup(self.sql, "DELETE FROM lavlah.publication_audit WHERE candidate_id=%s", (older,))

        with ThreadPoolExecutor(max_workers=1) as pool:
            with (
                psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as first,
                psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as second,
            ):
                first.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                second.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                second.execute("SET LOCAL statement_timeout='6s'")
                self.assertIsNotNone(self._raw_review(first, newer))
                future = pool.submit(self._raw_review, second, older)
                self._wait_for_blocker(second.info.backend_pid, first.info.backend_pid)
                first.commit()
                with self.assertRaisesRegex(psycopg.errors.InsufficientPrivilege, "Stale or invalid observation"):
                    future.result(timeout=7)
                second.rollback()

        self.assertEqual(
            self.sql("SELECT name FROM lavlah.public_listings WHERE organization_id=%s", (self.org,)),
            [("newer observation",)],
        )
