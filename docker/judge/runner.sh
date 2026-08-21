#!/bin/sh
set -eu

mode="${1:-}"

case "$mode" in
    compile)
        [ "$#" -eq 3 ] || exit 64
        exec /usr/bin/timeout --signal=KILL 15 \
            /usr/local/bin/g++ -std=c++17 -O2 -pipe "$2" -o "$3"
        ;;
    run)
        [ "$#" -eq 8 ] || exit 64
        program="$2"
        input_file="$3"
        output_file="$4"
        diagnostics_file="$5"
        metrics_file="$6"
        status_file="$7"
        timeout_seconds="$8"

        set +e
        /usr/bin/time -f '%e %M' -o "$metrics_file" \
            /usr/bin/timeout --signal=KILL "$timeout_seconds" "$program" \
            < "$input_file" > "$output_file" 2> "$diagnostics_file"
        exit_status="$?"
        set -e
        printf '%s\n' "$exit_status" > "$status_file"
        ;;
    *)
        exit 64
        ;;
esac
