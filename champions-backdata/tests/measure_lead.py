"""선출 + 선봉 60전략 게임(champions/lead.py) 검증 — 선봉 턴 교체가 있는 순차 시뮬(BS)을 기준으로 후회를 잰다.

기준 BS = tests/model_b.py 의 경로 캐시 결정적 Model B 에 선봉 턴 3×3 게임을 얹은 것.
  선봉 공개 뒤 각자 '그대로' 또는 '뒤의 두 마리 중 하나로 교체'. 교체로 들어오는 쪽은 상대 선봉의 공짜 한 방
  (engine.simulate pre_hit=True)을 맞고 첫 구간을 시작하고, 그 뒤는 Model B 와 같다. 둘 다 바꾸면 새 대면을 만피로.
비교
  예전 pick  b910f0b 의 pick.advise: 1:1 값(V, 실전 신호 포함)의 단순 평균 20×20 → 혼합, 보장값 최고 조합 + 3×3 선봉 게임
  새 pick    lead.LeadGame: 상태 캐시 순차 평가 + 선봉 턴 교체, 조합 단위 이중 오라클
후회 = 기준 게임 값 − 그 전략의 보장값(기준 행렬에서 상대가 최선으로 대응할 때). 0 이면 기준 게임의 균형과 같다.

데이터: 2026-09-24 수집본(tests/REPORT Phase 5 와 같은 6팀, seed SEED+2), 고정 파티. 상대 메가 = 스톤 든 첫 슬롯(알려짐).
실행:   python tests/measure_lead.py [--teams 6] [--workers 4]  → tests/out_lead.txt
        기준 행렬은 tests/out_lead_data/BS_<팀>.npz 에 저장하고, 있으면 다시 쓴다(팀당 4~9분, 병렬 가능).
"""
import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DAY = "2026-09-24"
DDIR = os.path.join(HERE, "out_lead_data")


def _use_day():
    """이 프로세스의 수집본을 DAY 로 고정(tests/REPORT Phase 5 와 같은 팀 표본)."""
    import _common  # noqa: F401
    import champions.data as cdata
    import _fixtures
    if not hasattr(cdata.load, "cache_clear"):          # 이 프로세스에서 이미 고정함
        return cdata.load()
    D = cdata.Data(cdata.RAW / DAY)
    cdata.load.cache_clear()
    cdata.load = lambda: D
    _fixtures.data = lambda: D
    return D


def _teams(D):
    from _fixtures import party, sample_teams, SEED
    mine = party(D)
    return mine, sample_teams(D, 6, seed=SEED + 2, exclude_keys=[b.key for b in mine])


def reference(n):
    """팀 n 의 BS 기준: (M, MA, MB) 각 (20, 3, 20, 3). M 은 둘 다 그대로, MA 는 내 선봉이 교체로 들어와 상대 선봉의
    한 방을 맞고 시작, MB 는 상대 선봉이 그렇게 들어옴."""
    D = _use_day()
    from _fixtures import clean
    import model_b as MB
    from champions import engine
    from champions.engine import plan_matrix, simulate
    from champions.game import solve
    mine, teams = _teams(D)
    ti, keys, ob, stones = teams[n]
    f = os.path.join(DDIR, f"BS_{ti}.npz")
    if os.path.exists(f):
        return ti, f
    opp = [clean(b) for b in ob]
    TRI = [t for t, _ in MB.STRATS[::3]]

    def seg_pre(ctx, key, A, B, pre):
        if key in ctx.seg:
            return
        env = ctx.env
        env.carry, env.field, env.fainted, env.screens = {}, None, {}, {}
        X, Y = (A, B) if pre == "A" else (B, A)
        O = np.asarray(plan_matrix(X, Y, pre_hit=True, branch=False)[0], float)
        if O.size == 1:
            x, y = np.array([1.0]), np.array([1.0])
        else:
            _, x, y = solve(O)
            x, y = np.clip(x, 0, None), np.clip(y, 0, None)
            x, y = x / x.sum(), y / y.sum()
        px, py = engine.plans_vs(X, Y), engine.plans_vs(Y, X)
        out = []
        for i in np.nonzero(x > 1e-9)[0]:
            for j in np.nonzero(y > 1e-9)[0]:
                env.record, env.created, env.fields = True, [], []
                v = simulate(X, Y, px[i], py[j], pre_hit=True)
                env.record = False
                sx, sy = env.created[0], env.created[1]
                out.append((float(x[i] * y[j]), sx, sy, env.fields[0], v) if pre == "A"
                           else (float(x[i] * y[j]), sy, sx, env.fields[0], -v))
        ctx.seg[key] = out

    def battle_pre(ctx, ta, tb, la, lb, pre):
        st = {"aliveA": (True,) * 3, "aliveB": (True,) * 3, "hpA": (1.0,) * 3, "hpB": (1.0,) * 3, "curA": la, "curB": lb,
              "bA": tuple(ctx.my[i] for i in ta), "bB": tuple(ctx.opp[j] for j in tb), "carry": {}, "field": None,
              "scrA": (0, 0), "scrB": (0, 0)}
        path = (("pre", pre),)
        seg_pre(ctx, path + ((ta[la], tb[lb]),), st["bA"][la], st["bB"][lb], pre)
        return MB._rec(ctx, ta, tb, st, path)[0]

    ctx = MB.DetCtx(mine, opp)
    M = np.zeros((20, 3, 20, 3))
    MA, MBs = np.zeros_like(M), np.zeros_like(M)
    with ctx.env:
        for a, ta in enumerate(TRI):
            for b, tb in enumerate(TRI):
                for i in range(3):
                    for j in range(3):
                        M[a, i, b, j] = MB.battle_det(ctx, ta, tb, i, j)[0]
                        MA[a, i, b, j] = battle_pre(ctx, ta, tb, i, j, "A")
                        MBs[a, i, b, j] = battle_pre(ctx, ta, tb, i, j, "B")
    os.makedirs(DDIR, exist_ok=True)
    np.savez_compressed(f, M=M, MA=MA, MB=MBs, keys=np.array(keys, dtype=str))
    return ti, f


def bs_matrix(z):
    """기준 60×60: 칸마다 선봉 턴 3×3 게임의 값."""
    from champions.lead import _small_game
    M, MA, MBs = z["M"], z["MA"], z["MB"]
    S = np.zeros((60, 60))
    for a in range(20):
        for i in range(3):
            ks = [k for k in range(3) if k != i]
            for b in range(20):
                for j in range(3):
                    ls = [l for l in range(3) if l != j]
                    G = np.zeros((3, 3))
                    G[0, 0] = M[a, i, b, j]
                    for r, k in enumerate(ks, 1):
                        G[r, 0] = MA[a, k, b, j]
                        for c, l in enumerate(ls, 1):
                            G[r, c] = M[a, k, b, l]
                    for c, l in enumerate(ls, 1):
                        G[0, c] = MBs[a, i, b, l]
                    S[3 * a + i, 3 * b + j] = _small_game(G)[0]
    return S


def old_pick(V, mine):
    """b910f0b 의 pick.advise(메가 알려짐): 단순 평균 P → LP 혼합 x, 조합마다 3×3 선봉 게임(V, 상대 선출 분포 y)."""
    from champions.engine import is_closer
    from champions.game import solve, solve_bayes
    from champions.lead import TRI, STRATS
    P = np.array([[np.mean([V[i, j] for i in a for j in b]) for b in TRI] for a in TRI])
    _, x, y = solve(P)
    closer = [is_closer(b) for b in mine]
    their = [(TRI[k], float(y[k])) for k in range(20) if y[k] > 0.01] or [(TRI[int(y.argmax())], 1.0)]

    def lead_game(t):
        rows = [i for i in t if not closer[i]] or list(t)
        Ms = [[[float(V[i, j]) for j in b] for i in rows] for b, _ in their]
        _, xl, _ = solve_bayes(Ms, [p for _, p in their])
        return {i: float(p) for i, p in zip(rows, xl)}
    mix = np.zeros(60)
    for k, t in enumerate(TRI):
        if x[k] > 1e-9:
            for i, p in lead_game(t).items():
                mix[STRATS.index((t, t.index(i)))] += x[k] * p
    safe = TRI[int(P.min(axis=1).argmax())]
    lp = lead_game(safe)
    pure = np.zeros(60)
    pure[STRATS.index((safe, safe.index(max(lp, key=lp.get))))] = 1
    return mix, pure


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teams", type=int, default=6)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    out = []
    say = lambda s="": (print(s, flush=True), out.append(s))
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as ex:
        refs = list(ex.map(reference, range(a.teams)))
    say(f"# 선출+선봉 60전략 게임 검증 — 데이터 {DAY}, 기준 BS(선봉 턴 교체 있는 순차 시뮬) {len(refs)}팀 [{time.time() - t0:.0f}s]\n")
    D = _use_day()
    from _fixtures import clean
    from champions.engine import value_vs
    from champions.matrix import blend
    from champions.game import solve
    from champions.lead import LeadGame
    mine, teams = _teams(D)
    rows = []
    for (ti, f), (ti2, keys, ob, stones) in zip(refs, teams):
        S = bs_matrix(np.load(f))
        vS = solve(S)[0]
        V = np.array([[blend(D, x.key, y.key, value_vs(x, y)) for y in ob] for x in mine])
        om, op = old_pick(V, mine)
        t1 = time.time()
        g = LeadGame(mine, [clean(b) for b in ob])
        r = g.solve([(1.0, ())])
        dt = time.time() - t1
        nm = np.zeros(60)
        for (k, i), w in r["x"].items():
            nm[3 * k + i] = w
        np_ = np.zeros(60)
        np_[3 * r["safe"][0] + r["safe"][1]] = 1
        def reg(s, vS=vS, S=S):
            return vS - float((s @ S).min())
        row = (ti, vS, reg(om), reg(op), reg(nm), reg(np_), vS - S.min(axis=1).max(), dt, len(g.cells))
        rows.append(row)
        say(f"- #{ti}: 기준 값 {vS:+.3f} | 후회 예전 혼합 {row[2]:.3f} · 예전 한 수 {row[3]:.3f} | 새 혼합 {row[4]:.3f} · "
            f"새 한 수 {row[5]:.3f} (한 수의 최소 {row[6]:.3f}) | 새 계산 {dt:.1f}s, 블록 {row[8]}/400")
    m = np.array([r[1:] for r in rows]).mean(axis=0)
    say(f"\n평균 후회: 예전 혼합 {m[1]:.3f} · 예전 한 수 {m[2]:.3f} → 새 혼합 {m[3]:.3f} · 새 한 수 {m[4]:.3f} "
        f"(한 수로 낼 수 있는 최소 {m[5]:.3f}). 새 계산 평균 {m[6]:.1f}s")
    with open(os.path.join(HERE, "out_lead.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
