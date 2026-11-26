#!/usr/bin/env bash
set -euo pipefail
# Only the disposable CI service is permitted.
[[ "${CI:-}" == true && "${GITHUB_ACTIONS:-}" == true ]]
[[ "${PGHOST:-}" == localhost && "${PGDATABASE:-}" == postgres && "${PGUSER:-}" == postgres ]]
expected='postgres:16@sha256:07abc3f43c9395b0bdbbab36bc25ddb0e8d83cd4fcafb5fb7d6abe14ff156dd8'
[[ "${LAVLAH_POSTGRES_IMAGE:-}" == "$expected" ]]
image_id=$(docker image inspect --format '{{.Id}}' "$expected")
[[ "$image_id" =~ ^sha256:[a-f0-9]{64}$ ]]
container=$(docker ps --filter "ancestor=$expected" --format '{{.ID}}')
[[ "$container" =~ ^[a-f0-9]+$ ]]
[[ "$(docker inspect --format '{{.Image}}' "$container")" == "$image_id" ]]
printf '%s\n' "$container"
