"""상성 행렬 V[내 카드, 상대 개체] = 시뮬레이션 값과 op.gg 실전 승패 신호의 혼합.

실전 신호 E(a,b): op.gg 가 포켓몬마다 주는 '가장 많이 이긴 상대 30' / '가장 많이 진 상대 30' 순위.
두 목록 모두 상대의 등장 빈도에 끌려가므로(흔한 상대는 양쪽 다 위에 있다) 절대 순위가 아니라
'진 목록 순위 − 이긴 목록 순위' 의 차이만 쓴다. a 쪽 목록과 b 쪽 목록을 반대칭으로 평균한다.
혼합: V = (1−λ)·sim + λ·E  (신호가 있는 쌍만, λ 기본 0.2)
"""
import os
from concurrent.futures import ProcessPoolExecutor

from .engine import value

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
    D = load()
    _W["D"] = D
    _W["my"] = [Build(D, **s) for s in my_specs]
    _W["opp"] = [Build(D, **s) for s in opp_specs]
    _W["mz"] = mirror_zero


def _row(i):
    D, A = _W["D"], _W["my"][i]
    return [0.0 if (_W["mz"] and B.key == A.key) else blend(D, A.key, B.key, value(A, B)) for B in _W["opp"]]


def compute(my_builds, opp_builds, workers=None, mirror_zero=True):
    """행 = my_builds, 열 = opp_builds. 여러 프로세스로 나눠 계산.
    mirror_zero=True 면 같은 종끼리는 0(팀 탐색용 관례). 실전 선출 보드는 세트가 다르므로 False 로 실제 값을 쓴다."""
    my_specs = [b.spec() for b in my_builds]
    opp_specs = [b.spec() for b in opp_builds]
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    if workers == 1 or len(my_builds) * len(opp_builds) < 400:
        _init(my_specs, opp_specs, mirror_zero)
        return [_row(i) for i in range(len(my_builds))]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(my_specs, opp_specs, mirror_zero)) as ex:
        return list(ex.map(_row, range(len(my_builds)), chunksize=2))


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
