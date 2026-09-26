"""상성 행렬 V[내 카드, 상대 개체] = 시뮬레이션 값과 op.gg 실전 승패 신호의 혼합.

실전 신호 E(a,b): op.gg 가 포켓몬마다 주는 '가장 많이 이긴 상대 30' / '가장 많이 진 상대 30' 순위.
두 목록 모두 상대의 등장 빈도에 끌려가므로(흔한 상대는 양쪽 다 위에 있다) 절대 순위가 아니라
'진 목록 순위 − 이긴 목록 순위' 의 차이만 쓴다. a 쪽 목록과 b 쪽 목록을 반대칭으로 평균한다.
혼합: V = (1−λ)·sim + λ·E  (신호가 있는 쌍만, λ 기본 0.2)
"""
import os
from concurrent.futures import ProcessPoolExecutor

from .engine import value, value_vs

LAMBDA = 0.2
_LIST = 30


def _pos(lst, k):
    try:
        return lst.index(k)
    except ValueError:
        return _LIST


def empirical_one(D, a, b):
    u = D.USAGE.get(a)
    if not u:
        return None
    pw, pl = _pos(u["win"]["pokemon"], b), _pos(u["lose"]["pokemon"], b)
    if pw == _LIST and pl == _LIST:
        return None
    return max(-1.0, min(1.0, (pl - pw) / 15.0))


def empirical(D, a, b):
    """base 키 기준 E(a,b) ∈ [-1,1] 또는 None."""
    x, y = empirical_one(D, a, b), empirical_one(D, b, a)
    if x is None and y is None:
        return None
    return 0.5 * ((x or 0.0) - (y or 0.0)) if (x is not None and y is not None) else (x if x is not None else -y)


def blend(D, card_key, opp_key, sim, lam=LAMBDA):
    e = empirical(D, card_key, opp_key)
    return sim if e is None or card_key == opp_key else (1 - lam) * sim + lam * e


# ── 병렬 계산 ────────────────────────────────────────────────────
_W = {}


def _init(my_specs, opp_specs, mirror_zero=True):
    from .data import load
    from .engine import Build
    from .meta import make_alt, attach_variants
    D = load()
    _W["D"] = D
    _W["my"] = [Build(D, **s) for s in my_specs]
    _W["opp"] = []
    for s in opp_specs:                                # 스펙에는 변형이 없으므로 여기서 다시 붙인다
        roles = s.get("_roles")
        b = Build(D, **{k: v for k, v in s.items() if k != "_roles"})
        b.alt = make_alt(D, b)
        if roles:
            attach_variants(D, b, [(Build(D, **rs), p) for rs, p in roles])
        _W["opp"].append(b)
    _W["mz"] = mirror_zero


def _row(i):
    D, A = _W["D"], _W["my"][i]
    return [0.0 if (_W["mz"] and B.key == A.key) else blend(D, A.key, B.key, value_vs(A, B)) for B in _W["opp"]]


def opp_spec(b):
    """상대 세트 스펙 + 역할별 세트(있으면) — 작업 프로세스로 넘겨 다시 만든다."""
    s = b.spec()
    if b.roles and len(b.roles) > 1:
        s["_roles"] = [(rb.spec(), p) for rb, p in b.roles]
    return s


def compute(my_builds, opp_builds, workers=None, mirror_zero=True):
    """행 = my_builds, 열 = opp_builds. 여러 프로세스로 나눠 계산.
    mirror_zero=True 면 같은 종끼리는 0(팀 탐색용 관례). 실전 선출 보드는 세트가 다르므로 False 로 실제 값을 쓴다."""
    my_specs = [b.spec() for b in my_builds]
    opp_specs = [opp_spec(b) for b in opp_builds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or len(my_builds) * len(opp_builds) < 400:
        _init(my_specs, opp_specs, mirror_zero)
        return [_row(i) for i in range(len(my_builds))]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(my_specs, opp_specs, mirror_zero)) as ex:
        return list(ex.map(_row, range(len(my_builds)), chunksize=2))


# ── 민감도 분석용: 상성값을 구성 요소로 나눠 계산(M6) ──
def _parts_row(i):
    from .engine import duel_bayes, opp_types
    A = _W["my"][i]
    out = []
    for B in _W["opp"]:
        if B.key == A.key:
            out.append((0.0, 0.0, 0.0))
            continue
        Bs, ps = opp_types(B) or ([B], [1.0])
        out.append((duel_bayes(A, Bs, ps, None), duel_bayes(A, Bs, ps, "A"), duel_bayes(A, Bs, ps, "B")))
    return out


def compute_parts(my_builds, opp_builds, workers=None):
    """(N, PA, PB): 정면, 내가 교체로 들어가 한 대 맞음, 상대가 그렇게 들어옴(모두 내 입장, 실전 신호 섞기 전).
    value = (1−2w)·N + w·PA + w·PB (w = 교체 등장 가중, 기본 0.2). 같은 종끼리는 0(팀 탐색 관례)."""
    import numpy as np
    my_specs = [b.spec() for b in my_builds]
    opp_specs = [opp_spec(b) for b in opp_builds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(my_specs, opp_specs, True)) as ex:
        rows = list(ex.map(_parts_row, range(len(my_builds)), chunksize=2))
    arr = np.array(rows, dtype=np.float32)                  # (카드, 상대, 3)
    return arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]


def combine(D, card_keys, opp_keys, N, PA, PB, lam=LAMBDA, w=0.2, scale="linear"):
    """구성 요소 → 상성 행렬. lam = 실전 신호 가중, w = 교체 등장 가중, scale = 'linear' | 'sign'(승패 부호만)."""
    import numpy as np
    sim = (1 - 2 * w) * N + w * PA + w * PB
    V = sim.copy()
    for i, a in enumerate(card_keys):
        for j, b in enumerate(opp_keys):
            if a == b:
                V[i, j] = 0.0
                continue
            e = empirical(D, a, b)
            if e is not None:
                V[i, j] = (1 - lam) * sim[i, j] + lam * e
    if scale == "sign":
        V = np.sign(V)
    return V.astype(np.float32)


SPLIT_SEED = 20260926   # 종을 조정용/보류용 두 묶음으로 나누는 고정 시드(M2-3). 앞으로 모델 조정 판단은 A 묶음만 본다.


def type_baseline(a, b):
    """한 줄 기준선(M2-2): 각자 자기 타입 기술로 상대에게 줄 수 있는 최대 상성 배율의 차."""
    from .engine import type_eff
    return max(type_eff(t, b.types) for t in a.types) - max(type_eff(t, a.types) for t in b.types)


def _ranks(v):
    import numpy as np
    v = np.asarray(v, dtype=float)
    o = np.argsort(v, kind="mergesort")
    r = np.empty(len(v))
    r[o] = np.arange(len(v))
    # 동점은 평균 순위
    _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
    sums = np.zeros(len(cnt))
    np.add.at(sums, inv, r)
    return sums[inv] / cnt[inv]


def _spearman(x, y, w=None):
    import numpy as np
    rx, ry = _ranks(x), _ranks(y)
    w = np.ones(len(rx)) if w is None else np.asarray(w, dtype=float)
    mx, my = np.average(rx, weights=w), np.average(ry, weights=w)
    cov = np.average((rx - mx) * (ry - my), weights=w)
    return float(cov / np.sqrt(np.average((rx - mx) ** 2, weights=w) * np.average((ry - my) ** 2, weights=w)))


def validate_1v1(D, builds, n_boot=400, seed=SPLIT_SEED):
    """1:1 층 검증(M2): 시뮬과 op.gg 실전 신호 E 의 스피어만 ρ 와
    - 종 단위 군집 부트스트랩 95% 구간(쌍들이 종을 공유하므로 쌍 독립 가정은 SE 를 과소추정)
    - 타입 상성 기준선의 ρ 와, 시뮬 − 기준선 증분의 군집 구간, 타입을 통제한 부분상관
    - 종을 고정 시드로 A(조정용)/B(보류용) 묶음으로 나눈 각 묶음 안의 ρ"""
    import numpy as np
    keys = [b.key for b in builds]
    I, J, S, T, E = [], [], [], [], []
    for i, a in enumerate(builds):
        for j in range(i + 1, len(builds)):
            b = builds[j]
            if a.key == b.key:
                continue
            e = empirical(D, a.key, b.key)
            if e is None:
                continue
            I.append(i); J.append(j); S.append(value(a, b)); T.append(type_baseline(a, b)); E.append(e)
    I, J, S, T, E = map(np.asarray, (I, J, S, T, E))
    if len(E) < 10:
        return None
    rho_s, rho_t = _spearman(S, E), _spearman(T, E)
    # 타입을 통제한 부분상관: 순위를 타입 순위에 선형 회귀한 잔차끼리
    rs, rt, re = _ranks(S), _ranks(T), _ranks(E)
    def resid(y):
        A = np.c_[np.ones(len(rt)), rt]
        return y - A @ np.linalg.lstsq(A, y, rcond=None)[0]
    partial = float(np.corrcoef(resid(rs), resid(re))[0, 1])
    rng = np.random.default_rng(seed)
    n = len(builds)
    bs, bt, bd = [], [], []
    for _ in range(n_boot):
        c = np.bincount(rng.integers(0, n, n), minlength=n)     # 종을 복원추출한 횟수
        w = c[I] * c[J]
        if w.sum() < 10:
            continue
        a_, b_ = _spearman(S, E, w), _spearman(T, E, w)
        bs.append(a_); bt.append(b_); bd.append(a_ - b_)
    q = lambda v: (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)))
    perm = np.random.default_rng(seed).permutation(n)
    half = np.zeros(n, dtype=int)
    half[perm[n // 2:]] = 1                                      # 0 = A(조정용), 1 = B(보류용)
    halves = {}
    for h in (0, 1):
        mask = (half[I] == h) & (half[J] == h)
        halves["AB"[h]] = (_spearman(S[mask], E[mask]) if mask.sum() >= 10 else None, int(mask.sum()))
    return {"n_pairs": int(len(E)), "n_species": n, "rho": rho_s, "rho_ci": q(bs), "se": float(np.std(bs)),
            "rho_type": rho_t, "rho_type_ci": q(bt), "delta": rho_s - rho_t, "delta_ci": q(bd), "partial": partial,
            "halves": halves, "half_of": {k: "AB"[h] for k, h in zip(keys, half)}}


def sim_vs_empirical(D, builds):
    """모델 점검: 시뮬레이션 값과 실전 신호의 순위 상관(스피어만)."""
    xs, ys = [], []
    for i, a in enumerate(builds):
        for b in builds[i + 1:]:
            if a.key == b.key:
                continue
            e = empirical(D, a.key, b.key)
            if e is None:
                continue
            xs.append(value(a, b))
            ys.append(e)

    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for k, i in enumerate(o):
            r[i] = k
        return r

    if len(xs) < 10:
        return None, len(xs)
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy), n
