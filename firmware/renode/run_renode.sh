#!/usr/bin/env bash
# Run the firmware in Renode headless and leave the CSV in results/renode_run.log.
#   RENODE=/path/to/renode ./firmware/renode/run_renode.sh [build-dir]
set -euo pipefail
cd "$(dirname "$0")/../.."
RENODE=${RENODE:-renode}
BUILD=${1:-build/renode}
LOG=results/renode_run.log
[ -f "$BUILD/ecg_edge.elf" ] || { echo "missing $BUILD/ecg_edge.elf - build with -DECG_TARGET=renode (see README)"; exit 1; }
rm -f "$LOG"
# 'platforms/...' is resolved relative to the Renode installation, our files relative to the repo.
"$RENODE" --disable-xwt --console --plain \
    -e "\$bin=@$PWD/$BUILD/ecg_edge.elf; \$log=@$PWD/$LOG; include @$PWD/firmware/renode/ecg_edge.resc"
echo "log: $LOG ($(wc -l < "$LOG") lines); last line: $(tail -n1 "$LOG")"
python3 scripts/validate.py --log "$LOG" --label renode || true
