#!/bin/sh
set -eu
export LC_ALL=C

[ "$#" -eq 3 ] || exit 64

base_image="$1"
time_package="$2"
util_linux_package="$3"

reject_control_characters() {
    case "$1" in
        *[![:print:]]*) return 1 ;;
        *) return 0 ;;
    esac
}

reject_control_characters "$base_image"
reject_control_characters "$time_package"
reject_control_characters "$util_linux_package"

printf '%s\n' "$base_image" \
    | grep -Eq '^([A-Za-z0-9][A-Za-z0-9._:/-]*@)?sha256:[0-9a-f]{64}$'
printf '%s\n' "$time_package" \
    | grep -Eq '^time=[A-Za-z0-9][A-Za-z0-9.+:~_-]*$'
printf '%s\n' "$util_linux_package" \
    | grep -Eq '^util-linux=[A-Za-z0-9][A-Za-z0-9.+:~_-]*$'
