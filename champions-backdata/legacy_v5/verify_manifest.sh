#!/usr/bin/env bash
# 배포본 검증. 전부 일치해야 정상이다.
cd "$(dirname "$0")"
if sha256sum -c MANIFEST.sha256 --quiet; then echo "전부 일치 ($(wc -l < MANIFEST.sha256)개 파일)"; else echo "불일치 있음 — 위 목록 확인"; exit 1; fi
