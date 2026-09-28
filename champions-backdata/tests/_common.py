"""검증 공용 도구 — champions/ 코드는 읽기만 한다(수정·캐시 쓰기 없음).

- residuals(M, v, x, y)          행렬 게임 해의 잔차(정규화·비음·무차별·착취 가능성)
- bayes_residuals(Ms, ps, v, x, ydist)  베이지안 게임 해의 잔차(상대 유형별 최적 대응 포함)
- support_enum(M)                작은 게임의 독립 기준해(지지 집합 열거 — 단체법과 무관)
- bayes_brute_2(Ms, ps)          내 행동이 2개인 베이지안 게임의 정확해(오목 조각선형 함수의 꺾임점 전수)
"""
import itertools
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TOL = 1e-6


def residuals(M, v, x, y):
    M = np.asarray(M, dtype=float)
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    Aq = M @ y                      # 내 순수전략별 기대보수(상대 y 에 대해)
    pA = x @ M                      # 상대 순수전략별 기대보수(내 x 에 대해, 내 입장)
    sx, sy = x > 1e-9, y > 1e-9
    return {
        "sum_p-1": float(abs(x.sum() - 1)), "min_p": float(x.min()),
        "sum_q-1": float(abs(y.sum() - 1)), "min_q": float(y.min()),
        "exploit": float(Aq.max() - pA.min()),                        # ≥ 0, 균형이면 0
        "indiff_row": float(np.abs(Aq[sx] - v).max()) if sx.any() else 0.0,
        "indiff_col": float(np.abs(pA[sy] - v).max()) if sy.any() else 0.0,
        "v_gap": float(max(abs(Aq.max() - v), abs(pA.min() - v))),
    }


def ok(r, tol=TOL):
    return (r["sum_p-1"] < tol and r["min_p"] > -tol and r["sum_q-1"] < tol and r["min_q"] > -tol
            and r["exploit"] < tol and r["indiff_row"] < tol and r["indiff_col"] < tol)


def bayes_residuals(Ms, ps, v, x, ydist):
    """상대가 유형 t 를 알고 y_t 를 고르는 게임.
    내 보장값  L = Σ_t π_t min_b (xᵀ A_t)_b
    상대 보장값 U = max_a Σ_t π_t (A_t y_t)_a
    U − L = 착취 가능성(0 이면 x, {y_t} 모두 균형). 유형별 y_t 의 지지 열이 (xᵀA_t) 의 최소인지도 본다."""
    ps = np.asarray(ps, float) / sum(ps)
    x = np.asarray(x, float)
    L = sum(p * (x @ np.asarray(M)).min() for p, M in zip(ps, Ms))
    U = max(sum(p * (np.asarray(M) @ np.asarray(yt))[a] for p, M, yt in zip(ps, Ms, ydist)) for a in range(len(x)))
    br_gap = 0.0
    for M, yt in zip(Ms, ydist):
        col = x @ np.asarray(M)
        s = np.asarray(yt) > 1e-9
        br_gap = max(br_gap, float((col[s] - col.min()).max()) if s.any() else 0.0)
    return {"sum_p-1": float(abs(x.sum() - 1)), "min_p": float(x.min()),
            "sum_qt-1": float(max(abs(np.sum(yt) - 1) for yt in ydist)), "min_qt": float(min(np.min(yt) for yt in ydist)),
            "L": float(L), "U": float(U), "exploit": float(U - L), "v-L": float(v - L),
            "type_br_gap": br_gap}


def bayes_ok(r, tol=TOL):
    return (r["sum_p-1"] < tol and r["min_p"] > -tol and r["sum_qt-1"] < tol and r["min_qt"] > -tol
            and abs(r["exploit"]) < tol and abs(r["v-L"]) < tol and r["type_br_gap"] < tol)


def support_enum(M):
    """모든 균형 중 하나(값은 유일). 지지 집합 크기가 같은 쌍을 전수해 무차별 방정식을 푼다(비퇴화 가정 없이
    결과를 residuals 로 확인). 작은 게임(≤ 6×6) 전용 기준해."""
    M = np.asarray(M, dtype=float)
    m, n = M.shape
    best = None
    for k in range(1, min(m, n) + 1):
        for S in itertools.combinations(range(m), k):
            for T in itertools.combinations(range(n), k):
                A = M[np.ix_(S, T)]
                # 상대 y_T: A y = v1, Σy = 1 ;  내 x_S: xᵀA = v1ᵀ, Σx = 1
                K = np.zeros((k + 1, k + 1))
                K[:k, :k] = A
                K[:k, k] = -1
                K[k, :k] = 1
                rhs = np.zeros(k + 1)
                rhs[k] = 1
                try:
                    sy = np.linalg.solve(K, rhs)
                    K2 = K.copy()
                    K2[:k, :k] = A.T
                    sx = np.linalg.solve(K2, rhs)
                except np.linalg.LinAlgError:
                    continue
                x = np.zeros(m); y = np.zeros(n)
                x[list(S)] = sx[:k]; y[list(T)] = sy[:k]
                if x.min() < -1e-12 or y.min() < -1e-12:
                    continue
                r = residuals(M, sx[k], x, y)
                if r["exploit"] < 1e-9:
                    return float(sx[k]), x, y
    return best


def bayes_brute_2(Ms, ps):
    """내 행동 2개. f(p) = Σ_t π_t min_b [p A_t[0,b] + (1−p) A_t[1,b]] 는 오목 조각선형 → 꺾임점과 양 끝만 보면 최대."""
    ps = np.asarray(ps, float) / sum(ps)
    cand = {0.0, 1.0}
    for M in Ms:
        M = np.asarray(M, float)
        n = M.shape[1]
        for b1 in range(n):
            for b2 in range(b1 + 1, n):
                # p·a + (1−p)·c = p·b + (1−p)·d  →  p = (d−c)/((a−c)−(b−d))
                a, c = M[0, b1], M[1, b1]
                b, d = M[0, b2], M[1, b2]
                den = (a - c) - (b - d)
                if abs(den) > 1e-15:
                    p = (d - c) / den
                    if 0 <= p <= 1:
                        cand.add(float(p))
    f = lambda p: sum(pi * min(p * M[0, b] + (1 - p) * M[1, b] for b in range(np.asarray(M).shape[1]))
                      for pi, M in zip(ps, [np.asarray(M, float) for M in Ms]))
    p = max(cand, key=f)
    return f(p), np.array([p, 1 - p])


def fmt(x):
    return f"{x:.2e}" if isinstance(x, float) else str(x)
