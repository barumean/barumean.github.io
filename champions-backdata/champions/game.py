"""2인 영합 행렬 게임의 혼합전략 해 (scipy 없이 numpy 단체법).

행 플레이어가 최대화. M 을 양수로 옮긴 P 에 대해
    max Σw  s.t.  P w ≤ 1, w ≥ 0      (w = 열 전략 / 값)
를 풀면 값 v = 1/Σw, 열 전략 y = w/Σw, 행 전략 x = (여유변수의 쌍대값)/Σw.
원점이 실행 가능해서 1단계가 필요 없다. 20×20 정도는 수 ms.
"""
import numpy as np


def solve(M, tol=1e-12, max_iter=2000):
    """(값, 행 혼합전략 x, 열 혼합전략 y)."""
    M = np.asarray(M, dtype=float)
    m, n = M.shape
    lo, hi = M.min(axis=1).max(), M.max(axis=0).min()
    if hi - lo <= tol:                                   # 안장점 — 순수전략이 곧 해
        i = int(M.min(axis=1).argmax())
        j = int(M.max(axis=0).argmin())
        x = np.zeros(m); x[i] = 1
        y = np.zeros(n); y[j] = 1
        return float(lo), x, y
    shift = 1.0 - M.min()
    P = M + shift
    T = np.zeros((m + 1, n + m + 1))
    T[:m, :n] = P
    T[:m, n:n + m] = np.eye(m)
    T[:m, -1] = 1.0
    T[m, :n] = -1.0
    basis = list(range(n, n + m))
    for _ in range(max_iter):
        neg = np.where(T[m, :-1] < -tol)[0]
        if not len(neg):
            break
        c = int(neg[0])                                  # 블랜드 규칙(순환 방지)
        col = T[:m, c]
        ok = col > tol
        if not ok.any():
            break
        ratio = np.full(m, np.inf)
        ratio[ok] = T[:m, -1][ok] / col[ok]
        r = int(np.argmin(ratio))
        T[r] /= T[r, c]
        for k in range(m + 1):
            if k != r and T[k, c] != 0:
                T[k] -= T[k, c] * T[r]
        basis[r] = c
    s = T[m, -1]
    w = np.zeros(n + m)
    for r, b in enumerate(basis):
        w[b] = T[r, -1]
    y = w[:n] / s
    x = T[m, n:n + m] / s
    return float(1.0 / s - shift), x / x.sum(), y / y.sum()
