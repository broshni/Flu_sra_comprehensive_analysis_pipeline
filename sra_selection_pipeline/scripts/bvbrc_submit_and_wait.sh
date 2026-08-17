#!/usr/bin/env bash
#
# Submit a BV-BRC (p3-tools) service job, capture its job id, and block until
# the job reaches a terminal state (complete / failed / etc.), polling
# `p3-job-status` at a fixed interval.
#
# Usage:
#   bvbrc_submit_and_wait.sh <jobid_output_file> <poll_interval_sec> <timeout_sec> <log_file> <submit-command...>
#
# Example:
#   bvbrc_submit_and_wait.sh job_id.txt 30 21600 submit.log \
#       p3-submit-viral-assembly --srr-id SRR36625009 --strategy IRMA /user/home/run assembly
#
# On success, writes the job id to <jobid_output_file> and exits 0.
# On failure (job failed, or timeout reached), exits 1 with a message on stderr.

set -uo pipefail

JOBID_FILE="$1"; shift
POLL_INTERVAL="$1"; shift
TIMEOUT="$1"; shift
LOGFILE="$1"; shift
# Remaining args are the p3-submit-* command and its arguments.

mkdir -p "$(dirname "$JOBID_FILE")" "$(dirname "$LOGFILE")"

echo "=== $(date -u +%FT%TZ) Submitting: $* ===" >> "$LOGFILE"

SUBMIT_OUTPUT="$("$@" 2>&1)"
SUBMIT_STATUS=$?
echo "$SUBMIT_OUTPUT" >> "$LOGFILE"

if [ "$SUBMIT_STATUS" -ne 0 ]; then
    echo "ERROR: job submission command failed (exit $SUBMIT_STATUS). See $LOGFILE" >&2
    exit 1
fi

# Different BV-BRC submission scripts have been observed to report the job
# id in different formats:
#   p3-submit-viral-assembly:  "Submitted assembly with id 23236984" (plain integer)
#   other p3-submit-* tools:   "Job submitted: ace5ad73-db90-49d4-b854-8ab7290abb77" (UUID)
# Try the integer-after-"id" form first (confirmed for p3-submit-viral-assembly),
# then fall back to the UUID form.
JOB_ID="$(echo "$SUBMIT_OUTPUT" | grep -oiE 'id[[:space:]:=]+[0-9]+' | head -n1 | grep -oE '[0-9]+')"

if [ -z "$JOB_ID" ]; then
    JOB_ID="$(echo "$SUBMIT_OUTPUT" | grep -oE '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}' | head -n1)"
fi

if [ -z "$JOB_ID" ]; then
    echo "ERROR: could not find a job id in the submission output. See $LOGFILE" >&2
    exit 1
fi

echo "$JOB_ID" > "$JOBID_FILE"
echo "Job ID: $JOB_ID" >> "$LOGFILE"

ELAPSED=0
while true; do
    STATUS_OUTPUT="$(p3-job-status "$JOB_ID" 2>&1)"
    echo "$(date -u +%FT%TZ) $STATUS_OUTPUT" >> "$LOGFILE"

    # Expected form: "<job-id>: <status>"
    STATUS="$(echo "$STATUS_OUTPUT" | sed -n "s/^${JOB_ID}:[[:space:]]*//p" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"

    case "$STATUS" in
        complete|completed|done)
            echo "Job $JOB_ID completed." >> "$LOGFILE"
            exit 0
            ;;
        failed|fail|error|deleted|suspend|suspended|terminated)
            echo "ERROR: job $JOB_ID ended with status '$STATUS'. See $LOGFILE" >&2
            exit 1
            ;;
        *)
            # queued, running, in-progress, submitted, or unrecognized -- keep waiting
            ;;
    esac

    if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
        echo "ERROR: timed out after ${TIMEOUT}s waiting for job $JOB_ID (last status: '$STATUS'). See $LOGFILE" >&2
        exit 1
    fi

    sleep "$POLL_INTERVAL"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done
