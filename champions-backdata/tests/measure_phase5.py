"""Phase 5 — 실제 게임과의 오차 분해: Model A(현재 20×20 P) vs Model B(3:3 순차 시뮬 60×60).

실행:  python tests/measure_phase5.py [--teams 6] [--mc-runs 8] [--no-mc] [--no-selfcheck]
재현: 팀 표본 seed 20260929(SEED+2), 파티 tests/fixtures/party_20260927.txt, 결정적 Model B 는 난수 없음,
      확률 Model B 는 판 r 마다 random.Random(20260927·1000003 + r).
"""
import argparse
import time

import numpy as np

import _common  # noqa: F401
from _fixtures import data, party, clean, sample_teams, SEED
from model_b import model_b_det, model_b, STRATS
from champions.engine import duel, value, value_vs, is_closer
from champions.matrix import blend
from champions.meta import modal_build, mega_prob, stones_of
from champions.pick import _pick_matrix, mega_scenarios, scenario_pick_matrices, stone_count_dist
from champions.team import TRI
from champions.game import solve, solve_bayes

TRIS = [tuple(t) for t in TRI]


def agg_mean(V):
    return np.array([[np.mean([V[i, j] for i in a for j in b]) for b in TRIS] for a in TRIS])


def agg_code(V):
    return _pick_matrix(V, TRIS, TRIS)


def lead_rule(V, y, trio, mine):
    """pick.py:147-170 의 선봉 규칙을 그대로: freq = 상대 포켓몬별 선출 확률(합 1 로 정규화),
    점수 = ½·Σ_j V[i,j]·freq_j + ½·min_{freq_j>0.05} V[i,j], 마무리 포켓몬 제외."""
    freq = np.zeros(6)
    for k, t in enumerate(TRIS):
        for j in t:
            freq[j] += y[k]
    freq /= max(1e-9, freq.sum())
    score = lambda i: 0.5 * float((V[i] * freq).sum()) + 0.5 * float(V[i][freq > 0.05].min())
    return max(trio, key=lambda i: (not is_closer(mine[i]), score(i)))


def sigma_60(x, V, y, mine):
    """Model A 의 혼합(조합 x + 조합마다 코드 규칙 선봉) → 60 전략 분포."""
    s = np.zeros(60)
    for k, t in enumerate(TRIS):
        if x[k] <= 0:
            continue
        ld = lead_rule(V, y, t, mine)
        s[STRATS.index((t, t.index(ld)))] += x[k]
    return s


def collapse_leadgame(M):
    """조합 쌍마다 3×3 선봉 게임의 값(선봉은 서로 조합을 안 뒤 동시에 고른다고 볼 때)."""
    P = np.zeros((20, 20))
    for a in range(20):
        for b in range(20):
            P[a, b] = solve(M[3 * a:3 * a + 3, 3 * b:3 * b + 3])[0]
    return P


def spearman(x, y):
    rx = np.argsort(np.argsort(np.ravel(x))); ry = np.argsort(np.argsort(np.ravel(y)))
    return float(np.corrcoef(rx, ry)[0, 1])


def evaluate_in_B(M, vB, sigma):
    """σ(60) 를 Model B 에서 썼을 때의 보장값과 후회(v_B − 보장값)."""
    L = float((sigma @ M).min())
    return L, vB - L


def lead_opt_value(M, x):
    """조합 분포 x 는 그대로, 조합마다 선봉(혼합 가능)만 Model B 에서 최적으로 고를 때의 보장값.
    '나는 내 조합(유형 k, 확률 x_k)을 알고 선봉을 고르고, 상대는 모른 채 60 전략 중 고른다' = 정보가 뒤집힌 베이지안 게임
    → 부호·전치해서 검증된 solve_bayes 로 푼다: 값 = −solve_bayes([−M_kᵀ], [x_k])."""
    from champions.game import solve_bayes
    supp = [k for k in range(20) if x[k] > 1e-9]
    Ms = [-M[3 * k:3 * k + 3].T for k in supp]
    return -solve_bayes(Ms, [x[k] for k in supp])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=6)
    ap.add_argument("--mc-runs", type=int, default=8)
    ap.add_argument("--no-mc", action="store_true")
    ap.add_argument("--no-selfcheck", action="store_true")
    a = ap.parse_args()
    out = lambda s="": print(s, flush=True)
    D = data()
    mine = party(D)
    teams = sample_teams(D, a.teams, seed=SEED + 2, exclude_keys=[b.key for b in mine])
    out(f"# Phase 5 측정 — 데이터 {D.dir.name}, 파티 {', '.join(D.name(b.form) for b in mine)}, 상대 레플리카 팀 {len(teams)}개(seed {SEED + 2})\n")
    out("Model B = tests/model_b.py 의 결정적 순차 시뮬(정책은 파일 머리말). 상대 메가 = 스톤 든 첫 슬롯(알려진 것), 상대 세트 = 대표 세트(유형 없음).\n")
    steps = ["S1 V=정면 duel, 단순 평균 집계, LP", "S2 +교체 혼합(value)", "S3 +세트 불확실성(value_vs, 베이지안 유형)",
             "S4 +3:3 집계(½max+½min) = 현재 식", "S5 S4 에서 LP 대신 순수 maximin 조합", "S6 +op.gg 결합(λ 0.2) = 코드의 V"]
    R = {s: {"mae": [], "rho": [], "dv": [], "tv": [], "reg": [], "reg_pure": [], "agree": [], "reg_trio": []} for s in steps}
    import os
    ddir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out_phase5_data")
    os.makedirs(ddir, exist_ok=True)
    cell_ex = []
    lead_spread, b_self = [], None
    mega_rows = []
    for ti, keys, ob, stones in teams:
        t0 = time.time()
        opp = [clean(b) for b in ob]
        out(f"## 팀 #{ti}: {', '.join(D.name(b.form) for b in opp)}")
        M, W = model_b_det(mine, opp)
        vB, xB, yB = solve(M)
        xB3 = np.array([xB[3 * k:3 * k + 3].sum() for k in range(20)])
        PB = collapse_leadgame(M)
        out(f"- Model B: v_B = {vB:+.3f}, 승률 행렬 평균 {W.mean():.2f}, B 최다 조합 {'/'.join(D.name(mine[i].form) for i in TRIS[int(xB3.argmax())])} ({xB3.max():.2f}) [{time.time() - t0:.0f}s]")
        # 선봉의 중요도(Model B): 조합마다 선봉 3개의 보장값 차이
        chk = lead_opt_value(M, xB3)
        out(f"- 선봉 최적화 검산: B 균형의 조합 분포로 선봉만 다시 최적화한 값 {chk:+.6f} vs v_B {vB:+.6f} (같아야 함)")
        g = np.array([(M[s] @ yB) for s in range(60)])
        lead_spread.append(np.mean([g[3 * k:3 * k + 3].max() - g[3 * k:3 * k + 3].min() for k in range(20)]))
        if b_self is None and not a.no_selfcheck:
            M2, _ = model_b_det(opp, mine)
            b_self = (float(np.abs(M + M2.T).max()), float(np.abs(M + M2.T).mean()), vB + solve(M2)[0])
            out(f"- Model B 자기 점검(두 방향 따로 계산): max|M_B + M_B'ᵀ| = {b_self[0]:.3f}, 평균 {b_self[1]:.4f}, v_B + v_B' = {b_self[2]:+.4f}")
        VN = np.array([[duel(x, y) for y in opp] for x in mine])
        VV = np.array([[value(x, y) for y in opp] for x in mine])
        VS = np.array([[value_vs(x, y) for y in ob] for x in mine])
        VL = np.array([[blend(D, x.key, y.key, value_vs(x, y)) for y in ob] for x in mine])
        cfg = {steps[0]: (VN, agg_mean, "lp"), steps[1]: (VV, agg_mean, "lp"), steps[2]: (VS, agg_mean, "lp"),
               steps[3]: (VS, agg_code, "lp"), steps[4]: (VS, agg_code, "maximin"), steps[5]: (VL, agg_code, "lp")}
        for s, (V, agg, how) in cfg.items():
            P = agg(V)
            vA, xA, yA = solve(P)
            if how == "maximin":
                xA = np.eye(20)[int(P.min(axis=1).argmax())]
            sig = sigma_60(xA, V, yA, mine)
            L, reg = evaluate_in_B(M, vB, sig)
            kb = int(np.argmax(xA))
            sp = np.zeros(60); sp[STRATS.index((TRIS[kb], TRIS[kb].index(lead_rule(V, yA, TRIS[kb], mine))))] = 1
            _, regp = evaluate_in_B(M, vB, sp)
            r = R[s]
            r["mae"].append(np.abs(P - PB).mean()); r["rho"].append(spearman(P, PB)); r["dv"].append(vA - vB)
            r["tv"].append(0.5 * np.abs(xA - xB3).sum()); r["reg"].append(reg); r["reg_pure"].append(regp)
            r["agree"].append(kb == int(xB3.argmax()))
            r["reg_trio"].append(vB - lead_opt_value(M, xA))
            if s == steps[3]:
                d = P - PB
                k = np.unravel_index(np.argmax(np.abs(d)), d.shape)
                cell_ex.append((ti, TRIS[k[0]], TRIS[k[1]], float(P[k]), float(PB[k]), [D.name(b.form) for b in opp]))
        np.savez(os.path.join(ddir, f"team_{ti}.npz"), M=M, W=W, VN=VN, VV=VV, VS=VS, VL=VL, keys=np.array(keys, dtype=str),
                 stones=np.array(stones, dtype=int))
        # 메가 사전분포 층: 진실(B) = 스톤 든 첫 슬롯만 메가. A 는 (알려짐) / (모름: 코드의 베이지안) / (모름: 기대행렬로 평균)
        if stones:
            mb = {j: modal_build(D, keys[j], True) for j in range(6) if stones_of(D, keys[j])}
            bb = {j: modal_build(D, keys[j], False) for j in range(6)}
            Vb = np.array([[value_vs(x, bb[j]) for j in range(6)] for x in mine])
            Vm = np.full((6, 6), np.nan)
            for j, b in mb.items():
                if b is not None:
                    Vm[:, j] = [value_vs(x, b) for x in mine]
            opp_fake = [(k, [(bb[j], 1.0)] + ([(mb[j], 0.5)] if j in mb and mb[j] is not None else [])) for j, k in enumerate(keys)]
            scen, Vc = mega_scenarios(opp_fake, Vb, Vm, stone_count_dist(D), {}, [mega_prob(D, k) if j in mb else 0 for j, k in enumerate(keys)])
            Ps = scenario_pick_matrices(scen, Vc, TRIS, TRIS)
            probs = [p for p, _ in scen]
            vBay, xBay, ydB = solve_bayes(Ps, probs)
            yBay = sum(p * y for p, y in zip(probs, ydB))
            pin = np.array([sum(p for p, S in scen if j in S) for j in range(6)])
            Vexp = Vb * (1 - pin) + np.where(np.isnan(Vm), Vb, Vm) * pin
            vE, xE, yE = solve(agg_code(Vexp))
            Vk = VS
            vK, xK, yK = solve(agg_code(Vk))
            rows = []
            for lab, x, V, y in (("알려짐", xK, Vk, yK), ("모름·베이지안(코드)", xBay, Vexp, yBay), ("모름·기대행렬", xE, Vexp, yE)):
                rows.append((lab, evaluate_in_B(M, vB, sigma_60(x, V, y, mine))[1]))
            p_true = sum(p for p, S in scen if stones[0] in S)
            mega_rows.append((ti, len(stones), p_true, rows))
            out(f"- 메가 층: 실제 스톤 슬롯 {[D.name(keys[j]) for j in stones]} (B 에서는 첫 슬롯만 메가), 사전 P(첫 슬롯 스톤) {p_true:.2f}; "
                + ", ".join(f"{lab} 후회 {r:.3f}" for lab, r in rows))
        out("")
    out("## 요약 — 단계별 Model B 대비 오차(팀 평균, 괄호는 팀 간 최소~최대)\n")
    out("| 단계 | 셀 MAE(P_A vs B 선봉게임) | 셀 순위상관 | v_A − v_B | 균형 TV 거리 | B 에서의 후회(혼합, 코드 선봉) | 후회(조합만, 선봉은 B 최적) | 후회(최다 조합 1개) | 추천 조합 일치 |")
    out("|---|---|---|---|---|---|---|---|---|")
    f = lambda v: f"{np.mean(v):.3f} ({np.min(v):.3f}~{np.max(v):.3f})"
    for s in steps:
        r = R[s]
        out(f"| {s} | {f(r['mae'])} | {f(r['rho'])} | {f(r['dv'])} | {f(r['tv'])} | {f(r['reg'])} | {f(r['reg_trio'])} | {f(r['reg_pure'])} | {sum(r['agree'])}/{len(r['agree'])} |")
    out("\n- S4(현재 식)에서 P_A 와 Model B(선봉 게임 값)의 차이가 가장 큰 칸(팀별): " + "; ".join(
        f"#{ti} 나 {'/'.join(D.name(mine[i].form) for i in a)} vs {'/'.join(nm[j] for j in b)}: P_A {pa:+.2f}, B {pb:+.2f}"
        for ti, a, b, pa, pb, nm in cell_ex))
    out(f"\n- Model B 에서 선봉의 중요도: 조합마다 선봉 3개의 (B 균형 상대에 대한) 값 차이 평균 {np.mean(lead_spread):.3f} — Model A 의 P 는 선봉과 무관(0)")
    if mega_rows:
        out("- 메가 층(팀별 후회): " + "; ".join(f"#{ti}(스톤 {n}개, 사전 {p:.2f}): " + ", ".join(f"{lab} {r:.3f}" for lab, r in rows)
                                          for ti, n, p, rows in mega_rows))
    if not a.no_mc:
        ti, keys, ob, stones = teams[0]
        opp = [clean(b) for b in ob]
        out(f"\n## 확률 모드 Model B 교차 확인(팀 #{ti}, 칸마다 {a.mc_runs}판, 워커 3)")
        t0 = time.time()
        Vs, Ws = model_b(mine, opp, n_runs=a.mc_runs, workers=3)
        Mmc = Vs.mean(axis=2)
        Mdet, _ = model_b_det(mine, opp)
        vdet = solve(Mdet)[0]
        rng = np.random.default_rng(SEED)
        boots = []
        for _ in range(200):
            idx = rng.integers(0, a.mc_runs, a.mc_runs)
            boots.append(solve(Vs[:, :, idx].mean(axis=2))[0])
        se_cell = Vs.std(axis=2, ddof=1).mean() / np.sqrt(a.mc_runs)
        out(f"- v_B(확률) = {solve(Mmc)[0]:+.3f} (판 부트스트랩 200회 95% CI [{np.percentile(boots, 2.5):+.3f}, {np.percentile(boots, 97.5):+.3f}]), "
            f"v_B(결정적) = {vdet:+.3f}; 칸 순위상관 {spearman(Mmc, Mdet):.3f}; 칸 평균 표준오차 {se_cell:.3f}; 승률 평균 {Ws.mean():.2f} [{time.time() - t0:.0f}s]")
        out("  (주의: 판 부트스트랩의 max/min 은 칸 잡음 때문에 v 를 한쪽으로 치우치게 한다 — 구간은 잡음 크기의 지표로만)")


if __name__ == "__main__":
    main()
