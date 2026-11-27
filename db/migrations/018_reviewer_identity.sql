BEGIN;

-- Provision one dedicated database login per reviewer. Store the catalog OID
-- alongside the name so a dropped and recreated login requires re-provisioning.
CREATE TABLE lavlah.reviewer_login_bindings (
    login_oid oid PRIMARY KEY,
    login_name name NOT NULL UNIQUE,
    user_id uuid NOT NULL UNIQUE REFERENCES lavlah.users(id) ON DELETE CASCADE
);
REVOKE ALL ON lavlah.reviewer_login_bindings FROM PUBLIC, lavlah_ingestion_reviewer;
GRANT SELECT ON lavlah.reviewer_login_bindings TO lavlah_publication_owner;

ALTER FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) RENAME TO atomic_review_internal;
REVOKE EXECUTE ON FUNCTION lavlah.atomic_review_internal(uuid,uuid,boolean,text)
    FROM PUBLIC, lavlah_ingestion_reviewer;

CREATE FUNCTION lavlah.atomic_review(cid uuid, actor uuid, approve boolean, evidence_text text)
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

GRANT CREATE ON SCHEMA lavlah TO lavlah_publication_owner;
ALTER FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) OWNER TO lavlah_publication_owner;
REVOKE CREATE ON SCHEMA lavlah FROM lavlah_publication_owner;
REVOKE ALL ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) TO lavlah_ingestion_reviewer;

COMMIT;
