#!/usr/bin/env bash
# Rebuild and prove the local Supabase stack before DB-backed CI starts.
set -euo pipefail

diagnostics_dir="${MANZIL_SUPABASE_DIAGNOSTICS:-${RUNNER_TEMP:-/tmp}/manzil-supabase-ci-diagnostics}"
mkdir -p "$diagnostics_dir"

is_post_seed_health_race() {
  local log_file="$1"
  grep -Eiq 'Restarting containers' "$log_file" &&
    grep -Eiq '(502([^0-9]|$)|bad gateway|storage[^[:cntrl:]]*(timed out|timeout)|kong[^[:cntrl:]]*(timed out|timeout))' "$log_file"
}

if [[ "${1:-}" == "--classify-log" ]]; then
  is_post_seed_health_race "$2"
  exit $?
fi

collect_diagnostics() {
  local label="$1"
  local target="$diagnostics_dir/$label"
  mkdir -p "$target"

  set +e
  supabase status -o json 2>&1 | jq '
    del(
      .ANON_KEY,
      .SERVICE_ROLE_KEY,
      .JWT_SECRET,
      .S3_PROTOCOL_ACCESS_KEY_ID,
      .S3_PROTOCOL_ACCESS_KEY_SECRET
    )
  ' > "$target/status.json"
  docker ps -a --filter 'name=supabase_' \
    --format '{{.Names}}\t{{.Status}}\t{{.Image}}' > "$target/containers.txt" 2>&1

  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    docker inspect --format '{{json .State.Health}}' "$container" \
      > "$target/${container}-health.json" 2>&1
  done < <(docker ps -a --filter 'name=supabase_' --format '{{.Names}}')

  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    docker logs --tail 200 "$container" > "$target/${container}.log" 2>&1
  done < <(
    docker ps -a --filter 'name=supabase_' --format '{{.Names}}' |
      grep -E '^supabase_(storage|kong)_' || true
  )
  set -e
}

run_reset() {
  local attempt="$1"
  local log_file="$diagnostics_dir/reset-attempt-${attempt}.log"
  set +e
  supabase db reset --yes 2>&1 | tee "$log_file"
  local reset_status="${PIPESTATUS[0]}"
  set -e
  return "$reset_status"
}

wait_for_stack() {
  local deadline=$((SECONDS + 90))
  local status_json api_url anon_key db_container
  while (( SECONDS < deadline )); do
    status_json="$(supabase status -o json 2>/dev/null || true)"
    api_url="$(jq -er '.API_URL' <<<"$status_json" 2>/dev/null || true)"
    anon_key="$(jq -er '.ANON_KEY' <<<"$status_json" 2>/dev/null || true)"
    db_container="$(
      docker ps --filter 'name=supabase_db_' --format '{{.Names}}' 2>/dev/null |
        head -n 1
    )"

    if [[ -n "$api_url" && -n "$anon_key" && -n "$db_container" ]] &&
      docker exec "$db_container" pg_isready -U postgres >/dev/null 2>&1 &&
      curl --fail --silent --show-error --max-time 3 \
        -H "apikey: $anon_key" "$api_url/auth/v1/health" >/dev/null &&
      curl --fail --silent --show-error --max-time 3 \
        -H "apikey: $anon_key" "$api_url/rest/v1/" >/dev/null &&
      curl --fail --silent --show-error --max-time 3 \
        -H "apikey: $anon_key" "$api_url/storage/v1/status" >/dev/null; then
      printf '%s' "$status_json"
      return 0
    fi
    sleep 2
  done
  return 1
}

echo "Starting local Supabase stack"
if ! supabase start; then
  collect_diagnostics "start-failed"
  exit 1
fi

if ! run_reset 1; then
  if ! is_post_seed_health_race "$diagnostics_dir/reset-attempt-1.log"; then
    echo "::error::Supabase reset failed before the recognized post-seed health race; not retrying."
    collect_diagnostics "reset-failed"
    exit 1
  fi

  echo "::warning::Post-seed Storage/Kong health race detected; capturing diagnostics and retrying once."
  collect_diagnostics "before-retry"
  supabase stop --no-backup
  supabase start
  if ! run_reset 2; then
    echo "::error::Supabase reset retry failed."
    collect_diagnostics "retry-failed"
    exit 1
  fi
fi

if ! ready_status="$(wait_for_stack)"; then
  echo "::error::Supabase did not make Postgres, Auth/PostgREST, and Storage ready within 90 seconds."
  collect_diagnostics "readiness-failed"
  exit 1
fi

if [[ -z "${GITHUB_ENV:-}" ]]; then
  echo "::error::GITHUB_ENV is required; this script is for GitHub Actions setup."
  exit 1
fi

jq -er '
  "SUPABASE_URL=\(.API_URL)",
  "SUPABASE_ANON_KEY=\(.ANON_KEY)",
  "SUPABASE_SERVICE_ROLE_KEY=\(.SERVICE_ROLE_KEY)",
  "DATABASE_URL=\(.DB_URL)"
' <<<"$ready_status" >> "$GITHUB_ENV"

echo "Supabase Postgres, Auth/PostgREST, and Storage are ready."
