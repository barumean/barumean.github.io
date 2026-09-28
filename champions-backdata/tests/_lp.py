"""독립 LP 풀이기(검증용, scipy 없음): 2단계 단체법 + 블랜드 규칙(들어올 변수·나갈 변수 모두 최소 첨자).

    maximize  cᵀz   s.t.  A_ub z ≤ b_ub,  A_eq z = b_eq,  z ≥ 0

champions/game.py 와 코드를 공유하지 않는다(교차 검증용). 작은 문제(수백 변수) 전용.
"""
import numpy as np

EPS = 1e-10


def _pivot(T, basis, r, c):
    T[r] /= T[r, c]
    for k in range(T.shape[0]):
        if k != r and abs(T[k, c]) > 0:
            T[k] -= T[k, c] * T[r]
    basis[r] = c


def _simplex(T, basis, ncols, max_iter=50000):
    """T 의 마지막 행 = −(목적 계수) 형태(최대화). 블랜드 규칙."""
    m = T.shape[0] - 1
    for _ in range(max_iter):
        obj = T[m, :ncols]
        enter = next((j for j in range(ncols) if obj[j] < -EPS), None)
        if enter is None:
            return "optimal"
        col = T[:m, enter]
        best, leave = None, None
        for i in range(m):
            if col[i] > EPS:
                q = T[i, -1] / col[i]
                if best is None or q < best - 1e-12 or (abs(q - best) <= 1e-12 and basis[i] < basis[leave]):
                    best, leave = q, i
        if leave is None:
            return "unbounded"
        _pivot(T, basis, leave, enter)
    return "iteration_limit"


def linprog_max(c, A_ub=None, b_ub=None, A_eq=None, b_eq=None):
    c = np.asarray(c, float)
    n = len(c)
    A_ub = np.zeros((0, n)) if A_ub is None else np.asarray(A_ub, float)
    b_ub = np.zeros(0) if b_ub is None else np.asarray(b_ub, float)
    A_eq = np.zeros((0, n)) if A_eq is None else np.asarray(A_eq, float)
    b_eq = np.zeros(0) if b_eq is None else np.asarray(b_eq, float)
    mu, me = len(b_ub), len(b_eq)
    m = mu + me
    # 열: z(n) | slack(mu) | art(m)
    ns, na = mu, m
    N = n + ns + na
    T = np.zeros((m + 1, N + 1))
    basis = [0] * m
    for i in range(mu):
        sgn = 1.0 if b_ub[i] >= 0 else -1.0
        T[i, :n] = sgn * A_ub[i]
        T[i, n + i] = sgn * 1.0
        T[i, -1] = sgn * b_ub[i]
    for k in range(me):
        i = mu + k
        sgn = 1.0 if b_eq[k] >= 0 else -1.0
        T[i, :n] = sgn * A_eq[k]
        T[i, -1] = sgn * b_eq[k]
    for i in range(m):
        T[i, n + ns + i] = 1.0
        basis[i] = n + ns + i
    # 1단계: Σ art 최소화 = −Σ art 최대화 → 목적 행 = Σ art 계수(=1) 에서 기저 제거
    T[m, :] = 0.0
    T[m, n + ns:n + ns + na] = 1.0
    for i in range(m):
        T[m] -= T[i]
    st = _simplex(T, basis, N)
    if st != "optimal" or -T[m, -1] > 1e-8:
        return {"status": "infeasible", "z": None, "obj": None}
    # 기저에 남은 인공변수(값 0)를 가능하면 빼낸다
    for i in range(m):
        if basis[i] >= n + ns:
            j = next((j for j in range(n + ns) if abs(T[i, j]) > EPS), None)
            if j is not None:
                _pivot(T, basis, i, j)
    # 2단계: 인공변수 열을 막고 원래 목적
    keep = n + ns
    T2 = np.zeros((m + 1, keep + 1))
    T2[:m, :keep] = T[:m, :keep]
    T2[:m, -1] = T[:m, -1]
    T2[m, :n] = -c
    for i in range(m):
        if basis[i] < keep:
            T2[m] -= T2[m, basis[i]] * T2[i]
    # 남은 인공 기저(중복 제약)는 값 0 인 채로 둔다: 그 행은 원래 변수로 표현 불가 → 0 행
    b2 = [b if b < keep else -1 for b in basis]
    rows = [i for i in range(m) if b2[i] >= 0]
    T3 = np.vstack([T2[rows], T2[m:m + 1]])
    b3 = [b2[i] for i in rows]
    st = _simplex(T3, b3, keep)
    if st != "optimal":
        return {"status": st, "z": None, "obj": None}
    z = np.zeros(keep)
    for i, b in enumerate(b3):
        z[b] = T3[i, -1]
    return {"status": "optimal", "z": z[:n], "obj": float(c @ z[:n])}


def game_value(M):
    """행 최대화 행렬 게임을 LP 로: max v s.t. Mᵀx ≥ v, Σx=1, x≥0 (v 는 두 비음 변수 차)."""
    M = np.asarray(M, float)
    m, n = M.shape
    # 변수: x(m), v+, v-
    c = np.r_[np.zeros(m), 1.0, -1.0]
    A_ub = np.c_[-M.T, np.ones(n), -np.ones(n)]     # v − xᵀM_j ≤ 0
    b_ub = np.zeros(n)
    A_eq = np.r_[np.ones(m), 0.0, 0.0][None, :]
    r = linprog_max(c, A_ub, b_ub, A_eq, [1.0])
    z = r["z"]
    return r["obj"], z[:m]


def bayes_value(Ms, ps):
    """Phase 2 의 G8 LP: max Σ π_t w_t  s.t. w_t ≤ Σ_a p_a A_t[a,b] ∀t,b,  Σp=1, p≥0 (w_t 자유 → 두 비음 차)."""
    Ms = [np.asarray(M, float) for M in Ms]
    ps = np.asarray(ps, float) / np.sum(ps)
    m, T = Ms[0].shape[0], len(Ms)
    nv = m + 2 * T
    c = np.r_[np.zeros(m), np.ravel([[p, -p] for p in ps])]
    rows, rhs = [], []
    for t, M in enumerate(Ms):
        for b in range(M.shape[1]):
            r = np.zeros(nv)
            r[:m] = -M[:, b]
            r[m + 2 * t], r[m + 2 * t + 1] = 1.0, -1.0
            rows.append(r); rhs.append(0.0)
    A_eq = np.r_[np.ones(m), np.zeros(2 * T)][None, :]
    res = linprog_max(c, np.array(rows), np.array(rhs), A_eq, [1.0])
    return res["obj"], res["z"][:m]
