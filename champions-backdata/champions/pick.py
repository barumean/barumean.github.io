"""선출·교체 추천 (기능 3).

advise  상대 6마리를 보고: 내 6마리 중 낼 3마리 + 선봉, 상대 한 마리마다 내 최선의 답
switch  배틀 중: 상대 필드 포켓몬(남은 HP) 에 대해 내 남은 포켓몬 중 누구를 낼지
상대의 메가는 모른다고 보고, 스톤 채용률을 그 팀 안에서 정규화한 확률로 메가형/기본형 값을 섞는다.
"""
import itertools

import numpy as np

from .engine import value, duel_stats
from .matrix import blend
from .meta import modal_build, mega_prob, stones_of
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
        if p[k] < 0.98:
            vs.append((modal_build(D, k, False), 1 - p[k] if vs else 1.0))
        out.append((k, [(b, w) for b, w in vs if b is not None]))
    return out


def matchup(D, mine, opp, mc=0):
    """V[i][j] = 내 i 대 상대 j (메가 확률로 섞은) 값."""
    V = np.zeros((len(mine), len(opp)))
    for i, a in enumerate(mine):
        for j, (k, vs) in enumerate(opp):
            V[i, j] = sum(w * blend(D, a.key, b.key, value(a, b, mc)) for b, w in vs) / max(1e-9, sum(w for _, w in vs))
    return V


def advise(D, mine, opp_keys, mega_known=None, mc=0):
    opp = opp_variants(D, opp_keys, mega_known)
    V = matchup(D, mine, opp, mc)
    n, m = len(mine), len(opp)
    if n == 6 and m == 6:
        _, P = pick_values(V[:, None, :].astype(np.float32))
        P = P[:, 0, :]                                    # (20 내 3, 20 상대 3)
        my_tri, op_tri = [tuple(t) for t in TRI], [tuple(t) for t in TRI]
    else:
        my_tri = list(itertools.combinations(range(n), min(3, n)))
        op_tri = list(itertools.combinations(range(m), min(3, m)))
        P = np.array([[0.5 * np.mean([max(V[i, j] for i in a) for j in b]) + 0.5 * np.mean([min(V[i, j] for j in b) for i in a])
                       for b in op_tri] for a in my_tri])
    # 선출은 서로 동시에 정하는 게임 → 혼합전략 균형으로 푼다 (보장값만 보면 너무 보수적이고 상대 선택을 무시)
    from .game import solve
    val, x, y = solve(P)
    order = np.argsort(-x)
    best = my_tri[order[0]]                               # 균형에서 가장 자주 낼 3마리
    their_order = np.argsort(-y)
    likely = op_tri[their_order[0]]
    freq = np.zeros(m)                                    # 상대 각 포켓몬이 선출될 확률(균형 기준)
    for k, t in enumerate(op_tri):
        for j in t:
            freq[j] += y[k]
    freq /= max(1e-9, freq.sum())
    # 선봉: 고른 3마리 중, 상대가 낼 확률로 가중한 평균과 상대 선출 후보 중 최악을 반반
    lead_scores = [(i, 0.5 * float((V[i] * freq).sum()) + 0.5 * float(V[i][freq > 0.05].min())) for i in best]
    lead = max(lead_scores, key=lambda x: x[1])[0]
    return {"V": V, "opp": opp, "best": best, "best_value": float(val), "safe_value": float(P.min(axis=1).max()),
            "mix": [(my_tri[k], float(x[k])) for k in order if x[k] > 0.01],
            "their_mix": [(op_tri[k], float(y[k])) for k in their_order if y[k] > 0.01],
            "alts": [(my_tri[k], float(P[k].min())) for k in np.argsort(-P.min(axis=1))[:4] if my_tri[k] != best][:3],
            "their_likely": likely, "their_freq": freq, "lead": lead, "lead_scores": lead_scores}


def switch(D, mine_hp, opp_build, opp_hp=1.0, active=None, mc=64):
    """mine_hp: [(Build, hp비율)]. active 는 지금 필드에 있는 내 포켓몬 인덱스(교체 없이 싸우는 선택지).
    교체로 들어오는 쪽은 상대에게 한 방을 먼저 맞는다. 확률 모드 mc 판 → (인덱스, 값, 그대로?, 승률)."""
    rows = []
    for i, (b, hp) in enumerate(mine_hp):
        if hp <= 0:
            continue
        stay = i == active
        v, p = duel_stats(b, opp_build, hpA=hp, hpB=opp_hp, pre_hit=not stay, mc=mc, seed=i + 1)
        v = blend(D, b.key, opp_build.key, v)
        rows.append((i, v, stay, p))
    return sorted(rows, key=lambda x: -x[1])
