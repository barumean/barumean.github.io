"""Phase 5 보조 — 저장된 행렬(tests/out_phase5_data/*.npz)로 단계 간 차이의 팀 단위 대응 부트스트랩 CI.

실행:  python tests/measure_phase5_paired.py    (measure_phase5.py 를 먼저 실행)
부트스트랩: 팀을 복원추출 5000회, seed 20260927. 팀이 6개뿐이라 구간이 넓다(판정은 방향이 일관된지만).
"""
import glob
import os

import numpy as np

import _common  # noqa: F401
from _fixtures import data, party, SEED
from measure_phase5 import agg_mean, agg_code, sigma_60, lead_opt_value, collapse_leadgame, spearman, TRIS
from champions.game import solve

D = data()
mine = party(D)
files = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_phase5_data", "team_*.npz")))
steps = {"S1": ("VN", agg_mean), "S2": ("VV", agg_mean), "S3": ("VS", agg_mean), "S4": ("VS", agg_code), "S6": ("VL", agg_code)}
res = {k: {"rho": [], "mae": [], "reg": [], "reg_trio": []} for k in steps}
for f in files:
    z = np.load(f)
    M = z["M"]
    vB = solve(M)[0]
    PB = collapse_leadgame(M)
    for k, (vk, agg) in steps.items():
        V = z[vk]
        P = agg(V)
        vA, xA, yA = solve(P)
        res[k]["rho"].append(spearman(P, PB)); res[k]["mae"].append(np.abs(P - PB).mean())
        res[k]["reg"].append(vB - (sigma_60(xA, V, yA, mine) @ M).min())
        res[k]["reg_trio"].append(vB - lead_opt_value(M, xA))
rng = np.random.default_rng(SEED)
n = len(files)
print(f"# Phase 5 단계 간 대응 차이 (팀 {n}개, 팀 부트스트랩 5000회, seed {SEED})\n")
print("| 비교 | 지표 | 평균 차이 | 95% CI | 차이의 부호가 같은 팀 |")
print("|---|---|---|---|---|")
for a, b, lab in (("S1", "S2", "교체 혼합 추가"), ("S2", "S3", "세트 불확실성 추가"), ("S3", "S4", "½max+½min 집계(단순 평균 대비)"),
                  ("S4", "S6", "op.gg 결합 추가"), ("S1", "S4", "S1 → 현재 식(S4)")):
    for m, better in (("rho", "+"), ("mae", "−"), ("reg_trio", "−"), ("reg", "−")):
        d = np.array(res[b][m]) - np.array(res[a][m])
        bs = [d[rng.integers(0, n, n)].mean() for _ in range(5000)]
        same = max((d > 0).sum(), (d < 0).sum())
        print(f"| {lab} ({a}→{b}) | {m} (좋아지는 방향 {better}) | {d.mean():+.3f} | [{np.percentile(bs, 2.5):+.3f}, {np.percentile(bs, 97.5):+.3f}] | {same}/{n} |")
