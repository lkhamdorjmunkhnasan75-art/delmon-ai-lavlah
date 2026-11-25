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
psql -X -v ON_ERROR_STOP=1 -d "$target" <<'SQL'
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM lavlah.https_observations WHERE scheduler_run_id IS NOT NULL) THEN RAISE EXCEPTION 'missing run provenance'; END IF;
 IF has_table_privilege('lavlah_public_reader','lavlah.https_scheduler_runs','SELECT') THEN RAISE EXCEPTION 'private runs exposed'; END IF;
 IF NOT has_table_privilege('lavlah_ingestion','lavlah.scheduler_alerts','SELECT') THEN RAISE EXCEPTION 'missing alert grant'; END IF;
END $$;
SQL
echo "Backup/restore table data and selected ACL checks passed"
