"""선출·교체 추천 (기능 3).

advise  상대 6마리를 보고: 내 6마리 중 낼 3마리 + 선봉, 상대 한 마리마다 내 최선의 답
switch  배틀 중: 상대 필드 포켓몬(남은 HP) 에 대해 내 남은 포켓몬 중 누구를 낼지
상대의 메가는 모른다고 보고, 스톤 채용률을 그 팀 안에서 정규화한 확률로 '누가 메가인가' 유형을 둔 베이지안 게임으로 푼다.
"""
import itertools

import numpy as np

from .engine import value, value_vs, duel_stats
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


def mega_scenarios(opp, Vb, Vm):
    """[(확률, V)] — 상대 팀에서 '누가 메가인가'(또는 아무도 아님)별 상성 행렬. 한 팀에 메가는 한 번."""
    p = [sum(w for b, w in vs if b.mega) for k, vs in opp]
    out = []
    for j, pj in enumerate(p):
        if pj > 1e-9 and not np.isnan(Vm[:, j]).any():
            V = Vb.copy()
            V[:, j] = Vm[:, j]
            out.append((pj, V))
    rest = 1 - sum(pr for pr, _ in out)
    if rest > 1e-9 or not out:
        out.append((max(rest, 1e-9), Vb.copy()))
    tot = sum(pr for pr, _ in out)
    return [(pr / tot, V) for pr, V in out]


def _pick_matrix(V, my_tri, op_tri):
    if V.shape == (6, 6):
        _, P = pick_values(V[:, None, :].astype(np.float32))
        return P[:, 0, :]
    return np.array([[0.5 * np.mean([max(V[i, j] for i in a) for j in b]) + 0.5 * np.mean([min(V[i, j] for j in b) for i in a])
                      for b in op_tri] for a in my_tri])


def advise(D, mine, opp_keys, mega_known=None, mc=0):
    """선출 = 베이지안 게임. 상대는 자기 팀의 메가가 누구인지 알고 고르고, 나는 모른 채 고른다.
    (예전처럼 메가 확률로 상성을 먼저 평균하면 상대가 메가별로 대응하지 못하는 것처럼 되어 낙관 쪽으로 치우친다)"""
    from .game import solve_bayes
    opp = opp_variants(D, opp_keys, mega_known)
    Vb, Vm = matchup(D, mine, opp, mc)
    scen = mega_scenarios(opp, Vb, Vm)
    n, m = len(mine), len(opp)
    my_tri = [tuple(t) for t in TRI] if n == 6 else list(itertools.combinations(range(n), min(3, n)))
    op_tri = [tuple(t) for t in TRI] if m == 6 else list(itertools.combinations(range(m), min(3, m)))
    Ps = [_pick_matrix(V, my_tri, op_tri) for _, V in scen]
    probs = [pr for pr, _ in scen]
    val, x, ydist = solve_bayes(Ps, probs)
    V = sum(pr * Vs for pr, Vs in scen)                   # 표시용 기대 상성(선택에는 쓰지 않음)
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
    # 선봉: 고른 3마리 중, 상대가 낼 확률로 가중한 평균과 상대 선출 후보 중 최악을 반반
    def lead_score(i):
        return 0.5 * float((V[i] * freq).sum()) + 0.5 * float(V[i][freq > 0.05].min())

    lead_scores = [(i, lead_score(i)) for i in best]
    lead = max(lead_scores, key=lambda x: x[1])[0]
    # 혼합의 각 조합마다 선봉(같은 규칙) — 2순위 조합을 낼 때도 누가 먼저인지 알 수 있게
    lead_of = lambda t: max(t, key=lead_score)
    return {"V": V, "opp": opp, "best": best, "best_value": float(val),
            "best_worst": float(worst[order[0]]),          # 추천 조합 자신의 최악값(ASTRA 5)
            "safe_value": float(worst.max()), "safe_trio": my_tri[int(worst.argmax())],
            "n_scenarios": len(scen),
            "mix": [(my_tri[k], float(x[k]), lead_of(my_tri[k])) for k in order if x[k] > 0.01],
            "their_mix": [(op_tri[k], float(y[k])) for k in their_order if y[k] > 0.01],
            "alts": [(my_tri[k], float(worst[k])) for k in np.argsort(-worst)[:4] if my_tri[k] != best][:3],
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
