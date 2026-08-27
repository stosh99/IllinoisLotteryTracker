#!/usr/bin/env bash
# Pull database backups from the production VPS to this workstation.
#
# Deliberately a PULL, not a push: the credentials for the offsite copy live
# only here, so a compromised or failed VPS cannot reach, encrypt, or delete
# these files. Each run re-syncs anything missing, so a machine that was
# powered off simply catches up on its next run.
#
# When ILT_BACKUP_GPG_RECIPIENT names a key, each dump is encrypted to that
# public key and the plaintext is removed. Only the public key is needed here,
# so the scheduled job never holds the ability to decrypt. Manifests stay in
# plaintext on purpose: they carry only checksums, row counts, and timestamps,
# and the backup monitoring reads them.
set -euo pipefail

REMOTE="${ILT_BACKUP_REMOTE:-stosh99@66.220.29.98}"
REMOTE_DIR="${ILT_BACKUP_REMOTE_DIR:-/home/stosh99/illinois-lottery-data/backups}"
LOCAL_DIR="${ILT_BACKUP_LOCAL_DIR:-$HOME/backups/scratchoffdata}"
RECIPIENT="${ILT_BACKUP_GPG_RECIPIENT:-}"

mkdir -p "$LOCAL_DIR"

if [ -n "$RECIPIENT" ] && ! gpg --list-keys "$RECIPIENT" >/dev/null 2>&1; then
  echo "$(date --iso-8601=seconds) ERROR: no public key for '$RECIPIENT'" >&2
  exit 1
fi

# A dump already held in encrypted form must not be pulled again; without this
# every run would re-download the plaintext that encryption just removed.
exclude_args=()
for encrypted in "$LOCAL_DIR"/*.dump.gpg; do
  [ -e "$encrypted" ] || continue
  exclude_args+=(--exclude "$(basename "${encrypted%.gpg}")")
done

rsync --archive --ignore-existing --chmod=F600 --timeout=120 \
  "${exclude_args[@]}" \
  -e "ssh -o BatchMode=yes -o ConnectTimeout=15" \
  "${REMOTE}:${REMOTE_DIR}/" "${LOCAL_DIR}/"

verify_against_manifest() {
  python3 - "$1" <<'PYTHON'
import hashlib
import json
import sys
from pathlib import Path

dump = Path(sys.argv[1])
manifest = json.loads(dump.with_suffix(".dump.manifest.json").read_text(encoding="utf-8"))
digest = hashlib.sha256()
with dump.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
if digest.hexdigest() != manifest["dump_sha256"]:
    print(f"checksum mismatch for {dump.name}", file=sys.stderr)
    raise SystemExit(1)
print(f"{dump.name} verified ({manifest['dump_bytes']} bytes, {manifest['migration_revision']})")
PYTHON
}

pulled=0
encrypted_now=0
for dump in "$LOCAL_DIR"/*.dump; do
  [ -e "$dump" ] || continue
  pulled=$((pulled + 1))
  # Verify the transfer before encrypting, so a truncated copy is caught here
  # rather than during a restore emergency.
  if ! verify_against_manifest "$dump"; then
    echo "$(date --iso-8601=seconds) ERROR: checksum verification failed for $(basename "$dump")" >&2
    exit 1
  fi
  [ -n "$RECIPIENT" ] || continue

  target="${dump}.gpg"
  gpg --batch --yes --trust-model always --recipient "$RECIPIENT" \
    --output "$target" --encrypt "$dump"
  if [ ! -s "$target" ]; then
    echo "$(date --iso-8601=seconds) ERROR: encryption produced no output for $(basename "$dump")" >&2
    rm -f "$target"
    exit 1
  fi
  chmod 600 "$target"
  rm -f "$dump"
  encrypted_now=$((encrypted_now + 1))
done

held=$(find "$LOCAL_DIR" -maxdepth 1 \( -name '*.dump' -o -name '*.dump.gpg' \) | wc -l)
if [ "$held" -eq 0 ]; then
  echo "$(date --iso-8601=seconds) ERROR: no backups present in ${LOCAL_DIR}" >&2
  exit 1
fi
state=$([ -n "$RECIPIENT" ] && echo "encrypted to ${RECIPIENT}" || echo "UNENCRYPTED")
echo "$(date --iso-8601=seconds) OK: ${held} backup(s) held in ${LOCAL_DIR} (${state}); \
${pulled} verified this run, ${encrypted_now} newly encrypted"
