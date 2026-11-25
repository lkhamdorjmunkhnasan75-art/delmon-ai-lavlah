BEGIN;
CREATE TABLE lavlah.chat_usage (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES lavlah.users(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 outcome text NOT NULL CHECK(outcome IN ('matched','clarify','no_result')),
 estimated_micro_mnt integer NOT NULL CHECK(estimated_micro_mnt BETWEEN 0 AND 70000),
 UNIQUE(id,user_id)
);
CREATE INDEX chat_usage_actor_time ON lavlah.chat_usage(user_id,created_at);
CREATE TABLE lavlah.chat_feedback (
 usage_id uuid PRIMARY KEY,
 user_id uuid NOT NULL,
 rating smallint NOT NULL CHECK(rating IN (-1,1)),
 FOREIGN KEY(usage_id,user_id) REFERENCES lavlah.chat_usage(id,user_id)
);
ALTER TABLE lavlah.chat_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE lavlah.chat_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY chat_usage_own ON lavlah.chat_usage TO lavlah_request USING (user_id=lavlah.request_user_id()) WITH CHECK(user_id=lavlah.request_user_id());
CREATE POLICY chat_feedback_own ON lavlah.chat_feedback TO lavlah_request USING (user_id=lavlah.request_user_id()) WITH CHECK(user_id=lavlah.request_user_id());
REVOKE ALL ON lavlah.chat_usage,lavlah.chat_feedback FROM PUBLIC;
GRANT SELECT,INSERT ON lavlah.chat_usage,lavlah.chat_feedback TO lavlah_request;
GRANT UPDATE(rating) ON lavlah.chat_feedback TO lavlah_request;
COMMIT;
