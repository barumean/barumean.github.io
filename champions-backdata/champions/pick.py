"""선출·교체 추천 (기능 3).

advise  상대 6마리를 보고: 내 6마리 중 낼 3마리 + 선봉, 상대 한 마리마다 내 최선의 답
switch  배틀 중: 상대 필드 포켓몬(남은 HP) 에 대해 내 남은 포켓몬 중 누구를 낼지
상대가 누구에게 스톤을 들렸는지 모른다고 보고, '스톤을 든 1~2마리 조합'을 유형으로 둔 베이지안 게임으로 푼다.
레플리카 팀의 스톤 수: 2개 71%·1개 16%·없음 8%(3개 이상은 드물어 2개로 묶음). 배틀에서 메가진화는 한 번이라
스톤을 든 두 마리를 모두 내면 상대는 더 유리한 쪽을 메가진화한다.
"""
import itertools

import numpy as np

from .engine import value, value_vs, duel_stats, is_closer
from .matrix import blend
from .meta import modal_build, mega_prob, stones_of
from .engine import Build
from .team import pick_values, TRI


def opp_variants(D, keys, mega_known=None):
    """[(key, [(Build, 확률)…])]. mega_known: {key: 스톤 키 | False}. 모르는 상대는 스톤 채용률로,
    한 팀에서 메가는 한 번이므로 확률 합이 1을 넘으면 나눠 준다. 메가가 확정된 상대가 있으면 나머지는 0."""
    mega_known = mega_known or {}
    if any(mega_known.values()):
        p = {k: 1.0 if mega_known.get(k) else 0.0 for k in keys}
    else:
        p = {k: 0.0 if k in mega_known else mega_prob(D, k) for k in keys}
        tot = sum(p.values())
        if tot > 1:
            p = {k: v / tot for k, v in p.items()}
    out = []
    for k in keys:
        vs = []
        if p[k] > 0.02 and stones_of(D, k):
            st = mega_known.get(k) or None
            vs.append((modal_build(D, k, True, stone=st), p[k]))
        # 기본형은 스톤 채용률이 높아도 넣는다 — 다른 포켓몬이 메가인 경우 이 칸은 기본형이어야 한다
        # (예전에는 채용률 ≥0.98 종이 기본형 없이 늘 메가로 남아 한 배틀에 메가가 둘이 됐다, REPORT 3-5)
        base = modal_build(D, k, False)
        if base is None and vs:
            mb = vs[0][0]
            base = Build(D, k, mb.moves, None, None, mb.nature, mb.sp, label="meta-base")
        vs.append((base, max(1e-3, 1 - p[k]) if vs else 1.0))
        out.append((k, [(b, w) for b, w in vs if b is not None]))
    return out


def matchup(D, mine, opp, mc=0):
    """(Vb, Vm): 내 i 대 상대 j 의 기본형 값, 메가형 값(메가가 없으면 NaN). 확률로 섞지 않는다."""
    n, m = len(mine), len(opp)
    Vb, Vm = np.zeros((n, m)), np.full((n, m), np.nan)
    for j, (k, vs) in enumerate(opp):
        base = next((b for b, w in vs if not b.mega), None)
        meg = next((b for b, w in vs if b.mega), None)
        for i, a in enumerate(mine):
            if base is not None:
                Vb[i, j] = blend(D, a.key, base.key, value_vs(a, base, mc))
            if meg is not None:
                Vm[i, j] = blend(D, a.key, meg.key, value_vs(a, meg, mc))
        if base is None:                                  # 메가 확정(스톤 100%)이면 기본형 칸도 메가 값으로
            Vb[:, j] = Vm[:, j]
    return Vb, Vm


def stone_count_dist(D):
    """레플리카 팀의 스톤 수 분포 {'all': [P(0),P(1),P(2+)], '1'..'4': 팀 안 메가 가능 종 수별 분포}.
    후보 수에 조건화하면 표본 안 로그우도가 −1.025 → −1.009 로 좋아진다(REPORT 3-5 권고). 표본이 20팀 미만인
    후보 수는 전체 분포를 쓴다."""
    from collections import Counter, defaultdict
    from .meta import stones_of
    allc, by = Counter(), defaultdict(Counter)
    for t in D.TEAMS:
        keys = [D.base_of(sl["pokemon"]) for sl in t["slots"] if sl["pokemon"] in D.DEX]
        n = min(4, sum(1 for k in keys if stones_of(D, k)))
        k = min(2, sum(1 for sl in t["slots"] if sl.get("item") in D.STONE))
        allc[k] += 1
        by[n][k] += 1
    norm = lambda c: [c[k] / (sum(c.values()) or 1) for k in (0, 1, 2)]
    out = {"all": norm(allc)}
    for n, c in by.items():
        if n >= 1 and sum(c.values()) >= 20:
            out[str(n)] = norm(c)
    return out


def stone_sets(pm, K, forced=None):
    """[(확률, 스톤 든 슬롯 튜플)]. pm[j] = 그 종의 스톤 채용률(스톤이 없으면 0), K = 스톤 수 분포,
    forced = {j: True(메가 확정) | False(메가 아님)}. 스톤 수 k 가 정해지면 k마리 조합의 확률은
    채용률 오즈의 곱에 비례(조건부 베르누이)."""
    from math import prod
    forced = forced or {}
    if isinstance(K, dict):                               # 후보 수별 분포(없으면 전체)
        n = min(4, sum(1 for p in pm if p > 0))
        K = K.get(str(n)) or K["all"]
    cand = [j for j, p in enumerate(pm) if p > 0 and forced.get(j) is not False]
    must = {j for j in cand if forced.get(j)}
    odds = {j: min(pm[j], 0.97) / (1 - min(pm[j], 0.97)) for j in cand}
    out = []
    for k, pk in enumerate(K):
        if pk <= 0 or k > len(cand):
            continue
        subs = [S for S in itertools.combinations(cand, k) if must <= set(S)]
        ws = [prod(odds[j] for j in S) for S in subs]
        t = sum(ws)
        if t > 0:
            out += [(pk * w / t, S) for S, w in zip(subs, ws) if w > 0]
    if not out:
        return [(1.0, tuple(sorted(must)))]
    tot = sum(p for p, _ in out)
    out = [(p / tot, S) for p, S in out if p / tot > 1e-4]
    tot = sum(p for p, _ in out)                           # 버린 뒤 다시 정규화(REPORT 3-5)
    return [(p / tot, S) for p, S in out]


def mega_scenarios(opp, Vb, Vm, K=(0.08, 0.16, 0.76), forced=None, pm=None):
    """[(확률, 스톤 든 슬롯들)] 과 슬롯별 메가 행렬. 반환: (scen, Vc) — Vc[c] = c 가 메가일 때의 상성 행렬
    (c = None 이면 아무도 메가가 아님)."""
    pm = [(pm[j] if pm is not None else min(1.0, sum(w for b, w in vs if b.mega)))
          if not np.isnan(Vm[:, j]).any() else 0.0 for j, (k, vs) in enumerate(opp)]
    scen = stone_sets(pm, K, forced)
    Vc = {None: Vb.copy()}
    for _, S in scen:
        for c in S:
            if c not in Vc:
                V = Vb.copy()
                V[:, c] = Vm[:, c]
                Vc[c] = V
    return scen, Vc


def scenario_pick_matrices(scen, Vc, my_tri, op_tri):
    """스톤 조합별 선출 행렬. 상대 3마리 중 스톤을 든 쪽이 둘이면 그중 나에게 더 불리한 쪽을 메가진화한다."""
    Pc = {c: _pick_matrix(V, my_tri, op_tri) for c, V in Vc.items()}
    out = []
    for _, S in scen:
        P = Pc[None].copy()
        for bi, b in enumerate(op_tri):
            cs = [c for c in S if c in b]
            if cs:
                P[:, bi] = np.min([Pc[c][:, bi] for c in cs], axis=0)
        out.append(P)
    return out


def _pick_matrix(V, my_tri, op_tri):
    if V.shape == (6, 6):
        _, P = pick_values(V[:, None, :].astype(np.float32))
        return P[:, 0, :]
    from .team import AGG_W
    def agg(a, b):
        mean = float(np.mean([V[i, j] for i in a for j in b]))
        if AGG_W <= 0:
            return mean
        old = 0.5 * np.mean([max(V[i, j] for i in a) for j in b]) + 0.5 * np.mean([min(V[i, j] for j in b) for i in a])
        return (1 - AGG_W) * mean + AGG_W * old
    return np.array([[agg(a, b) for b in op_tri] for a in my_tri])


def advise(D, mine, opp_keys, mega_known=None, mc=0):
    """선출 = 베이지안 게임. 상대는 자기 팀의 메가가 누구인지 알고 고르고, 나는 모른 채 고른다.
    (예전처럼 메가 확률로 상성을 먼저 평균하면 상대가 메가별로 대응하지 못하는 것처럼 되어 낙관 쪽으로 치우친다)"""
    from .game import solve_bayes
    opp = opp_variants(D, opp_keys, mega_known)
    Vb, Vm = matchup(D, mine, opp, mc)
    mk = mega_known or {}
    forced = {j: bool(mk[k]) for j, (k, _) in enumerate(opp) if k in mk}
    if any(forced.values()):
        forced = {j: forced.get(j, False) for j in range(len(opp))}   # 메가가 확정되면 나머지는 메가 아님
    scen, Vc = mega_scenarios(opp, Vb, Vm, stone_count_dist(D), forced, [mega_prob(D, k) for k, _ in opp])
    n, m = len(mine), len(opp)
    my_tri = [tuple(t) for t in TRI] if n == 6 else list(itertools.combinations(range(n), min(3, n)))
    op_tri = [tuple(t) for t in TRI] if m == 6 else list(itertools.combinations(range(m), min(3, m)))
    Ps = scenario_pick_matrices(scen, Vc, my_tri, op_tri)
    probs = [pr for pr, _ in scen]
    val, x, ydist = solve_bayes(Ps, probs)
    # 표시용 기대 상성(선택에는 쓰지 않음): 슬롯별로 스톤을 들 확률로 메가 값을 섞는다
    pin = np.array([sum(pr for pr, S in scen if j in S) for j in range(m)])
    V = Vb * (1 - pin) + np.where(np.isnan(Vm), Vb, Vm) * pin
    order = np.argsort(-x)
    best = my_tri[order[0]]                               # 균형에서 가장 자주 낼 3마리
    y = sum(pr * yd for pr, yd in zip(probs, ydist))      # 상대 선출 분포(메가 유형으로 가중)
    their_order = np.argsort(-y)
    likely = op_tri[their_order[0]]
    freq = np.zeros(m)                                    # 상대 각 포켓몬이 선출될 확률(균형 기준)
    for k, t in enumerate(op_tri):
        for j in t:
            freq[j] += y[k]
    freq /= max(1e-9, freq.sum())
    # 조합별 최악값: 상대가 메가 유형을 알고 그 조합에 가장 불리하게 고를 때(유형 확률로 가중)
    worst = np.array([sum(pr * P[a].min() for pr, P in zip(probs, Ps)) for a in range(len(my_tri))])
    P = sum(pr * Pm for pr, Pm in zip(probs, Ps))
    # 선봉 = 3×3 선봉 게임(REPORT 결론 2-①): 행 = 내 선봉, 열 = 상대 선봉, 칸 = 첫 대면 값 V.
    # 상대 3마리는 상대만 안다(균형 분포 y 를 유형 확률로 둔 베이지안 게임) → 결정적 규칙 대신 선봉 혼합 비율.
    # 마무리 포켓몬(총대장·성묘)은 동료가 쓰러진 뒤에 강해지므로 선봉 후보에서 뺀다(셋 다 마무리면 예외).
    closer = [is_closer(b) for b in mine]
    their = [(op_tri[k], float(y[k])) for k in range(len(op_tri)) if y[k] > 0.01] or [(op_tri[int(y.argmax())], 1.0)]

    def lead_game(t):
        rows = [i for i in t if not closer[i]] or list(t)
        Ms = [[[float(V[i, j]) for j in b] for i in rows] for b, _ in their]
        v, xl, _ = solve_bayes(Ms, [p for _, p in their])
        probs_l = {i: float(p) for i, p in zip(rows, xl)}
        return max(probs_l, key=probs_l.get), probs_l, float(v)

    # 한 조합만 낸다면 = 최악값(상대가 유형을 알고 최선 대응할 때의 보장값)이 가장 좋은 조합(REPORT 4-1·4-2).
    # 균형 혼합의 최다 조합은 '확률이 최대'일 뿐 보수상 의미가 없다.
    safe = my_tri[int(worst.argmax())]
    lead, lead_probs, lead_v = lead_game(safe)
    return {"V": V, "opp": opp, "best": safe, "best_value": float(val), "best_worst": float(worst.max()),
            "safe_value": float(worst.max()), "safe_trio": safe,
            "mix_top": my_tri[order[0]], "mix_top_worst": float(worst[order[0]]),
            "n_scenarios": len(scen), "mega_marg": pin,
            "mix": [(my_tri[k], float(x[k]), lead_game(my_tri[k])[0]) for k in order if x[k] > 0.01],
            "their_mix": [(op_tri[k], float(y[k])) for k in their_order if y[k] > 0.01],
            "alts": [(my_tri[k], float(worst[k])) for k in np.argsort(-worst)[:4] if my_tri[k] != safe][:3],
            "their_likely": likely, "their_freq": freq, "lead": lead, "lead_probs": lead_probs,
            "lead_scores": sorted(lead_probs.items(), key=lambda kv: -kv[1])}


def switch(D, mine_hp, opp_build, opp_hp=1.0, active=None, mc=64, free=False):
    """mine_hp: [(Build, hp비율)]. active 는 지금 필드에 있는 내 포켓몬 인덱스(교체 없이 싸우는 선택지).
    교체로 들어오는 쪽은 상대에게 한 방을 먼저 맞는다. free=True(내 포켓몬이 쓰러진 뒤 내보내기)면 공짜 등장이라 안 맞는다. 확률 모드 mc 판 → (인덱스, 값, 그대로?, 승률)."""
    rows = []
    for i, (b, hp) in enumerate(mine_hp):
        if hp <= 0:
            continue
        stay = i == active
        v, p = duel_stats(b, opp_build, hpA=hp, hpB=opp_hp, pre_hit=not (stay or free), mc=mc, seed=i + 1)
        v = blend(D, b.key, opp_build.key, v)
        rows.append((i, v, stay, p))
    return sorted(rows, key=lambda x: -x[1])
