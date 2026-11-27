BEGIN;

-- PostgreSQL requires UPDATE privilege on at least one column for FOR SHARE.
-- The NOLOGIN publication owner has no service-role members.
GRANT UPDATE (user_id) ON lavlah.reviewer_login_bindings TO lavlah_publication_owner;

CREATE OR REPLACE FUNCTION lavlah.atomic_review(cid uuid, actor uuid, approve boolean, evidence_text text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    bound_actor uuid;
BEGIN
    -- The publication ordering checks need fresh snapshots after lock waits.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Review requires READ COMMITTED' USING ERRCODE='42501';
    END IF;

    SELECT binding.user_id INTO bound_actor
    FROM lavlah.reviewer_login_bindings AS binding
    JOIN pg_roles AS login ON login.oid=binding.login_oid AND login.rolname=binding.login_name
    WHERE login.rolname=session_user AND login.rolcanlogin
      AND pg_has_role(login.oid, 'lavlah_ingestion_reviewer', 'MEMBER')
    FOR SHARE OF binding;

    IF bound_actor IS NULL OR bound_actor IS DISTINCT FROM actor THEN
        RAISE EXCEPTION 'Reviewer identity binding required' USING ERRCODE='42501';
    END IF;

    RETURN lavlah.atomic_review_internal(cid,bound_actor,approve,evidence_text);
END;
$$;

-- Queue checks for the atomic publication path only. Administrative imports
-- and restoration of historical rows have their own trust boundary.
CREATE FUNCTION lavlah.check_review_at_commit()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    pid uuid;
    source_expiry timestamptz;
BEGIN
    SELECT permission_id INTO STRICT pid
    FROM lavlah.ingestion_candidates WHERE id=NEW.candidate_id;

    IF NOT EXISTS (
        SELECT 1
        FROM lavlah.reviewer_login_bindings AS binding
        JOIN pg_roles AS login ON login.oid=binding.login_oid AND login.rolname=binding.login_name
        WHERE login.rolname=session_user AND login.rolcanlogin AND binding.user_id=NEW.reviewer_id
          AND pg_has_role(login.oid, 'lavlah_ingestion_reviewer', 'MEMBER')
    ) OR NOT lavlah.lock_active_permission(pid)
      OR NOT lavlah.lock_actor_grant(pid, NEW.reviewer_id, 'review') THEN
        RAISE EXCEPTION 'Review authorization no longer valid' USING ERRCODE='42501';
    END IF;

    IF NEW.source_id IS NOT NULL THEN
        SELECT expires_at INTO STRICT source_expiry
        FROM lavlah.sources WHERE id=NEW.source_id;
        IF source_expiry <= clock_timestamp() THEN
            RAISE EXCEPTION 'Review source expired' USING ERRCODE='42501';
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

GRANT CREATE ON SCHEMA lavlah TO lavlah_publication_owner;
ALTER FUNCTION lavlah.check_review_at_commit() OWNER TO lavlah_publication_owner;
REVOKE CREATE ON SCHEMA lavlah FROM lavlah_publication_owner;
REVOKE ALL ON FUNCTION lavlah.check_review_at_commit() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER review_authorization_at_commit
AFTER INSERT ON lavlah.ingestion_reviews
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW WHEN (current_user = 'lavlah_publication_owner')
EXECUTE FUNCTION lavlah.check_review_at_commit();

COMMIT;
