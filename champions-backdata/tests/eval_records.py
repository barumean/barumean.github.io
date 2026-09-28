"""5-4 실전 기록 평가 프로토콜 — 5-3(모델 대 모델 분해)과 별개. 기록 파일이 없으면 표본 크기 계산만 한다.

실행:  python tests/eval_records.py [--records tests/fixtures/records.csv] [--party tests/fixtures/party_20260927.txt]

'일치'의 정의(먼저 고정):
  (P) 상대 선출 예측 적중: 실제 상대가 낸 3마리(집합)가 모델의 상대 선출 분포 y 에서
      top-1 / top-3 안에 드는가. 로그우도 = log y(실제 조합) (0 방지: y' = 0.95·y + 0.05/20).
  (R) 내 선출 추천 일치: 내가 실제로 낸 3마리가 모델의 내 혼합 x 의 top-1 / top-3 안인가.
      (x 는 혼합전략이므로 top-1 일치는 '정답'이 아니다. 판정 지표는 로그우도 log x'(실제))
  승패와의 관계(보정)는 기록 수가 수백 단위가 되어야 의미가 있다.
기준선: 무작위(조합 1/20 → top-1 5%, top-3 15%, 로그우도 −3.00), 사용률 모델(상대 포켓몬별 가중 w_j = exp(−(싱글 순위−1)/25),
       조합 확률 ∝ Π w_j — meta.opponents 의 사전값과 같은 형태).

CSV 열(머리줄 필수, 이름은 한국어/영어 모두 D.mon 으로 해석):
  opp6        상대 6마리, 쉼표 구분(따옴표로 묶기)
  opp_pick    상대가 실제로 낸 3마리
  my_pick     내가 실제로 낸 3마리(선택)
  opp_mega    메가진화한 상대(선택)
  result      승/패(선택)
"""
import argparse
import csv
import math
import os

import numpy as np

import _common  # noqa: F401
from _fixtures import data, HERE


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def binom_tail(k, n, p):
    """P(X ≥ k), X ~ Bin(n, p)."""
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def power_note(out):
    out("## 표본 크기 — 기록 10개로 무엇을 말할 수 있나\n")
    lo, hi = wilson(3, 10)
    out(f"- 3/10 일치의 95% Wilson 구간: [{lo:.2f}, {hi:.2f}] — 폭 {hi - lo:.2f}.")
    out(f"- top-1 무작위(5%) 대비: P(X≥3 | n=10, p=0.05) = {binom_tail(3, 10, 0.05):.4f} → 무작위보다는 낫다고 말할 수 있다.")
    out(f"- top-3 무작위(15%) 대비 3/10: P(X≥3 | p=0.15) = {binom_tail(3, 10, 0.15):.3f} → 구분 불가.")
    for p0, p1 in ((0.30, 0.50), (0.30, 0.45), (0.30, 0.40)):
        n = next(n for n in range(5, 5000) if (1.96 * math.sqrt(p0 * (1 - p0) / n) + 0.84 * math.sqrt(p1 * (1 - p1) / n)) <= p1 - p0)
        out(f"- 일치율 {p0:.0%} → {p1:.0%} 개선을 한쪽 5%·검정력 80% 로 구분하려면 약 n = {n} 경기(단일 표본 근사)")
    out("- 5-3 의 단계(교체 혼합·집계식·LP·메가·op.gg)마다 기여를 실전으로 판정하려면 단계 수만큼 비교가 늘어 n 이 수백 이상 필요 → 10경기로는 판정 불가.")
    out("- 주의: README 의 '10경기 중 3경기 일치'는 실전 기록이 아니라 '3:3 연속 평가 시제품과 선출 추천이 같은가'(모델 대 모델)다.\n")


def usage_model(D, keys):
    tri = [tuple(t) for t in __import__("champions.team", fromlist=["TRI"]).TRI]
    w = np.array([math.exp(-((D.RANK.get(k) or 300) - 1) / 25) + 0.02 for k in keys])
    p = np.array([np.prod(w[list(t)]) for t in tri])
    return tri, p / p.sum()


def evaluate(D, mine, rows, out):
    from champions.pick import advise
    tri = None
    hit = {"model": [0, 0], "usage": [0, 0]}
    ll = {"model": [], "usage": [], "random": []}
    myhit, myll = [0, 0], []
    for r in rows:
        keys = [D.base_of(D.mon(x.strip())) for x in r["opp6"].split(",")]
        actual = frozenset(keys.index(D.base_of(D.mon(x.strip()))) for x in r["opp_pick"].split(","))
        res = advise(D, mine, keys)
        from champions.team import TRI
        tri = [tuple(t) for t in TRI]
        ym = np.zeros(20)
        for t, p in res["their_mix"]:
            ym[tri.index(t)] = p
        ym = ym / ym.sum() if ym.sum() > 0 else np.full(20, 1 / 20)
        _, yu = usage_model(D, keys)
        for name, y in (("model", ym), ("usage", yu)):
            order = [frozenset(tri[k]) for k in np.argsort(-y)]
            hit[name][0] += order[0] == actual
            hit[name][1] += actual in order[:3]
            ll[name].append(math.log(0.95 * y[tri.index(tuple(sorted(actual)))] + 0.05 / 20))
        ll["random"].append(math.log(1 / 20))
        if r.get("my_pick"):
            mk = [b.key for b in mine]
            mact = tuple(sorted(mk.index(D.base_of(D.mon(x.strip()))) for x in r["my_pick"].split(",")))
            xm = np.zeros(20)
            for t, p, _ in res["mix"]:
                xm[tri.index(t)] = p
            order = [tri[k] for k in np.argsort(-xm)]
            myhit[0] += order[0] == mact
            myhit[1] += mact in order[:3]
            myll.append(math.log(0.95 * xm[tri.index(mact)] / max(1e-12, xm.sum()) + 0.05 / 20))
    n = len(rows)
    out(f"## 기록 {n}경기 평가\n")
    out("| 모델 | top-1 (95% CI) | top-3 (95% CI) | 평균 로그우도 |")
    out("|---|---|---|---|")
    for name in ("model", "usage"):
        h1, h3 = hit[name]
        out(f"| {name} | {h1}/{n} {wilson(h1, n)} | {h3}/{n} {wilson(h3, n)} | {np.mean(ll[name]):.3f} |")
    out(f"| random | 기대 5% | 기대 15% | {np.mean(ll['random']):.3f} |")
    if myll:
        out(f"\n내 선출이 모델 혼합의 top-1: {myhit[0]}/{len(myll)}, top-3: {myhit[1]}/{len(myll)}, 로그우도 {np.mean(myll):.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default=os.path.join(HERE, "fixtures", "records.csv"))
    a = ap.parse_args()
    out = lambda s="": print(s, flush=True)
    out("# 5-4 실전 기록 평가\n")
    power_note(out)
    if not os.path.exists(a.records):
        out(f"기록 파일 없음({a.records}) — 평가 불가. 양식: tests/fixtures/records_template.csv")
        return
    D = data()
    from _fixtures import party
    rows = list(csv.DictReader(open(a.records, encoding="utf-8-sig")))
    evaluate(D, party(D), rows, out)


if __name__ == "__main__":
    main()
