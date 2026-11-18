#!/usr/bin/env bash
# Roda toda a Parte 2 (na raiz do repo, com `docker compose up -d --build` já no ar).
set -e
cd "$(dirname "$0")"
mkdir -p results
python functional.py
python load.py 10 3
cd ../..
python tests/part2/faults.py market-service 15
python tests/part2/faults.py auth-service 15
docker compose stop npc-service && sleep 5 && docker compose start npc-service
docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' > tests/part2/results/docker_stats.csv
python tests/part2/report.py
