#!/usr/bin/env bash
export PATH="$PATH:/usr/sbin:/sbin"
# Stop proxy and test doubles by listening port (avoids pgrep self-match).
for port in 4000 4001 8090 8091; do
  for p in $(ss -lptnH "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | sort -u); do
    kill "$p" 2>/dev/null && echo "stopped pid $p (:$port)"
  done
done
sleep 1
