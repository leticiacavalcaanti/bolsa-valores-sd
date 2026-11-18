#!/usr/bin/env bash
# Roda toda a bateria do DFS (em dfs/, com `docker compose up -d --build` no ar). ~40 min.
set -x
export MSYS_NO_PATHCONV=1 PYTHONIOENCODING=utf-8
cd "$(dirname "$0")/.."
D="docker compose run --rm -T --entrypoint python client /tests/perf.py"
$D e2
$D e3
python tests/recovery.py e9
python tests/recovery.py e7
python tests/recovery.py e8
python tests/functional.py
python tests/plots.py
python tests/report.py
