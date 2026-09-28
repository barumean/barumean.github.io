"""Phase 2 — solver 자체 검증(toy game). payoff 모델과 무관하게 game.solve / game.solve_bayes 만 본다.

실행:  python tests/test_phase2_solver.py          (표 출력 + unittest)
       python -m unittest tests.test_phase2_solver
허용 오차 TOL = 1e-6 (tests/_common.py).
"""
import itertools
import sys
import unittest

import numpy as np

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import TOL, residuals, ok, bayes_residuals, bayes_ok, support_enum, bayes_brute_2
from champions.game import solve, solve_bayes

RPS = np.array([[0, -1, 1], [1, 0, -1], [-1, 1, 0]], float)
G1 = np.array([[3, -1, 4], [2, -2, 3], [-1, 2, 0]], float)      # 행1 < 행0 (강지배), 열2 > 열0 (최소화 쪽 강지배)
G4 = np.array([[3, 1, 4], [2, 0, 1], [5, 2, 6]], float)         # 안장점 (2,1) 값 2
G5 = np.array([[1, 1], [0, 2], [2, 0]], float)                   # 행 균형이 여럿(행0, (0,½,½), 그 혼합)
# G8: 상대 유형 2개(0.5/0.5). 이론해(LP 를 손으로 풂):
#   f(p) = ½·min(−2−p, 1−p) + ½·min(3−6p, 4p−2)  → p<½ 에서 −2+1.5p, p>½ 에서 ½−3.5p  → 유일한 최대 p=½, v_B = −1.25
#   유형1 최적 대응 = 열0(엄격), 유형2 = (0.3, 0.7)(내 무차별 조건에서)
#   기대행렬 ½(A1+A2) = [[−3,1],[½,−½]] 의 값 v_A = −0.2, x_A = (0.2, 0.8) → x_A 의 실제 보장값 f(0.2) = −1.7
G8_A1 = np.array([[-3, 0], [-2, 1]], float)
G8_A2 = np.array([[-3, 2], [3, -2]], float)


def _row(name, theory, got, r, note=""):
    return f"| {name} | {theory} | {got} | exploit {r['exploit']:.1e} · indiff {max(r['indiff_row'], r['indiff_col']):.1e} | {note} |"


def table():
    L = ["| 게임 | 이론값 | solver 결과 | 잔차(착취·무차별) | 비고 |", "|---|---|---|---|---|"]
    v, x, y = solve(G1); r = residuals(G1, v, x, y)
    L.append(_row("G1 강지배", "v=5/7=0.714286, x=(3/7,0,4/7), y=(3/7,4/7,0)",
                  f"v={v:.6f}, x={np.round(x, 6).tolist()}, y={np.round(y, 6).tolist()}", r,
                  f"지배 행 확률 {x[1]:.1e}, 지배 열 확률 {y[2]:.1e}"))
    MP = np.array([[1, -1], [-1, 1]], float)
    v, x, y = solve(MP); r = residuals(MP, v, x, y)
    L.append(_row("G2 동전 맞추기", "v=0, p=q=(½,½)", f"v={v:.2e}, x={np.round(x, 6).tolist()}, y={np.round(y, 6).tolist()}", r))
    v, x, y = solve(RPS); r = residuals(RPS, v, x, y)
    L.append(_row("G3 가위바위보", "v=0, 각 ⅓", f"v={v:.2e}, x={np.round(x, 6).tolist()}, y={np.round(y, 6).tolist()}", r))
    v, x, y = solve(G4); r = residuals(G4, v, x, y)
    L.append(_row("G4 안장점", "v=2, x=e3, y=e2", f"v={v}, x={x.tolist()}, y={y.tolist()}", r))
    v, x, y = solve(G5); r = residuals(G5, v, x, y)
    L.append(_row("G5 다중 균형", "v=1, x∈{e1, (0,½,½), 혼합}, y=(½,½)", f"v={v:.6f}, x={np.round(x, 6).tolist()}, y={np.round(y, 6).tolist()}", r,
                  "균형 조건만 확인"))
    D6 = np.vstack([RPS, RPS[0]])
    v6, x6, y6 = solve(D6); r = residuals(D6, v6, x6, y6)
    D6c = np.hstack([RPS, RPS[:, [1]]])
    v6c, x6c, y6c = solve(D6c); rc = residuals(D6c, v6c, x6c, y6c)
    L.append(_row("G6 복제 전략", "v=0 (RPS 와 같음)", f"행 복제 v={v6:.2e}, 열 복제 v={v6c:.2e}", {"exploit": max(r["exploit"], rc["exploit"]),
                  "indiff_row": max(r["indiff_row"], rc["indiff_row"]), "indiff_col": max(r["indiff_col"], rc["indiff_col"])},
                  f"복제 행 확률 합 {x6[0] + x6[3]:.4f}"))
    rng = np.random.default_rng(7)
    U = rng.normal(size=(9, 9)); S = U - U.T
    v7, x7, y7 = solve(S); r7 = residuals(S, v7, x7, y7); r7b = residuals(S, 0.0, y7, x7)
    L.append(_row("G7 대칭 A=−Aᵀ (9×9, seed 7)", "v=0, x·y 모두 양쪽 균형", f"v={v7:.2e}", r7,
                  f"(y,x) 로 바꿔 넣어도 exploit {r7b['exploit']:.1e}"))
    vB, xB, yd = solve_bayes([G8_A1, G8_A2], [0.5, 0.5])
    rb = bayes_residuals([G8_A1, G8_A2], [0.5, 0.5], vB, xB, yd)
    vT, xT = bayes_brute_2([G8_A1, G8_A2], [0.5, 0.5])
    vA = solve(0.5 * G8_A1 + 0.5 * G8_A2)[0]
    L.append(f"| G8 베이지안 | 손 풀이 v=−1.25, x=(½,½), y₁=(1,0), y₂=(0.3,0.7); 꺾임점 전수 v={vT:.6f}, x={np.round(xT, 6).tolist()} | v={vB:.6f}, x={np.round(xB, 6).tolist()}, "
             f"y_t={[np.round(t, 4).tolist() for t in yd]} | U−L {rb['exploit']:.1e} · 유형별 최적대응 틈 {rb['type_br_gap']:.1e} | "
             f"value(B) {vB:.4f} ≤ value(A: 기대행렬) {vA:.4f}; x_A 의 실제 보장값 {sum(0.5 * (solve(0.5 * G8_A1 + 0.5 * G8_A2)[1] @ M).min() for M in (G8_A1, G8_A2)):.4f} |")
    return "\n".join(L)


class ToyGames(unittest.TestCase):
    def check(self, M, v_theory=None):
        v, x, y = solve(M)
        r = residuals(M, v, x, y)
        self.assertTrue(ok(r), r)
        if v_theory is not None:
            self.assertAlmostEqual(v, v_theory, delta=TOL)
        return v, x, y

    def test_G1_strictly_dominated(self):
        v, x, y = self.check(G1, 5 / 7)
        self.assertLess(x[1], TOL)
        self.assertLess(y[2], TOL)
        np.testing.assert_allclose(x, [3 / 7, 0, 4 / 7], atol=TOL)
        np.testing.assert_allclose(y, [3 / 7, 4 / 7, 0], atol=TOL)

    def test_G2_matching_pennies(self):
        v, x, y = self.check(np.array([[1, -1], [-1, 1]], float), 0.0)
        np.testing.assert_allclose(x, [.5, .5], atol=TOL)
        np.testing.assert_allclose(y, [.5, .5], atol=TOL)

    def test_G3_rps(self):
        v, x, y = self.check(RPS, 0.0)
        np.testing.assert_allclose(x, [1 / 3] * 3, atol=TOL)
        np.testing.assert_allclose(y, [1 / 3] * 3, atol=TOL)

    def test_G4_saddle(self):
        v, x, y = self.check(G4, 2.0)
        self.assertEqual(int(x.argmax()), 2)
        self.assertEqual(int(y.argmax()), 1)

    def test_G5_multiple_equilibria(self):
        self.check(G5, 1.0)

    def test_G6_duplicates(self):
        rng = np.random.default_rng(11)
        for _ in range(50):
            M = rng.normal(size=(5, 6))
            v = solve(M)[0]
            i, j = rng.integers(5), rng.integers(6)
            self.assertAlmostEqual(solve(np.vstack([M, M[i]]))[0], v, delta=TOL)
            self.assertAlmostEqual(solve(np.hstack([M, M[:, [j]]]))[0], v, delta=TOL)

    def test_G7_skew_symmetric(self):
        rng = np.random.default_rng(7)
        for n in (2, 3, 5, 9, 20):
            U = rng.normal(size=(n, n)); S = U - U.T
            v, x, y = self.check(S, 0.0)
            self.assertTrue(ok(residuals(S, 0.0, y, x)))

    def test_G8_bayes(self):
        Ms, ps = [G8_A1, G8_A2], [0.5, 0.5]
        v, x, yd = solve_bayes(Ms, ps)
        self.assertTrue(bayes_ok(bayes_residuals(Ms, ps, v, x, yd)))
        vT, xT = bayes_brute_2(Ms, ps)
        self.assertAlmostEqual(v, vT, delta=TOL)
        self.assertAlmostEqual(v, -1.25, delta=TOL)
        np.testing.assert_allclose(x, [0.5, 0.5], atol=TOL)
        np.testing.assert_allclose(yd[0], [1, 0], atol=TOL)
        np.testing.assert_allclose(yd[1], [0.3, 0.7], atol=TOL)
        vA, xA, _ = solve(0.5 * G8_A1 + 0.5 * G8_A2)
        self.assertAlmostEqual(vA, -0.2, delta=TOL)
        self.assertLessEqual(v, vA + TOL)
        # 기대행렬로 푼 x_A 를 실제(유형을 아는 상대) 게임에 쓰면 보장값이 v_B 보다 낮다 — 모형 A 의 낙관 편향
        LA = sum(0.5 * (xA @ M).min() for M in Ms)
        self.assertAlmostEqual(LA, -1.7, delta=TOL)

    def test_bayes_random_2actions_vs_brute(self):
        rng = np.random.default_rng(3)
        for _ in range(200):
            T = int(rng.integers(2, 5)); n = int(rng.integers(2, 5))
            Ms = [rng.normal(size=(2, n)) for _ in range(T)]
            ps = rng.dirichlet(np.ones(T))
            v, x, yd = solve_bayes(Ms, ps)
            vT, _ = bayes_brute_2(Ms, ps)
            self.assertAlmostEqual(v, vT, delta=TOL)
            self.assertTrue(bayes_ok(bayes_residuals(Ms, ps, v, x, yd)))
            self.assertLessEqual(v, solve(sum(p * M for p, M in zip(ps, Ms)))[0] + TOL)

    def test_bayes_random_pick_sized(self):
        """선출 크기(20×20, 유형 2~8)에서 착취 가능성 인증(U−L)으로 확인 — 기준 LP 없이도 최적성 증명."""
        rng = np.random.default_rng(5)
        for _ in range(40):
            T = int(rng.integers(2, 9))
            Ms = [rng.uniform(-1, 1, size=(20, 20)) for _ in range(T)]
            ps = rng.dirichlet(np.ones(T))
            v, x, yd = solve_bayes(Ms, ps)
            r = bayes_residuals(Ms, ps, v, x, yd)
            self.assertTrue(bayes_ok(r), r)

    def test_random_vs_support_enum(self):
        rng = np.random.default_rng(1)
        for _ in range(300):
            m, n = int(rng.integers(1, 6)), int(rng.integers(1, 6))
            M = rng.normal(size=(m, n))
            v, x, y = self.check(M)
            ref = support_enum(M)
            self.assertIsNotNone(ref)
            self.assertAlmostEqual(v, ref[0], delta=TOL)

    def test_degenerate_integer_games(self):
        """{-1,0,1} 정수 행렬(동률·퇴화가 많음 — 선출 행렬의 max/min 합산도 동률이 잦다)에서 순환·반복 한도 문제가 없는지."""
        rng = np.random.default_rng(2)
        bad = 0
        for _ in range(500):
            m, n = int(rng.integers(2, 21)), int(rng.integers(2, 21))
            M = rng.integers(-1, 2, size=(m, n)).astype(float)
            v, x, y = solve(M)
            if not ok(residuals(M, v, x, y)):
                bad += 1
        self.assertEqual(bad, 0)

    def test_independent_lp_cross_check(self):
        """독립 LP(tests/_lp.py, 2단계 단체법·블랜드)와 값 비교: 일반 게임 + G8 식의 베이지안 LP."""
        from _lp import game_value, bayes_value
        rng = np.random.default_rng(9)
        for _ in range(60):
            M = rng.normal(size=(int(rng.integers(2, 12)), int(rng.integers(2, 12))))
            self.assertAlmostEqual(game_value(M)[0], solve(M)[0], delta=TOL)
        self.assertAlmostEqual(bayes_value([G8_A1, G8_A2], [.5, .5])[0], -1.25, delta=TOL)
        for _ in range(40):
            T = int(rng.integers(2, 6)); m = int(rng.integers(2, 10)); n = int(rng.integers(2, 10))
            Ms = [rng.normal(size=(m, n)) for _ in range(T)]
            ps = rng.dirichlet(np.ones(T))
            self.assertAlmostEqual(bayes_value(Ms, ps)[0], solve_bayes(Ms, ps)[0], delta=TOL)

    def test_permutation_invariance(self):
        rng = np.random.default_rng(4)
        for _ in range(100):
            M = rng.normal(size=(8, 7))
            pr, pc = rng.permutation(8), rng.permutation(7)
            self.assertAlmostEqual(solve(M)[0], solve(M[pr][:, pc])[0], delta=TOL)


if __name__ == "__main__":
    print(table())
    print()
    unittest.main(argv=[sys.argv[0], "-v"])
