"""선출 + 선봉을 한 번에 고르는 게임 — 조합 20 × 선봉 3 = 60 전략.

왜: 선봉이 상대 선봉에 읽히면 그대로 맞거나, 교체하면서 상대에게 공짜 한 방(한 턴)을 준다. 예전 방식(3마리를 고른 뒤
선봉을 따로)은 선출 값이 선봉과 무관했고, 선봉 실패의 비용이 어디에도 들어가지 않았다.

한 칸 = 내 (조합 a, 선봉 i) 대 상대 (조합 b, 선봉 j)
  선봉 턴 = 3×3 동시 게임. 각자 '그대로' 또는 '뒤의 두 마리 중 하나로 교체'.
    둘 다 그대로   → 3:3 순차 평가(seq3), 선봉 i 대 j
    나만 교체(k)   → k 가 상대 선봉 j 의 공짜 한 방을 맞고 시작(내 i 는 뒤에 만피로 남음)
    상대만 교체(l) → l 이 내 선봉 i 의 공짜 한 방을 맞고 시작
    둘 다 교체     → k 대 l 을 만피로 시작
  3:3 순차 평가는 상태를 이어 가는 1:1 엔진의 사슬(champions/seq3.py). 상태 캐시로 조합 쌍·선봉 사이에서 구간을 공유한다.

상대 메가: 스톤을 든 조합(1~2마리, 드물게 없음)을 상대만 아는 유형으로 둔 베이지안 게임(pick.stone_sets 와 같은 사전분포).
상대 조합에 스톤 든 쪽이 둘이면 칸마다 나에게 더 불리한 쪽을 메가진화한다.

푸는 법: 60×60 을 다 만들지 않고 조합 단위 이중 오라클로 필요한 조합 쌍 블록만 시뮬한다(균형은 정확).
'한 수만 고집할 때 최선'은 지금까지 본 상대 조합으로 상한을 매기고, 상한 순으로 전체 행을 계산하는 분기 한정으로 정확히 찾는다.

검증(tests/measure_lead.py, 2026-09-24 데이터 6팀, 선봉 턴 교체가 있는 경로 캐시 순차 시뮬을 기준):
  후회(기준 게임 값 − 보장값) 옛 pick 혼합 0.435 · 한 수 0.633 → 이 게임 혼합 0.006 · 한 수 0.173(한 수의 최소 0.171).
  계산 8~19초(한 프로세스, 상대 메가 확정). 메가 불확실(스톤 조합 7가지)이면 20~25초.
"""
import itertools
import time

import numpy as np

from .game import solve, solve_bayes
from .seq3 import Seq

TRI = [tuple(t) for t in itertools.combinations(range(6), 3)]
STRATS = [(t, l) for t in TRI for l in range(3)]          # (조합, 조합 안의 선봉 위치) — tests/model_b.py 와 같은 순서


def _small_game(M):
    M = np.asarray(M, float)
    if M.size == 1:
        return float(M.flat[0]), np.array([1.0]), np.array([1.0])
    lo, hi = M.min(axis=1).max(), M.max(axis=0).min()
    if hi - lo <= 1e-12:
        x = np.zeros(M.shape[0]); x[int(M.min(axis=1).argmax())] = 1
        y = np.zeros(M.shape[1]); y[int(M.max(axis=0).argmin())] = 1
        return float(lo), x, y
    v, x, y = solve(M)
    x, y = np.clip(x, 0, None), np.clip(y, 0, None)
    return float(v), x / x.sum(), y / y.sum()


class LeadGame:
    """상대 한 팀에 대한 60×60 (스톤 조합별). opp: 상대 6마리 기본형, opp_mega: {슬롯: 메가형 Build}."""

    def __init__(self, mine, opp, opp_mega=None, switch=True):
        self.mine, self.opp = list(mine), list(opp)
        self.mega_slot = {}
        builds = list(opp)
        for c, mb in (opp_mega or {}).items():
            self.mega_slot[c] = len(builds)
            builds.append(mb)
        self.seq = Seq(self.mine, builds)
        self.switch = switch
        self.blocks, self.cells = {}, {}

    def _block(self, ta, tb):
        """(M, MA, MB) 3×3: M[i, j] 선봉 i 대 j, MA[k, j] 내 k 가 j 의 한 방을 맞고 들어옴, MB[i, l] 상대 l 이 i 의 한 방."""
        r = self.blocks.get((ta, tb))
        if r is None:
            s = self.seq
            M = np.array([[s.battle(ta, tb, i, j) for j in range(3)] for i in range(3)])
            if self.switch:
                MA = np.array([[s.battle(ta, tb, k, j, pre="A") for j in range(3)] for k in range(3)])
                MB = np.array([[s.battle(ta, tb, i, l, pre="B") for l in range(3)] for i in range(3)])
            else:
                MA = MB = None
            r = (M, MA, MB)
            self.blocks[(ta, tb)] = r
        return r

    def sub(self, ta, tb, i, j):
        """선봉 i 대 j 의 선봉 턴 3×3 게임 (값, 내 혼합, 상대 혼합, 내 선택지, 상대 선택지). 선택지 None = 그대로."""
        M, MA, MB = self._block(ta, tb)
        if not self.switch:
            return float(M[i, j]), np.array([1.0]), np.array([1.0]), [None], [None]
        ks = [None] + [k for k in range(3) if k != i]
        ls = [None] + [l for l in range(3) if l != j]
        G = np.zeros((3, 3))
        for r, k in enumerate(ks):
            for c, l in enumerate(ls):
                if k is None and l is None:
                    G[r, c] = M[i, j]
                elif l is None:
                    G[r, c] = MA[k, j]
                elif k is None:
                    G[r, c] = MB[i, l]
                else:
                    G[r, c] = M[k, l]
        v, x, y = _small_game(G)
        return v, x, y, ks, ls

    def matrix(self, mega=None):
        """60×60 (내 입장). mega = 메가진화한 상대 슬롯(없으면 None)."""
        P = np.zeros((60, 60))
        for ai, ta in enumerate(TRI):
            for bi, b in enumerate(TRI):
                tb = tuple(self.mega_slot[c] if c == mega else c for c in b)
                for i in range(3):
                    for j in range(3):
                        P[3 * ai + i, 3 * bi + j] = self.sub(ta, tb, i, j)[0]
        return P

    def _map(self, b, c):
        return tuple(self.mega_slot[x] if x == c else x for x in b)

    def cell_block(self, a, b, c=None):
        """3×3 선봉 블록(행 = 내 선봉, 열 = 상대 선봉): 선봉 턴 게임의 값. c = 메가진화한 상대 슬롯."""
        key = (a, b, c)
        r = self.cells.get(key)
        if r is None:
            ta, tb = TRI[a], self._map(TRI[b], c if c in TRI[b] else None)
            r = np.array([[self.sub(ta, tb, i, j)[0] for j in range(3)] for i in range(3)])
            self.cells[key] = r
        return r

    def scen_block(self, a, b, S):
        """스톤 조합 S 일 때의 블록: 상대 조합에 스톤 든 쪽이 있으면 칸마다 나에게 더 불리한 쪽을 메가진화."""
        cs = [c for c in S if c in TRI[b]]
        if not cs:
            return self.cell_block(a, b)
        return np.min([self.cell_block(a, b, c) for c in cs], axis=0)

    def solve(self, scen, tol=1e-7, log=None):
        """60×60 베이지안 게임을 조합 단위 이중 오라클로 푼다(필요한 조합 쌍 블록만 시뮬).
        초기 조합은 만피 1:1 값의 평균으로 고르고, 서로의 최선 대응이 이미 들어 있을 때까지 조합을 늘린다.
        보장값이 가장 좋은 한 수는 '지금까지 본 상대 조합'으로 상한을 매긴 뒤, 상한 순으로 전체 행을 계산하는
        분기 한정으로 정확히 찾는다."""
        probs = [p for p, _ in scen]
        Ss = [S for _, S in scen]
        n = len(TRI)
        V0 = self._fresh_values()
        P0 = np.array([[V0[np.ix_(ta, tb)].mean() for tb in TRI] for ta in TRI])
        A, B = [int(P0.min(axis=1).argmax())], [int(P0.max(axis=0).argmin())]
        while True:
            Ms = [np.block([[self.scen_block(a, b, S) for b in B] for a in A]) for S in Ss]
            v, x, ydist = solve_bayes(Ms, probs)
            xs = {(A[k // 3], k % 3): w for k, w in enumerate(x) if w > 1e-9}
            ys = [{(B[k // 3], k % 3): w for k, w in enumerate(yd) if w > 1e-9} for yd in ydist]
            # 내 최선 대응(모든 조합·선봉) — 상대 지지 조합의 블록만 필요
            my_br, my_v = None, -9.0
            for a in range(n):
                tot = np.zeros(3)
                for p, S, yk in zip(probs, Ss, ys):
                    for (b, j), w in yk.items():
                        tot += p * w * self.scen_block(a, b, S)[:, j]
                i = int(tot.argmax())
                if tot[i] > my_v:
                    my_br, my_v = a, float(tot[i])
            # 상대 최선 대응(유형마다) — 내 지지 조합의 블록만 필요
            add_b, v_br = set(), 0.0
            for p, S in zip(probs, Ss):
                best_b, best = None, 9.0
                for b in range(n):
                    tot = np.zeros(3)
                    for (a, i), w in xs.items():
                        tot += w * self.scen_block(a, b, S)[i, :]
                    j = int(tot.argmin())
                    if tot[j] < best:
                        best_b, best = b, float(tot[j])
                v_br += p * best
                if best_b not in B:
                    add_b.add(best_b)
            grow = False
            if my_v > v + tol and my_br not in A:
                A.append(my_br); grow = True
            if v_br < v - tol and add_b:
                B.extend(sorted(add_b)); grow = True
            if log:
                log(f"  [lead] 이중 오라클: 내 조합 {len(A)} · 상대 조합 {len(B)} · 값 {v:+.3f} · 블록 {len(self.cells)}")
            if not grow:
                break
        # 보장값 최고 한 수: 상한(본 상대 조합만) → 상한 순으로 전체 행
        def worst(a, i, Bset):
            return sum(p * min(self.scen_block(a, b, S)[i, :].min() for b in Bset) for p, S in zip(probs, Ss))
        # 마무리 포켓몬(총대장·성묘)은 순차 평가가 실제 쓰러진 수로 계산하므로 선봉 후보에서 따로 빼지 않는다
        ub = sorted(((worst(a, i, B), a, i) for a in range(n) for i in range(3)), reverse=True)
        exact = {}
        best, bv = None, -9.0
        for u, a, i in ub:
            if u <= bv:
                break
            w = worst(a, i, range(n))
            exact[(a, i)] = w
            if w > bv:
                best, bv = (a, i), w
        for (a, i) in xs:                                  # 혼합 지지 조합은 전체 행이 이미 있다(상대 최선 대응 계산)
            if (a, i) not in exact:
                exact[(a, i)] = worst(a, i, range(n))
        return {"value": float(v), "x": xs, "y": ys, "probs": probs, "Ss": Ss, "safe": best, "safe_value": bv,
                "exact": exact, "A": A, "B": B}

    def _fresh_values(self):
        """만피 1:1 균형값(내 6 × 상대 6, 기본형) — 이중 오라클의 시작 조합을 고르는 데만 쓴다."""
        s = self.seq
        V = np.zeros((len(self.mine), len(self.opp)))
        with s.env:
            for i, A in enumerate(self.mine):
                for j, B in enumerate(self.opp):
                    V[i, j] = s._segment(A, B, {}, None, {}, {})[1]
        return V


def advise(D, mine, opp_keys, mega_known=None, switch=True, log=None):
    """선출·선봉 추천. 반환 dict:
    safe        (조합, 선봉 위치) — 보장값(상대가 스톤 조합을 알고 최선으로 대응할 때)이 가장 좋은 한 수
    safe_value  그 보장값
    value       균형(섞어 낼 때) 값
    mix         [(조합, 선봉 위치, 확률, 그 수의 보장값)] — 균형 혼합(섞어 내면 읽히지 않음)
    their_mix   [(상대 조합, 선봉 위치, 확률)]
    response    {상대 선봉 슬롯: (그대로 확률, {교체할 내 슬롯: 확률}, 값, 그 선봉일 확률)} — safe 로 냈을 때 선봉 턴 대응
    responses   {(조합, 선봉 위치): response} — 균형 혼합의 수마다
    V0          (6, 6) 만피 1:1 값(내 입장, 상대 기본형)"""
    from .meta import modal_build, mega_prob, stones_of
    from .pick import stone_sets, stone_count_dist
    t0 = time.time()
    mk = mega_known or {}
    opp, opp_mega, pm = [], {}, []
    for j, k in enumerate(opp_keys):
        b = modal_build(D, k, False) or modal_build(D, k, True, stone=mk.get(k) or None)
        opp.append(_clean(b))
        if stones_of(D, k) and mk.get(k) is not False:
            mb = modal_build(D, k, True, stone=mk.get(k) or None)
            if mb is not None:
                opp_mega[j] = _clean(mb)
        pm.append(mega_prob(D, k) if j in opp_mega else 0.0)
    forced = {j: bool(mk[k]) for j, k in enumerate(opp_keys) if k in mk}
    if any(forced.values()):
        forced = {j: forced.get(j, False) for j in range(len(opp_keys))}
    scen = stone_sets(pm, stone_count_dist(D), forced)
    g = LeadGame(mine, opp, opp_mega, switch)
    r = g.solve(scen, log=log)
    xs = r["x"]
    y = {}
    for p, yk in zip(r["probs"], r["y"]):
        for s, w in yk.items():
            y[s] = y.get(s, 0.0) + p * w
    (sa, si) = r["safe"]
    res = {"value": r["value"], "safe": (TRI[sa], si), "safe_value": r["safe_value"],
           "mix": [(TRI[a], i, float(w), r["exact"].get((a, i))) for (a, i), w in sorted(xs.items(), key=lambda t: -t[1]) if w > 0.01],
           "their_mix": [(TRI[b], j, float(w)) for (b, j), w in sorted(y.items(), key=lambda t: -t[1]) if w > 0.01],
           "n_scenarios": len(scen), "n_blocks": len(g.cells), "n_sim": g.seq.n_sim, "seconds": time.time() - t0}
    res["response"] = _response(g, sa, si, r)
    # 균형에서 낼 수 있는 수마다의 선봉 턴 대응(이번 판에 뽑힌 수로 바로 볼 수 있게)
    res["responses"] = {(TRI[a], i): _response(g, a, i, r) for (a, i), w in xs.items() if w > 0.01}
    res["V0"] = g._fresh_values()
    return res


def _response(g, a, i, r):
    """safe 로 냈을 때 상대 선봉별 선봉 턴 대응(3×3 게임의 균형). 상대 (조합, 선봉)은 균형 분포로 가중하고,
    스톤 조합마다 그 칸에서 상대가 고를 메가(나에게 더 불리한 쪽)로 계산한다."""
    ta = TRI[a]
    out = {}
    for p, S, yk in zip(r["probs"], r["Ss"], r["y"]):
        for (b, j), w in yk.items():
            w = p * w
            cs = [c for c in S if c in TRI[b]]
            c = min(cs, key=lambda c: g.cell_block(a, b, c)[i, j]) if cs else None
            v, xs, _, ks, _ = g.sub(ta, g._map(TRI[b], c), i, j)
            q = TRI[b][j]
            acc = out.setdefault(q, [0.0, {}, 0.0, 0.0])
            for rr, k in enumerate(ks):
                if k is None:
                    acc[0] += w * xs[rr]
                else:
                    acc[1][ta[k]] = acc[1].get(ta[k], 0.0) + w * xs[rr]
            acc[2] += w * v
            acc[3] += w
    tot = sum(x[3] for x in out.values()) or 1.0
    return {q: (x[0] / x[3], {k: p / x[3] for k, p in x[1].items() if p / x[3] > 0.01}, x[2] / x[3], x[3] / tot)
            for q, x in sorted(out.items(), key=lambda t: -t[1][3])}


def _clean(b):
    """유형(역할별 세트·변형) 없이 대표 세트만 — 순차 평가는 상대 한 벌로 계산한다(OPPONENT_SETS_REVIEW 참고)."""
    from .engine import Build
    return Build(b.D, **b.spec())
