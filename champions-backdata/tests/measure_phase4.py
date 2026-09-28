"""Phase 4 — 출력 해석 검증(실데이터). pick.advise 의 내부 행렬을 같은 공개 함수로 다시 만들고(결과 일치 확인),
균형의 비유일성은 독립 LP(tests/_lp.py)로 범위를 구한다.

실행:  python tests/measure_phase4.py [--teams 12]
"""
import argparse
import itertools

import numpy as np

import _common  # noqa: F401
from _fixtures import data, party, sample_teams, SEED
from champions.pick import advise, opp_variants, matchup, mega_scenarios, scenario_pick_matrices, stone_count_dist
from champions.meta import mega_prob
from champions.game import solve_bayes
from champions.team import TRI


def internals(D, mine, opp_keys):
    """advise 와 같은 순서로 Ps, probs 를 만든다(메가 모름 = CLI 기본)."""
    opp = opp_variants(D, opp_keys, None)
    Vb, Vm = matchup(D, mine, opp, 0)
    scen, Vc = mega_scenarios(opp, Vb, Vm, stone_count_dist(D), {}, [mega_prob(D, k) for k, _ in opp])
    tri = [tuple(t) for t in TRI]
    Ps = scenario_pick_matrices(scen, Vc, tri, tri)
    probs = [p for p, _ in scen]
    pin = np.array([sum(pr for pr, S in scen if j in S) for j in range(6)])
    V = Vb * (1 - pin) + np.where(np.isnan(Vm), Vb, Vm) * pin
    return Ps, probs, V, tri


def _L(Ps, probs, x):
    return sum(p * (x @ P).min() for p, P in zip(probs, Ps))


def _U(Ps, probs, yd):
    return float(max(sum(p * (P @ y) for p, P, y in zip(probs, Ps, yd))))


def opp_eq_range(Ps, probs, v, c0, sense):
    """상대 균형 집합에서 Σ_t π_t ⟨c0, y_t⟩ 의 최대(sense=+1)/최소(−1). 섭동 사전식 선택:
    P_t − sense·ε·(1 c0ᵀ) 를 풀면 상대는 U(y) − sense·ε·⟨c0,y⟩ 를 최소화 → ε 가 작으면 균형 집합 안에서 극값.
    끝점이 원래 게임의 균형인지(U(y) ≤ v + 1e-8) 확인하고, 아니면 ε 를 줄인다. 검증된 solve_bayes 만 쓴다."""
    from champions.game import solve_bayes
    C = np.ones((Ps[0].shape[0], 1)) @ np.asarray(c0, float)[None, :]
    for eps in (1e-4, 1e-5, 1e-6, 1e-7):
        _, _, yd = solve_bayes([P - sense * eps * C for P in Ps], probs)
        if _U(Ps, probs, yd) <= v + 1e-8:
            return float(sum(p * (np.asarray(c0) @ y) for p, y in zip(probs, yd)))
    return None


def my_eq_range(Ps, probs, v, k, sense):
    """내 균형 집합에서 x_k 의 최대/최소: P_t + sense·ε·e_k 1ᵀ (행 k 에만 ε) → L(x) + sense·ε·x_k 최대화."""
    from champions.game import solve_bayes
    E = np.zeros_like(Ps[0]); E[k, :] = 1.0
    for eps in (1e-4, 1e-5, 1e-6, 1e-7):
        _, x, _ = solve_bayes([P + sense * eps * E for P in Ps], probs)
        if _L(Ps, probs, x) >= v - 1e-8:
            return float(x[k])
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=12)
    a = ap.parse_args()
    out = lambda s="": print(s, flush=True)
    D = data()
    mine = party(D)
    teams = sample_teams(D, a.teams, seed=SEED + 1, exclude_keys=[b.key for b in mine])
    nm = lambda t: "/".join(D.name(mine[i].form) for i in t)
    out(f"# Phase 4 측정 — 데이터 {D.dir.name}, 상대 레플리카 팀 {len(teams)}개(seed {SEED + 1}), 메가 모름(CLI 기본)\n")
    agg = {"best_ne_safe": 0, "best_not_maxworst_in_support": 0, "safe_outside_support": 0, "n": 0, "supp": [], "xmax": [],
           "indiff": [], "yrange_top": [], "flip_top": 0, "freq_range": [], "xbest_range": [], "xbest_flip": 0,
           "lead_ne_leadgame": 0, "lead_loss": [], "exploit_best": [], "exploit_safe": []}
    for ti, keys, ob, stones in teams:
        r = advise(D, mine, keys)
        Ps, probs, V, tri = internals(D, mine, keys)
        v, x, yd = solve_bayes(Ps, probs)
        assert abs(v - r["best_value"]) < 1e-9 and tri[int(np.argmax(x))] == r["best"], "advise 재현 실패"
        T = len(Ps)
        agg["n"] += 1
        supp = [k for k in range(20) if x[k] > 1e-6]
        agg["supp"].append(len(supp)); agg["xmax"].append(float(x.max()))
        # 4-1 무차별: 지지 조합의 기대보수(상대 균형 y 에 대해) = v
        pay = sum(p * (P @ y) for p, P, y in zip(probs, Ps, yd))
        agg["indiff"].append(float(np.abs(pay[supp] - v).max()))
        worst = np.array([sum(p * P[k].min() for p, P in zip(probs, Ps)) for k in range(20)])
        kb = int(np.argmax(x)); ks = int(np.argmax(worst))
        agg["best_ne_safe"] += kb != ks
        agg["safe_outside_support"] += ks not in supp
        agg["best_not_maxworst_in_support"] += kb != max(supp, key=lambda k: worst[k])
        agg["exploit_best"].append(v - worst[kb]); agg["exploit_safe"].append(v - worst[ks])
        # 4-3 상대 예상의 비유일성: 코드의 상대 최빈 조합 확률 범위, 다른 조합이 그보다 커질 수 있나
        ymarg = sum(p * y for p, y in zip(probs, yd))
        top = int(np.argmax(ymarg))
        e_top = np.eye(20)[top]
        lo = opp_eq_range(Ps, probs, v, e_top, -1); hi = opp_eq_range(Ps, probs, v, e_top, +1)
        agg["yrange_top"].append((ymarg[top], lo, hi))
        other_max = max(opp_eq_range(Ps, probs, v, np.eye(20)[k], +1) for k in range(20) if k != top)
        agg["flip_top"] += other_max > lo + 1e-6
        fr = []
        for j in range(6):
            cj = np.array([1.0 if j in t else 0.0 for t in tri]) / 3
            fr.append((opp_eq_range(Ps, probs, v, cj, -1), opp_eq_range(Ps, probs, v, cj, +1)))
        agg["freq_range"].append(max(h - l for l, h in fr))
        # 내 추천 조합 확률의 범위(다른 균형에서)
        xl, xh = my_eq_range(Ps, probs, v, kb, -1), my_eq_range(Ps, probs, v, kb, +1)
        agg["xbest_range"].append((x[kb], xl, xh))
        others = [my_eq_range(Ps, probs, v, k, +1) for k in range(20) if k != kb]
        agg["xbest_flip"] += max(others) > xl + 1e-6
        # 4-4 선봉: 코드 규칙 vs '상대가 내 선봉을 보고 선봉을 고른다면'(첫 대면 V 기준 최악 대응)의 최선
        freq = r["their_freq"]
        best = r["best"]
        from champions.engine import is_closer
        cand = [i for i in best if not is_closer(mine[i])] or list(best)     # 코드와 같은 제약: 마무리 포켓몬은 선봉 제외
        leadgame = {i: sum(ymarg[k] * min(V[i, j] for j in tri[k]) for k in range(20)) for i in cand}
        lg = max(leadgame, key=leadgame.get)
        agg["lead_ne_leadgame"] += lg != r["lead"]
        agg["lead_loss"].append(leadgame[lg] - leadgame[r["lead"]])
        out(f"- 팀 #{ti} ({', '.join(D.name(k) for k in keys)}): 유형 {T}, 값 {v:+.3f}, 지지 {len(supp)}조합, 추천 {nm(r['best'])} x={x[kb]:.2f} "
            f"[다른 균형에서 {xl:.2f}~{xh:.2f}], 안전 {nm(r['safe_trio'])}, 선봉 {D.name(mine[r['lead']].form)} / 선봉게임 최선 {D.name(mine[lg].form)}; "
            f"상대 최빈 {'/'.join(D.name(keys[j]) for j in tri[top])} {ymarg[top]:.2f} [{lo:.2f}~{hi:.2f}]")
    n = agg["n"]
    out("\n## 요약")
    out(f"- 지지 조합 수 중앙값 {np.median(agg['supp']):.0f}, 최대 확률 x_max 중앙값 {np.median(agg['xmax']):.2f}")
    out(f"- 4-1 무차별 조건 |(P y*)_a − v| (지지 a) 최대 {max(agg['indiff']):.1e} → 지지 안의 모든 조합은 상대 균형에 대해 값이 같다")
    out(f"- 4-1 '추천(최대 x)' 이 지지 안에서 최악값이 가장 좋은 조합이 아닌 팀 {agg['best_not_maxworst_in_support']}/{n}")
    out(f"- 4-2 추천 ≠ 안전 {agg['best_ne_safe']}/{n}, 안전 조합이 균형 지지 밖 {agg['safe_outside_support']}/{n}; "
        f"착취 가능성(v − 최악값) 중앙값: 추천 {np.median(agg['exploit_best']):.3f}, 안전 {np.median(agg['exploit_safe']):.3f}")
    out(f"- 4-3 상대 최빈 조합 확률이 다른 균형에서 움직이는 폭(최대−최소) 중앙값 "
        f"{np.median([h - l for _, l, h in agg['yrange_top']]):.2f}; 다른 조합이 최빈이 될 수 있는 팀 {agg['flip_top']}/{n}; "
        f"상대 포켓몬별 선출 빈도(freq) 폭의 팀별 최대 중앙값 {np.median(agg['freq_range']):.2f}")
    out(f"- 4-3' 내 추천 조합 확률의 폭 중앙값 {np.median([h - l for _, l, h in agg['xbest_range']]):.2f}; 다른 균형에서 다른 조합이 더 높은 확률일 수 있는 팀 {agg['xbest_flip']}/{n}")
    out(f"- 4-4 코드 선봉 ≠ '상대가 선봉에 최악 대응' 기준 최선 선봉 {agg['lead_ne_leadgame']}/{n}, 그 기준에서 손실 중앙값 {np.median(agg['lead_loss']):.3f}, 최대 {max(agg['lead_loss']):.3f}")


if __name__ == "__main__":
    main()
