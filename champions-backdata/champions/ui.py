"""선출 보드(실전용 HTML) 생성.

내 파티 6마리 × 상대 후보 전체(기본형·메가형)의 상성 값을 미리 계산해 한 HTML 파일에 넣는다.
브라우저에서는 상대 6마리를 고르기만 하면 3/6 선출 게임을 LP 로 풀어 ① 선봉 ② ③ 순서를 보여준다.
파티가 바뀌면 다시 생성: python -m champions ui --party my.txt
"""
import json
from pathlib import Path

from .data import ROOT
from .matrix import compute
from .engine import usable
from .meta import modal_build, mega_prob, opponents, stones_of
from .sets import arch_of

TEMPLATE = Path(__file__).with_name("ui_template.html")


def build_payload(D, mine, log=print):
    from .textio import NATURE_KO, fmt_sp
    dex = json.loads((D.dir / "dex.json").read_text(encoding="utf-8"))
    tcol = {k: v.get("color", "#888") for k, v in dex["types"].items()}
    tname = {k: v.get("name", k) for k, v in dex["types"].items()}
    # 상대 후보: 조우 가중치가 있는 개체의 기본 키 + op.gg 통계가 있는 전 종
    weight = {}
    for e, b, w in opponents(D):
        weight[b.key] = weight.get(b.key, 0.0) + w
    keys = list(dict.fromkeys(list(weight) + [r["key"] for r in D.TIER if r["key"] in D.DEX]))   # 싱글 순위 전 종
    rows, skipped = [], []
    for k in keys:
        b = modal_build(D, k, False)
        if b is None or not usable(b):
            skipped.append(k)
            continue
        mb = modal_build(D, k, True) if stones_of(D, k) else None
        rows.append({"k": k, "b": b, "mb": mb})
    log(f"[ui] 상대 후보 {len(rows)}종 (메가형 {sum(1 for r in rows if r['mb'])}) × 내 파티 {len(mine)} 상성 계산…"
        + (f"  (모델로 싸울 수 없어 제외: {', '.join(D.name(k) for k in skipped)})" if skipped else ""))
    opp_builds = [r["b"] for r in rows] + [r["mb"] for r in rows if r["mb"]]
    V = compute(mine, opp_builds, mirror_zero=False)    # (6, 기본 N + 메가 M), 실전 신호 혼합 포함, 동족전도 실제 값
    n = len(rows)
    mi = n
    opps = []
    for j, r in enumerate(rows):
        k, b = r["k"], r["b"]
        o = {"k": k, "n": D.name(k).split(" (")[0], "full": D.name(k), "t": D.DEX[k]["types"],
             "w": round(weight.get(k, 0.0) * 100, 3), "r": D.RANK.get(k), "v": [round(V[i][j], 3) for i in range(len(mine))],
             "set": f"{D.item_name(b.item)} · " + " / ".join(D.move_name(m) for m in b.moves)}
        if r["mb"]:
            o["pm"] = round(min(1.0, mega_prob(D, k)), 3)
            o["mn"] = D.name(r["mb"].form)
            o["mt"] = r["mb"].types
            o["mv"] = [round(V[i][mi], 3) for i in range(len(mine))]
            mi += 1
        opps.append(o)
    opps.sort(key=lambda o: (-o["w"], o["r"] or 999))
    me = [{"n": D.name(b.form), "k": b.key, "t": b.types, "a": arch_of(b), "item": D.item_name(b.item),
           "nat": NATURE_KO.get(b.nature, b.nature), "sp": fmt_sp(b.sp), "mv": [D.move_name(m) for m in b.moves]}
          for b in mine]
    return {"me": me, "opps": opps, "types": {"c": tcol, "n": tname},
            "meta": {"date": D.dir.name, "season": D.SEASON.upper(), "teams": len(D.TEAMS)}}


def write(D, mine, out=None, log=print):
    payload = build_payload(D, mine, log)
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    out = Path(out) if out else ROOT / "out" / "pick_board.html"
    out.write_text(html, encoding="utf-8")
    return out
