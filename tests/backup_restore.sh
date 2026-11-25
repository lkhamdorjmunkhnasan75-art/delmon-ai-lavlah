#!/usr/bin/env bash
set -euo pipefail
# Disposable CI server only. No production database access.
[[ "${PGHOST:-}" == localhost && "${PGDATABASE:-}" == postgres && "${PGUSER:-}" == postgres ]]
# Use the same PostgreSQL major version as the disposable service.
server_version=$(psql -X -At -v ON_ERROR_STOP=1 -c 'SHOW server_version_num')
major=$((server_version / 10000))
[[ "$major" == 16 ]]
# ubuntu-latest may ship a newer client. Use the service image's own tools.
container_id=$(docker ps --filter ancestor=postgres:16 --format '{{.ID}}')
[[ "$container_id" =~ ^[a-f0-9]+$ ]]
pg_dump() {
  docker exec -e PGPASSWORD="$PGPASSWORD" "$container_id" pg_dump -h 127.0.0.1 -U "$PGUSER" -d "$PGDATABASE" "$@"
}
pg_restore() {
  docker exec -i -e PGPASSWORD="$PGPASSWORD" "$container_id" pg_restore -h 127.0.0.1 -U "$PGUSER" "$@"
}
docker exec "$container_id" pg_dump --version
docker exec "$container_id" pg_restore --version
work=$(mktemp -d)
target="lavlah_restore_${RANDOM}_$$"
trap 'dropdb --if-exists "$target"; rm -rf "$work"' EXIT
pg_dump --format=custom --schema=lavlah > "$work/backup.dump"
sha256sum "$work/backup.dump" > "$work/backup.sha256"
sha256sum --check "$work/backup.sha256"
createdb "$target"
pg_restore --exit-on-error --dbname="$target" < "$work/backup.dump"
psql -X -At -v ON_ERROR_STOP=1 -c "SELECT tablename FROM pg_tables WHERE schemaname='lavlah' ORDER BY tablename" > "$work/tables"
while IFS= read -r table; do
  [[ "$table" =~ ^[a-z_]+$ ]]
  for db in postgres "$target"; do
    psql -X -At -v ON_ERROR_STOP=1 -d "$db" -c "SELECT md5(row_to_json(t)::text) FROM lavlah.$table t ORDER BY 1" > "$work/$db.rows"
  done
  diff "$work/postgres.rows" "$work/$target.rows"
done < "$work/tables"
# Compare sequence state and schema ACL/RLS metadata, not merely row content.
for db in postgres "$target"; do
  psql -X -At -v ON_ERROR_STOP=1 -d "$db" -c "SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='lavlah' ORDER BY sequencename" > "$work/$db.seq"
  psql -X -At -v ON_ERROR_STOP=1 -d "$db" -c "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity,coalesce(c.relacl::text,'') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='lavlah' AND c.relkind IN ('r','v','S') ORDER BY c.relname" > "$work/$db.acl"
  psql -X -At -v ON_ERROR_STOP=1 -d "$db" -c "SELECT tablename,policyname,permissive,roles,cmd,qual,with_check FROM pg_policies WHERE schemaname='lavlah' ORDER BY tablename,policyname" > "$work/$db.policies"
done
for kind in seq acl policies; do diff "$work/postgres.$kind" "$work/$target.$kind"; done
psql -X -v ON_ERROR_STOP=1 -d "$target" <<'SQL'
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM lavlah.https_observations WHERE scheduler_run_id IS NOT NULL) THEN RAISE EXCEPTION 'missing run provenance'; END IF;
 IF has_table_privilege('lavlah_public_reader','lavlah.https_scheduler_runs','SELECT') THEN RAISE EXCEPTION 'private runs exposed'; END IF;
 IF NOT has_table_privilege('lavlah_ingestion','lavlah.scheduler_alerts','SELECT') THEN RAISE EXCEPTION 'missing alert grant'; END IF;
 IF NOT EXISTS (SELECT 1 FROM lavlah.publication_audit) OR NOT EXISTS (SELECT 1 FROM lavlah.mock_callbacks) OR NOT EXISTS (SELECT 1 FROM lavlah.chat_usage) OR NOT EXISTS (SELECT 1 FROM lavlah.chat_feedback) THEN RAISE EXCEPTION 'missing populated audit fixtures'; END IF;
 IF has_table_privilege('lavlah_public_reader','lavlah.chat_usage','SELECT') OR has_table_privilege('lavlah_public_reader','lavlah.mock_callbacks','SELECT') OR has_table_privilege('lavlah_public_reader','lavlah.publication_audit','SELECT') THEN RAISE EXCEPTION 'private journal exposed'; END IF;
 IF has_table_privilege('lavlah_ingestion_reviewer','lavlah.publication_audit','DELETE') OR has_table_privilege('lavlah_mock_billing','lavlah.mock_callbacks','UPDATE') OR has_table_privilege('lavlah_request','lavlah.chat_usage','DELETE') THEN RAISE EXCEPTION 'journal mutation privilege'; END IF;
END $$;
SQL
echo "Backup/restore table data and selected ACL checks passed"
echo "Populated journals, sequence values and RLS metadata restore passed"
