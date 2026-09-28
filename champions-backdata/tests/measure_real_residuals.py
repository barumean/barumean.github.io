"""실데이터 solver 출력의 잔차(허용 오차 1e-6): 선출 베이지안 게임(pick.advise 와 같은 입력) + 1:1 계획 게임(duel_stats 의 LP).

실행:  python tests/measure_real_residuals.py [--teams 12] [--pairs 300]
"""
import argparse
import random

import numpy as np

import _common  # noqa: F401
from _common import residuals, ok, bayes_residuals, bayes_ok
from _fixtures import data, party, clean, sample_teams, top_opponents, SEED
from measure_phase4 import internals
from champions.game import solve, solve_bayes
from champions.engine import plan_matrix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=12)
    ap.add_argument("--pairs", type=int, default=300)
    a = ap.parse_args()
    out = lambda s="": print(s, flush=True)
    D = data()
    mine = party(D)
    out("# 실데이터 solver 잔차 (TOL 1e-6)\n")
    keys_ = ["sum_p-1", "min_p", "sum_qt-1", "min_qt", "exploit", "v-L", "type_br_gap"]
    agg = {k: [] for k in keys_}
    nok = 0
    teams = sample_teams(D, a.teams, seed=SEED + 1, exclude_keys=[b.key for b in mine])
    for ti, keys, ob, st in teams:
        Ps, probs, V, tri = internals(D, mine, keys)
        v, x, yd = solve_bayes(Ps, probs)
        r = bayes_residuals(Ps, probs, v, x, yd)
        nok += bayes_ok(r)
        for k in keys_:
            agg[k].append(abs(r[k]) if k not in ("min_p", "min_qt") else r[k])
    out(f"## 선출 베이지안 게임(solve_bayes) — 레플리카 팀 {len(teams)}개(seed {SEED + 1}), 유형 수 = 스톤 조합 수")
    out(f"- 통과 {nok}/{len(teams)}; 최댓값: |Σp−1| {max(agg['sum_p-1']):.1e}, min p {min(agg['min_p']):.1e}, |Σq_t−1| {max(agg['sum_qt-1']):.1e}, "
        f"min q_t {min(agg['min_qt']):.1e}, 착취 U−L {max(agg['exploit']):.1e}, |v−L| {max(agg['v-L']):.1e}, 유형별 최적대응 틈 {max(agg['type_br_gap']):.1e}")
    # 1:1 계획 게임
    builds = [clean(b) for b in mine] + [clean(b) for _, b, _ in top_opponents(D, 60)]
    rnd = random.Random(SEED)
    stats, n_mixed, bad = [], 0, 0
    for _ in range(a.pairs):
        A, B = rnd.sample(builds, 2)
        O, _ = plan_matrix(A, B)
        O = np.asarray(O, float)
        v, x, y = solve(O)
        r = residuals(O, v, x, y)
        stats.append(r)
        n_mixed += (x > 1e-9).sum() > 1 or (y > 1e-9).sum() > 1
        bad += not ok(r)
    out(f"\n## 1:1 계획 게임(game.solve) — 무작위 {a.pairs}쌍(seed {SEED}, 분기 모드 행렬)")
    out(f"- 통과 {a.pairs - bad}/{a.pairs}, 혼합 균형 {n_mixed}쌍; 최댓값: exploit {max(s['exploit'] for s in stats):.1e}, "
        f"무차별 {max(max(s['indiff_row'], s['indiff_col']) for s in stats):.1e}, |Σ−1| {max(max(s['sum_p-1'], s['sum_q-1']) for s in stats):.1e}, "
        f"min 확률 {min(min(s['min_p'], s['min_q']) for s in stats):.1e}")


if __name__ == "__main__":
    main()
