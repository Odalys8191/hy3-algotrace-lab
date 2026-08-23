#!/bin/sh
set -eu
export LC_ALL=C

mode="${1:-}"

case "$mode" in
    compile)
        [ "$#" -eq 3 ] || exit 64
        exec /usr/bin/timeout --signal=KILL 15 \
            /usr/local/bin/g++ -std=c++17 -O2 -pipe "$2" -o "$3"
        ;;
    run)
        [ "$#" -eq 3 ] || exit 64
        program="$2"
        input_file="$3"
        exec "$program" < "$input_file"
        ;;
    *)
        exit 64
        ;;
esac
