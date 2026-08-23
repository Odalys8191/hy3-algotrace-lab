#!/bin/sh
# Full-history local companion to the SHA-pinned CI Gitleaks action.
set -eu

if ! command -v gitleaks >/dev/null 2>&1; then
    printf '%s\n' 'gitleaks is required for full-history security scanning' >&2
    exit 69
fi

exec gitleaks detect --source . --log-opts="--all" --redact --config .gitleaks.toml --no-banner
