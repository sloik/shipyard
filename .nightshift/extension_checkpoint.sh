#!/bin/sh
# Standalone, fail-contained entry point for every official checkpoint call.

set -u

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P) || exit 0
project_root=
run_id=
spec_id=
run_kind=
event=
outcome=unknown
artifact_refs_file=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --project-root|--run-id|--spec-id|--run-kind|--event|--outcome|--artifact-refs-file)
            option=$1
            if [ "$#" -lt 2 ]; then
                shift
                continue
            fi
            value=$2
            shift 2
            case "$option" in
                --project-root) project_root=$value ;;
                --run-id) run_id=$value ;;
                --spec-id) spec_id=$value ;;
                --run-kind) run_kind=$value ;;
                --event) event=$value ;;
                --outcome) outcome=$value ;;
                --artifact-refs-file) artifact_refs_file=$value ;;
            esac
            ;;
        *) shift ;;
    esac
done

if [ -z "$project_root" ]; then
    project_root=$(CDPATH='' cd -- "$script_dir/.." && pwd -P) || exit 0
fi
private_root=${NIGHTSHIFT_EXTENSION_PRIVATE_ROOT:-"$project_root/.nightshift/.extension-private"}
user_root=${NIGHTSHIFT_USER_EXTENSION_ROOT:-"$private_root/disabled-user"}
config_path=${NIGHTSHIFT_CONFIG_PATH:-"$project_root/.nightshift/config.yaml"}

record_failure() {
    mkdir -p -- "$private_root" 2>/dev/null || return 0
    printf '%s\n' '{"reason":"checkpoint-launch-failed","schema_version":"1.0.0"}' >>"$private_root/checkpoint-diagnostics.jsonl" 2>/dev/null || true
}

if [ -z "$run_id" ] || [ -z "$spec_id" ] || [ -z "$run_kind" ] || [ -z "$event" ]; then
    record_failure
    exit 0
fi

python_bin=${NIGHTSHIFT_PYTHON:-python3}
if ! "$python_bin" -c 'import yaml' >/dev/null 2>&1; then
    record_failure
    exit 0
fi

set -- "$python_bin" "$script_dir/extension_checkpoint.py" \
    --project-root "$project_root" --private-root "$private_root" \
    --user-root "$user_root" --run-id "$run_id" --sequence auto \
    --event "$event" --official-config "$config_path" \
    --run-kind "$run_kind" --spec-id "$spec_id" --outcome "$outcome"
if [ -n "${NIGHTSHIFT_EXTENSION_ARTIFACT_ROOT:-}" ]; then
    set -- "$@" --artifact-root "$NIGHTSHIFT_EXTENSION_ARTIFACT_ROOT"
fi
if [ -n "$artifact_refs_file" ]; then
    if [ -z "${NIGHTSHIFT_EXTENSION_ARTIFACT_ROOT:-}" ]; then
        record_failure
        exit 0
    fi
    set -- "$@" --artifact-refs-file "$artifact_refs_file"
fi
"$@"
status=$?
if [ "$status" -ne 0 ]; then
    record_failure
fi
exit 0
