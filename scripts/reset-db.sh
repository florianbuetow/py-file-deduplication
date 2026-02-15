#!/usr/bin/env bash
# Reset (delete) the database after user confirmation.
# Reads the database path from config.yaml.
set -euo pipefail

db_path=$(grep '^database:' config.yaml | sed 's/^database: *"\(.*\)"/\1/')

if [ -z "$db_path" ]; then
    printf "\033[0;31m✗ Could not read database path from config.yaml\033[0m\n"
    exit 1
fi

if [ ! -f "$db_path" ]; then
    printf "\033[0;33mNo database file found at %s — nothing to delete\033[0m\n" "$db_path"
    exit 0
fi

printf "This will permanently delete the database at %s\n" "$db_path"
printf "Type 'destroy' to confirm: "
read -r confirmation

if [ "$confirmation" != "destroy" ]; then
    printf "\n"
    printf "\033[0;33m✗ Reset cancelled\033[0m\n"
    exit 1
fi

rm -f "$db_path"
printf "\n"
printf "\033[0;32m✓ Database deleted\033[0m\n"
