"""Phase 3 — payoff 모델 일관성 측정(실데이터). 코드 수정 없음(원인 진단용 계측만 이 프로세스 안에서 감싼다).

실행:  python tests/measure_phase3.py [--top 100] [--teams 20]
출력은 tests/out_phase3.txt 로 받아 둔다(재현: seed 20260927, 데이터 data/raw 최신, 파티 tests/fixtures/party_20260927.txt).
"""
import argparse
import itertools
import math
import random
import sys
import time

import numpy as np

import _common  # noqa: F401
from _fixtures import data, party, clean, top_opponents, sample_teams, SEED
from champions import engine
from champions.engine import value, value_vs, duel, opp_types
from champions.matrix import blend, empirical, LAMBDA
from champions.meta import mega_prob, stones_of
from champions.pick import stone_sets, stone_count_dist, _pick_matrix
from champions.team import TRI
from champions.game import solve


# ── 원인 진단: 반사실 실험(이 프로세스 안에서만 engine 함수를 감싼다) ──────
_orig_speed, _orig_eot = engine.speed, engine.end_of_turn


def _eot_speed_order():
    """턴 종료 처리를 라벨(A 먼저)이 아니라 스피드 순(빠른 쪽 먼저)으로 — simulate 가 한 턴에 두 번 부르는 것을 첫 호출에서 몰아서."""
    st = {"n": 0}

    def eot(s, o, field):
        if st["n"] % 2 == 0:
            f, g = (s, o) if _orig_speed(s, field) >= _orig_speed(o, field) else (o, s)
            _orig_eot(f, g, field); _orig_eot(g, f, field)
        st["n"] += 1
    return eot


def _speed_tiebreak(A, B):
    """라벨과 무관한 동률 깨기: 세트 문자열 순서로 아주 작은 값을 더한다(동족·같은 세트면 그대로 동률)."""
    ka, kb = repr(A.spec()), repr(B.spec())
    bonus = {id(A): 1e-7 if ka > kb else 0.0, id(B): 1e-7 if kb > ka else 0.0}

    imp = {id(A): bonus[id(A)], id(B): bonus[id(B)]}
    ditto = next((bonus[id(X)] for X in (A, B) if X.ability == "imposter"), 0.0)

    def sp(s, field):                         # 메타몽은 변신한 빌드(새 객체)라 id 로 못 찾는다 → 괴짜 쪽 보너스
        return _orig_speed(s, field) + imp.get(id(s.b), ditto if s.b.entry_ability == "imposter" else 0.0)
    return sp


def _sum(A, B, branch=True):
    return duel(A, B, branch=branch) + duel(B, A, branch=branch)


def diagnose(A, B, branch=True):
    """(원래 합, 턴 종료 순서만 고친 합, 동률만 깬 합, 둘 다 고친 합)."""
    out = [_sum(A, B, branch)]
    for eot, tie in ((True, False), (False, True), (True, True)):
        engine.end_of_turn = _eot_speed_order() if eot else _orig_eot
        engine.speed = _speed_tiebreak(A, B) if tie else _orig_speed
        try:
            out.append(_sum(A, B, branch))
        finally:
            engine.speed, engine.end_of_turn = _orig_speed, _orig_eot
    return out


def spearman(x, y):
    rx = np.argsort(np.argsort(x)); ry = np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def boot_ci(v, n=2000, seed=SEED, f=np.mean):
    rng = np.random.default_rng(seed)
    v = np.asarray(v)
    s = [f(v[rng.integers(0, len(v), len(v))]) for _ in range(n)]
    return float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))


def phase_3_1(D, mine, opps, out):
    out("## 3-1 1:1 반대칭 V(A,B) + V(B,A)\n")
    builds = [("나:" + D.name(b.form), clean(b)) for b in mine] + [(e, clean(b)) for e, b, _ in opps]
    pairs = list(itertools.combinations(range(len(builds)), 2))
    out(f"대상: 내 파티 6 + 조우 가중 상위 {len(opps)} 개체(대표 세트, 유형 제거) = {len(builds)}개, 쌍 {len(pairs)}개 (동족·다른 세트 포함)")
    t0 = time.time()
    rows = []
    for i, j in pairs:
        A, B = builds[i][1], builds[j][1]
        s_br = duel(A, B) + duel(B, A)                                  # 기본(분기 모드)
        s_det = duel(A, B, branch=False) + duel(B, A, branch=False)     # 결정적 모드
        rows.append((i, j, s_br, s_det))
    out(f"계산 {time.time() - t0:.0f}s")
    S = np.array([r[2] for r in rows]); Sd = np.array([r[3] for r in rows])
    for name, arr in (("분기 모드(기본, value 가 쓰는 것)", S), ("결정적 모드(branch=False, 세트 탐색이 쓰는 것)", Sd)):
        bad = np.abs(arr) > 1e-6
        k = int(np.argmax(np.abs(arr)))
        i, j = rows[k][:2]
        out(f"- {name}: |duel(A,B)+duel(B,A)| > 1e-6 인 쌍 {bad.sum()}/{len(arr)} ({bad.mean() * 100:.1f}%), "
            f"평균 |합| {np.abs(arr).mean():.4f}, 최대 {np.abs(arr).max():.4f} ({builds[i][0]} vs {builds[j][0]})")
    # value 의 교체 항은 정확히 상쇄된다: value(A,B)+value(B,A) = 0.6·(duel(A,B)+duel(B,A))
    chk = []
    for i, j in pairs[:: max(1, len(pairs) // 60)]:
        A, B = builds[i][1], builds[j][1]
        chk.append(abs(value(A, B) + value(B, A) - 0.6 * (duel(A, B) + duel(B, A))))
    out(f"- 항등식 value(A,B)+value(B,A) = 0.6·[duel(A,B)+duel(B,A)] 확인({len(chk)}쌍): 최대 오차 {max(chk):.1e} → 교체 20/20 항은 반대칭을 깨지 않음")
    # 원인 분류: 반사실 실험 — 고치면 합이 0 이 되는 쪽이 원인
    for mode, arr, br in (("분기 모드", S, True), ("결정적 모드", Sd, False)):
        viol = [(r[0], r[1], v) for r, v in zip(rows, arr) if abs(v) > 1e-6]
        cause = {"턴 종료 처리 순서(A 먼저)": [], "스피드 동률 처리": [], "둘 다 고쳐야 0": [], "그 밖": []}
        for i, j, v in viol:
            s0, se, st_, sb = diagnose(builds[i][1], builds[j][1], br)
            c = ("턴 종료 처리 순서(A 먼저)" if abs(se) < 1e-9 else "스피드 동률 처리" if abs(st_) < 1e-9
                 else "둘 다 고쳐야 0" if abs(sb) < 1e-9 else "그 밖")
            cause[c].append((builds[i][0], builds[j][0], s0))
        out(f"- {mode} 위반 {len(viol)}쌍의 원인(반사실: 턴 종료를 스피드 순으로 / 라벨 무관 동률 깨기 / 둘 다 → 합이 0 이 되는가):")
        for c, lst in cause.items():
            if lst:
                e = max(lst, key=lambda t: abs(t[2]))
                out(f"  - {c}: {len(lst)}쌍 (최대 예 {e[0]} vs {e[1]}, 합 {e[2]:+.3f})")
    viol_pairs = [(r[0], r[1]) for r in rows if abs(r[2]) > 1e-6]
    # 확률 모드: 같은 seed 면 난수를 '행동 순서'로 소비하므로(라벨 무관) 동률 없는 쌍은 정확히 반대칭.
    rng = random.Random(SEED)
    sub = rng.sample(pairs, 40)
    mc0 = [duel(builds[i][1], builds[j][1], mc=32, seed=5) + duel(builds[j][1], builds[i][1], mc=32, seed=5) for i, j in sub]
    out(f"- 확률 모드(mc=32판/칸, seed=5), 무작위 40쌍(표본 seed {SEED}): 최대 |합| {max(abs(v) for v in mc0):.1e} — 같은 seed 면 난수 소비 순서가 라벨과 무관해 정확히 반대칭")
    mcv = [duel(builds[i][1], builds[j][1], mc=64, seed=5) + duel(builds[j][1], builds[i][1], mc=64, seed=5) for i, j in viol_pairs]
    if mcv:
        lo, hi = boot_ci(mcv)
        out(f"- 확률 모드(mc=64, seed=5), 분기 모드 위반 {len(mcv)}쌍: 합의 평균 {np.mean(mcv):+.4f} (95% 부트스트랩 CI [{lo:+.4f}, {hi:+.4f}]), "
            f"평균 |합| {np.mean(np.abs(mcv)):.4f}, 최대 {np.max(np.abs(mcv)):.4f} — 동률은 동전(rng)이라 분포상 대칭, 턴 종료 순서 비대칭은 남는다")
    return builds, rows


def phase_3_1_types(D, mine, opps, out):
    out("\n### 3-1b 상대 세트 유형(베이지안)이 만드는 구조적 비대칭\n")
    typed = [(e, b) for e, b, _ in opps if opp_types(b)]
    out(f"상위 {len(opps)} 개체 중 유형(역할 변형·alt)이 있는 개체 {len(typed)}")
    d1 = []
    for b in mine:
        for e, ob in typed:
            d1.append(value_vs(b, ob) + value_vs(ob, b))       # 행은 유형을 무시, 열만 유형 → 정보 비대칭
    d1 = np.array(d1)
    out(f"- 내 카드 A(유형 없음) × 유형 있는 상대 B: value_vs(A,B) + value_vs(B,A) 평균 {d1.mean():+.4f}, 평균 |합| {np.abs(d1).mean():.4f}, 최대 |합| {np.abs(d1).max():.4f} "
        f"(n={len(d1)}). value_vs(B,A) 는 A 가 유형이 없어 value(B,A) 와 같다 → 합 = '내가 상대 세트를 모르는 비용'(+ 엔진 비대칭)")
    d2 = []
    for (e1, b1), (e2, b2) in itertools.combinations(typed[:25], 2):
        d2.append(value_vs(b1, b2) + value_vs(b2, b1))
    d2 = np.array(d2)
    out(f"- 둘 다 유형 있는 상대끼리({len(d2)}쌍): 평균 {d2.mean():+.4f}, 평균 |합| {np.abs(d2).mean():.4f}, 최대 {np.abs(d2).max():.4f} "
        f"— 행 쪽은 언제나 '모르는 쪽', 열 쪽은 '아는 쪽'이라 두 방향이 서로 다른 게임")


def phase_3_1_blend(D, builds, out):
    out("\n### 3-1c op.gg 결합의 반대칭\n")
    keys = sorted({b.key for _, b in builds})
    errs, n = [], 0
    for a, b in itertools.combinations(keys, 2):
        ea, eb = empirical(D, a, b), empirical(D, b, a)
        if ea is None:
            continue
        n += 1
        errs.append(abs(ea + eb))
    out(f"- E(a,b)+E(b,a): 종 쌍 {n}개 중 최대 {max(errs):.1e} → E 자체는 반대칭(식: ½[x_ab − x_ba])")
    out(f"- blend 는 선형이라 (1−λ)(s−s)+λ(E−E)=0 — 반대칭을 보존. 단 동족(같은 키)은 E 없이 시뮬 값만(λ 미적용).")


def phase_3_2(D, mine, teams, out):
    out("\n## 3-2 3:3 관점 일관성 max|P_opp + P_meᵀ|\n")
    out(f"레플리카 팀 {len(teams)}개(seed {SEED}, 내 파티와 종이 겹치지 않는 팀), 상대 메가 = 스톤 든 첫 슬롯(알려진 것으로 고정)")
    my_tri = [tuple(t) for t in TRI]
    res = {"formula": [], "engine": [], "code": [], "value_gap": []}
    for ti, keys, ob, stones in teams:
        mc = [clean(b) for b in mine]
        oc = [clean(b) for b in ob]
        # (a) 식 자체: V_opp = −V_meᵀ 를 넣으면 정확히 −P_meᵀ 인가
        V = np.array([[value(a, b) for b in oc] for a in mc])
        P_me = _pick_matrix(V, my_tri, my_tri)
        res["formula"].append(np.abs(_pick_matrix(-V.T, my_tri, my_tri) + P_me.T).max())
        # (b) 같은 엔진으로 두 방향을 따로 계산(유형 없음)
        Vo = np.array([[value(b, a) for a in mc] for b in oc])
        P_opp = _pick_matrix(Vo, my_tri, my_tri)
        res["engine"].append(np.abs(P_opp + P_me.T).max())
        # (c) 코드 그대로: 내 행 × 상대 열(유형 있음) + op.gg 결합, 반대 방향도 같은 함수(상대 행 × 내 열)
        Vc = np.array([[blend(D, a.key, b.key, value_vs(a, b)) for b in ob] for a in mine])
        Voc = np.array([[blend(D, b.key, a.key, value_vs(b, a)) for a in mine] for b in ob])
        Pc, Poc = _pick_matrix(Vc, my_tri, my_tri), _pick_matrix(Voc, my_tri, my_tri)
        res["code"].append(np.abs(Poc + Pc.T).max())
        res["value_gap"].append(abs(solve(Pc)[0] + solve(Poc)[0]))
    for k, lab in (("formula", "(a) 식 자체: V_opp := −V_meᵀ"), ("engine", "(b) 같은 엔진·유형 없음(두 방향 따로 계산)"),
                   ("code", "(c) 코드 그대로(상대 열에만 유형 + op.gg 결합)"), ("value_gap", "(c) 게임 값 |v_me + v_opp|")):
        a = np.array(res[k])
        out(f"- {lab}: 팀별 최대 오차의 중앙값 {np.median(a):.4f}, 최대 {a.max():.4f}")


def phase_3_4(D, mine, opps, out):
    out("\n## 3-4 교체 혼합 0.6/0.2/0.2 의 크기\n")
    N, PA, PB, Vv = [], [], [], []
    for a in mine:
        for e, b, _ in opps:
            bc = clean(b)
            n, pa, pb = duel(a, bc), duel(a, bc, pre_hit=True), -duel(bc, a, pre_hit=True)
            N.append(n); PA.append(pa); PB.append(pb); Vv.append(0.6 * n + 0.2 * pa + 0.2 * pb)
    N, PA, PB, Vv = map(np.array, (N, PA, PB, Vv))
    flip = np.mean(np.sign(N) != np.sign(Vv))
    out(f"- 내 6 × 상위 {len(opps)} = {len(N)}쌍: 평균(PA−N) {np.mean(PA - N):+.3f} (내가 교체로 들어가 한 대 맞음), 평균(PB−N) {np.mean(PB - N):+.3f}")
    out(f"- 정면 값 N 과 혼합 값 V 의 부호가 다른 쌍 {flip * 100:.1f}%, 스피어만 ρ(N, V) = {spearman(N, Vv):.3f}")
    out(f"- 가중 0.2/0.2 는 상수: 어떤 쌍이 교체로 만나는지(선수의 선택)에 따라 달라지지 않는다")


def phase_3_5(D, out):
    out("\n## 3-5 메가 사전분포(stone_sets)\n")
    K = stone_count_dist(D)
    out(f"- 레플리카 팀 스톤 수 분포 K = P(0,1,≥2) = ({K[0]:.3f}, {K[1]:.3f}, {K[2]:.3f}), 합 {sum(K):.6f}")
    out("- 합성 예: 메가 가능 종 1마리(채용률 pm)만 있는 팀 → 그 종이 스톤을 들 확률")
    for pm in (0.05, 0.3, 0.6, 0.95):
        sc = stone_sets([pm, 0, 0, 0, 0, 0], K)
        out(f"  - pm={pm:.2f} → 모델 P(스톤) = {sum(p for p, S in sc if 0 in S):.3f}  (합 {sum(p for p, _ in sc):.6f})")
    out("- 합성 예: 메가 가능 2마리 pm=(0.9, 0.1)")
    sc = stone_sets([0.9, 0.1, 0, 0, 0, 0], K)
    out(f"  - 모델 주변확률 P(0)={sum(p for p, S in sc if 0 in S):.3f}, P(1)={sum(p for p, S in sc if 1 in S):.3f}, P(둘 다)={sum(p for p, S in sc if S == (0, 1)):.3f}")
    # 실데이터: 레플리카 팀의 실제 스톤 보유자에 대한 모델 확률(표본 내)
    from collections import Counter
    ll, ll_ind, hit, n, cond = [], [], 0, 0, Counter()
    for t in D.TEAMS:
        ks, true = [], []
        okk = True
        for j, s in enumerate(t["slots"]):
            k = s["pokemon"]
            if k not in D.DEX:
                okk = False; break
            base = D.base_of(k)
            ks.append(base)
            it = s.get("item")
            if it in D.STONE:
                true.append(j)
        if not okk or len(ks) != 6:
            continue
        pm = [mega_prob(D, k) if stones_of(D, k) else 0.0 for k in ks]
        ncand = sum(1 for p in pm if p > 0)
        cond[(ncand, min(2, len(true)))] += 1
        if not set(true) <= {j for j, p in enumerate(pm) if p > 0}:
            continue
        sc = stone_sets(pm, K)
        pr = {S: p for p, S in sc}
        S_true = tuple(sorted(true))[:2] if len(true) <= 2 else None
        if S_true is None:
            continue
        n += 1
        ll.append(math.log(max(1e-6, pr.get(S_true, 0.0))))
        hit += max(pr, key=pr.get) == S_true
        # 기준선: 종마다 독립 베르누이(pm) — 부분집합 확률을 정규화(크기 ≤2)
        subs = [S for k in range(3) for S in itertools.combinations([j for j, p in enumerate(pm) if p > 0], k)]
        w = {S: np.prod([min(pm[j], .97) if j in S else 1 - min(pm[j], .97) for j in range(6) if pm[j] > 0]) for S in subs}
        tot = sum(w.values())
        ll_ind.append(math.log(max(1e-6, w.get(S_true, 0.0) / tot)))
    out(f"- 레플리카 팀 {n}개(표본 내): 실제 스톤 보유 조합의 평균 로그우도 — 코드 모델 {np.mean(ll):.3f}, 독립 베르누이 기준선 {np.mean(ll_ind):.3f}; "
        f"코드 모델 최빈 조합 적중 {hit / n * 100:.1f}%")
    out("- 메가 가능 종 수별 실제 스톤 수 분포(레플리카): " + ", ".join(f"후보{c}종→스톤{k}: {v}" for (c, k), v in sorted(cond.items())))
    for c in (1, 2, 3, 4):
        tot = sum(v for (cc, k), v in cond.items() if cc == c)
        if not tot:
            continue
        emp = [cond[(c, k)] / tot for k in range(3)]
        kk = [K[k] if k <= c else 0 for k in range(3)]
        code = [x / sum(kk) for x in kk]
        out(f"  - 후보 {c}종 팀 {tot}개: 실제 P(스톤 0/1/2) = ({emp[0]:.2f}, {emp[1]:.2f}, {emp[2]:.2f}) vs 코드(K 를 자른 것) ({code[0]:.2f}, {code[1]:.2f}, {code[2]:.2f})")
    hi = sorted(((mega_prob(D, k), k) for k in D.USAGE if stones_of(D, k)), reverse=True)[:6]
    out("- 스톤 채용률 상위(≥0.98 이면 opp_variants 가 기본형 없이 메가만 둔다): " + ", ".join(f"{D.name(k)} {p:.2f}" for p, k in hi))


def phase_3_6(D, builds, out):
    out("\n## 3-6 op.gg 신호 E 의 척도\n")
    keys = sorted({b.key for _, b in builds})
    E, S = [], []
    byk = {}
    for _, b in builds:
        byk.setdefault(b.key, b)
    for a, b in itertools.combinations(keys, 2):
        e = empirical(D, a, b)
        if e is None:
            continue
        E.append(e); S.append(value(byk[a], byk[b]))
    E, S = np.array(E), np.array(S)
    tot = len(list(itertools.combinations(keys, 2)))
    out(f"- 종 쌍 {tot}개 중 E 있음 {len(E)} ({len(E) / tot * 100:.0f}%), |E|=1 포화 {np.mean(np.abs(E) >= 1 - 1e-9) * 100:.0f}%, E=0 {np.mean(E == 0) * 100:.0f}%")
    out(f"- 표준편차: 시뮬 {S.std():.3f}, E {E.std():.3f} · 스피어만 ρ(시뮬, E) = {spearman(S, E):.3f}")
    Vb = (1 - LAMBDA) * S + LAMBDA * E
    out(f"- λ={LAMBDA}: 결합 뒤 부호가 시뮬과 달라지는 쌍 {np.mean(np.sign(Vb) != np.sign(S)) * 100:.1f}%, ρ(시뮬, 결합) = {spearman(S, Vb):.3f}")
    out("- E 는 순위 차 /15 (목록 밖 = 30위) 이고, 종 단위라 메가/기본형·세트가 달라도 같은 값")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--teams", type=int, default=20)
    a = ap.parse_args()
    out = lambda s="": print(s, flush=True)
    D = data()
    mine = party(D)
    opps = top_opponents(D, a.top)
    out(f"# Phase 3 측정 — 데이터 {D.dir.name}, 파티 {', '.join(D.name(b.form) for b in mine)}\n")
    builds, rows = phase_3_1(D, mine, opps, out)
    phase_3_1_types(D, mine, opps, out)
    phase_3_1_blend(D, builds, out)
    teams = sample_teams(D, a.teams, exclude_keys=[b.key for b in mine])
    phase_3_2(D, mine, teams, out)
    phase_3_4(D, mine, opps, out)
    phase_3_5(D, out)
    phase_3_6(D, builds, out)


if __name__ == "__main__":
    main()
