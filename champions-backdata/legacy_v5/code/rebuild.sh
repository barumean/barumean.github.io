#!/usr/bin/env bash
# Champions 싱글 메타 — 전체 재생성. 이 스크립트가 있는 디렉터리에서 실행하세요.
set -euo pipefail
cd "$(dirname "$0")"
echo "[0/5] 입력 확인"
for f in raw2/dex2.json raw2/teams2.txt tier_new.txt mvraw/usage_raw.json \
         mv100.json power100.json mega.json megastats.json chart.json; do
  [ -f "$f" ] || { echo "  입력 누락: $f   (input/ 과 input/seed/ 를 이 디렉터리로 복사했는지 확인하세요)"; exit 1; }
done
echo "[1/5] 원본 → 가공"
node build2.mjs      # data100/stats100/mv100/power100/allmoves100/usage100/stonerate 생성
# (usage.mjs 는 build2.mjs 에 흡수되어 폐기되었습니다 — 실행하면 usage100.json 을 옛 형식으로 덮어씁니다)
node oppw2.mjs
echo "[2/5] 모델 행렬  (config.mjs의 CANON 하나만 사용)"
node mkv2.mjs
echo "[3/5] 조합 탐색 + 내시 균형   (opt_mo full 약 8분, nash_mo 각 약 18분 — 전체 1시간 남짓)"
node mkeff.mjs            # 종별 실효 메가 확률 (상대도 한 경기 메가 1회)
node opt_mo.mjs 50        # opt100b.mjs 를 대체 — 상대 메가 반영
node opt_mo.mjs full      # opt_full.mjs 를 대체
node opt_mo.mjs obs       # opt_obs.mjs 를 대체 (관측 풀: 래더 5회 이상)
python3 nash_mo.py 50     # nash100/nash_full/nash_obs.py 를 대체 — 양쪽 다 메가 1회를 수 안에 넣는다
python3 nash_mo.py full
python3 nash_mo.py obs
echo "[4/5] 페이지 블록"
node tk2.mjs
node mkdec.mjs
node mkcmp.mjs
node mkblk.mjs
node mkitem.mjs
node mkmega.mjs
node mkmv.mjs
node mksu.mjs
node mksets.mjs          # 기술 추천기 (setopt.mjs)
node genbucket2.mjs
node gen2.mjs
echo "[5/5] 분석용 CSV·행렬"
node exp.mjs
node decaudit.mjs
node sample_audit.mjs
echo "완료."
