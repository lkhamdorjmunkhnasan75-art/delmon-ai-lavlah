BEGIN;
DROP TRIGGER review_authorization_at_commit ON lavlah.ingestion_reviews;
DROP FUNCTION lavlah.check_review_at_commit();
REVOKE UPDATE (user_id) ON lavlah.reviewer_login_bindings FROM lavlah_publication_owner;

CREATE OR REPLACE FUNCTION lavlah.atomic_review(cid uuid, actor uuid, approve boolean, evidence_text text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    bound_actor uuid;
BEGIN
    SELECT binding.user_id INTO bound_actor
    FROM lavlah.reviewer_login_bindings AS binding
    JOIN pg_roles AS login ON login.oid=binding.login_oid AND login.rolname=binding.login_name
    WHERE login.rolname=session_user AND login.rolcanlogin;

    IF bound_actor IS NULL OR bound_actor IS DISTINCT FROM actor THEN
        RAISE EXCEPTION 'Reviewer identity binding required' USING ERRCODE='42501';
    END IF;

    RETURN lavlah.atomic_review_internal(cid,bound_actor,approve,evidence_text);
END;
$$;

COMMIT;
