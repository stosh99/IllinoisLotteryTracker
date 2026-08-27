#!/usr/bin/env bash
# Pull database backups from the production VPS to this workstation.
#
# Deliberately a PULL, not a push: the credentials for the offsite copy live
# only here, so a compromised or failed VPS cannot reach, encrypt, or delete
# these files. Each run re-syncs anything missing, so a machine that was
# powered off simply catches up on its next run.
set -euo pipefail

REMOTE="${ILT_BACKUP_REMOTE:-stosh99@66.220.29.98}"
REMOTE_DIR="${ILT_BACKUP_REMOTE_DIR:-/home/stosh99/illinois-lottery-data/backups}"
LOCAL_DIR="${ILT_BACKUP_LOCAL_DIR:-$HOME/backups/scratchoffdata}"

mkdir -p "$LOCAL_DIR"

# --ignore-existing keeps already-pulled dumps immutable here even if the
# remote copy is pruned or altered later.
rsync --archive --ignore-existing --chmod=F600 --timeout=120 \
  -e "ssh -o BatchMode=yes -o ConnectTimeout=15" \
  "${REMOTE}:${REMOTE_DIR}/" "${LOCAL_DIR}/"

newest=$(ls -1t "${LOCAL_DIR}"/*.dump 2>/dev/null | head -1 || true)
if [ -z "$newest" ]; then
  echo "$(date --iso-8601=seconds) ERROR: no dumps present in ${LOCAL_DIR}" >&2
  exit 1
fi

# Verify the newest local copy against its manifest checksum, so a truncated
# transfer is caught here rather than during a restore emergency.
if ! python3 - "$newest" <<'PYTHON'
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
then
  echo "$(date --iso-8601=seconds) ERROR: checksum verification failed" >&2
  exit 1
fi

count=$(ls -1 "${LOCAL_DIR}"/*.dump 2>/dev/null | wc -l)
echo "$(date --iso-8601=seconds) OK: ${count} dump(s) held in ${LOCAL_DIR}"
