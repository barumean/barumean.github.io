#!/usr/bin/env bash
# 패키지 루트에서 실행. 매니페스트는 자기 자신을 포함하지 않는다(검증 시 항상 불일치하므로).
set -euo pipefail
cd "$(dirname "$0")"
rm -f MANIFEST.sha256
find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum > MANIFEST.sha256
echo "MANIFEST.sha256: $(wc -l < MANIFEST.sha256)개 파일"
