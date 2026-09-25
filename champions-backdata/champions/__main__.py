"""python -m champions <명령>

  scrape   op.gg 수집 (싱글 순위 전 종)          --max-mons N --delay 1.0
  prep     풀 세트 최적화 + 상성 행렬 (캐시)   --pool N (기본: 전 종)
  team     최적 파티 6마리 + 아이템·기술       --pool N --must 한카리아스,누리레느 --exclude 메타몽
  moves    내 파티 기술 배치(+도구·성격)       --party party.txt | --names 한카리아스,누리레느,...
  pick     상대 6마리 보고 선출 3 + 선봉       --party party.txt --opp 보만다,한카리아스,...
  switch   배틀 중 상대 필드 포켓몬에 낼 교체   --party party.txt --hp 100,80,0,... --opp 보만다 --opp-hp 70
  ui       실전 선출 보드(HTML) 생성 — 상대 6마리를 탭하면 ①선봉 ②③ 순서   --party my.txt
  check    모델 점검(실전 승패 신호와 상관)
  audit    외부 심판 점검: 1:1 매치업을 gpt-6-astra 에 블라인드로 묻고 시뮬과 비교   --pairs 30 --dry
  review   기본 로직 검토: 결정 계층 소스를 gpt-6-astra 에 보내 설계 결함·개선안(압축)   --effort medium --dry

결과는 화면과 out/ 폴더(마크다운)에 같이 남는다.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime

from .data import ROOT, load


def _out(name, text):
    d = ROOT / "out"
    d.mkdir(exist_ok=True)
    f = d / f"{name}_{datetime.now():%Y%m%d_%H%M}.md"
    f.write_text(text, encoding="utf-8")
    return f


def _log(*a):
    print(*a, flush=True)


# ── scrape ──────────────────────────────────────────────────────
def cmd_scrape(a):
    from . import scrape
    scrape.run(a.max_mons, a.team_pages, a.delay, log=_log)


# ── prep / team ─────────────────────────────────────────────────
def _prepare(D, a, extra=()):
    from .pipeline import pool_keys, optimize_pool, make_cards, opponent_space, card_matrix
    keys = pool_keys(D, a.pool, getattr(a, "max_rank", 200) or None)   # --must 로 준 포켓몬은 순위와 관계없이 extra 로 들어간다
    ex = {D.mon(x) for x in (a.exclude.split(",") if getattr(a, "exclude", None) else [])}
    keys = [k for k in dict.fromkeys(keys + list(extra)) if k not in ex]
    sets = optimize_pool(D, keys, a.workers, log=_log)
    cards = make_cards(D, sets)
    opps, ids, teams = opponent_space(D)
    V = card_matrix(D, cards, opps, a.workers, log=_log)
    return sets, cards, opps, ids, teams, V


def cmd_prep(a):
    D = load()
    _prepare(D, a)
    _log("준비 완료.")


def cmd_team(a):
    import numpy as np
    from .engine import Build
    from .team import TeamSearch
    from .textio import fmt_build, party_line, table
    D = load()
    must = [D.mon(x) for x in a.must.split(",")] if a.must else []
    must = [D.base_of(k) for k in must]
    sets, cards, opps, ids, teams, V = _prepare(D, a, must)
    ow = np.array([w for _, _, w in opps])
    ts = TeamSearch(cards, V, ids, teams, ow)
    must_idx = []
    for k in must:
        c = max((i for i, c in enumerate(cards) if c["key"] == k), key=lambda i: cards[i]["score"])
        must_idx.append(c)
    _log(f"[team] 카드 {len(cards)}장 · 상대 개체 {len(ids)} · 레플리카 싱글 팀 {len(teams)}개로 탐색")
    res = ts.search(must_idx, restarts=a.restarts, log=_log)
    # 재시작 결과 상위 3개 각각의 이웃(한 장 바꾼 팀)까지 후보로 — 한 재시작 결과에만 기대지 않는다
    neigh = []
    for t, _ in res[:3]:
        neigh += ts.neighbors(list(t), k=8)
    # 탐색은 빠른 근사(순수전략 하한·상한 평균)로, 최종 후보는 혼합전략 균형값(정확)으로 다시 줄 세운다
    pool = sorted(set([(t, v) for t, v in res] + neigh), key=lambda x: -x[1])
    cand = list(dict.fromkeys(t for t, _ in pool))[:24]
    _log(f"[team] 후보 {len(cand)}팀을 혼합전략 균형값으로 재정렬…")
    cand = sorted(cand, key=lambda t: -ts.exact_score(t))[:10]
    p1, se = ts.bootstrap(cand)
    rows = sorted(zip(cand, [ts.exact_score(t) for t in cand], p1, se), key=lambda x: -x[1])
    # 동률 집단(1위와의 대응 차이가 2 표준오차 안) 안에서 무답 노출이 가장 작은 팀을 추천.
    # 후보들은 멤버 대부분을 공유하므로 각자의 SE 가 아니라 같은 상대 표본에서의 차이로 판정해야 한다.
    top_t = rows[0][0]
    tie = [r for r in rows if r[0] == top_t or ts.paired_z(top_t, r[0]) < 2.0]
    # 기본은 값이 가장 높은 팀. 동률 집단 안에 무답 노출이 그보다 1%p 이상 작은 팀이 있으면 그중 값이 가장 높은 팀.
    # (예전 round() 규칙은 0.7%p 차이를 1%p 로 올려 1위 확률 61% 팀 대신 2% 팀을 골랐다)
    top_r = max(tie, key=lambda r: r[1])
    safer = [r for r in tie if ts.gap(list(r[0])) <= ts.gap(list(top_r[0])) - 0.01]
    pick = max(safer, key=lambda r: r[1]) if safer else top_r
    L = []
    L.append(f"# 추천 파티 — 싱글 {D.SEASON.upper()} (op.gg 수집 {D.dir.name})\n")
    L.append(f"풀: 싱글 {a.max_rank or '전'}위 이내{'' if a.pool is None else f' 중 상위 {a.pool}종'} ({len(sets)}종 — 그보다 낮은 순위는 거의 안 쓰여 추천에서 제외, 상대로는 계산) ·상대 표본: 레플리카 싱글 팀 {len(teams)}개 · 카드 {len(cards)}장\n")
    L.append("## 이 파티를 쓰세요\n")
    L.append(f"팀 값 **{pick[1]:+.4f}** (±{pick[3]:.4f}) · 부트스트랩 1위 확률 {pick[2] * 100:.0f}% · 무답 노출 {ts.gap(list(pick[0])) * 100:.1f}%\n")
    L.append("```")
    for i in pick[0]:
        L.append(party_line(D, Build(D, **cards[i]["spec"])))
    L.append("```\n")
    L.append("```")
    nrep = {}
    for t in D.TEAMS:
        for k in {D.base_of(s["pokemon"]) for s in t["slots"] if s["pokemon"] in D.DEX}:
            nrep[k] = nrep.get(k, 0) + 1
    for i in pick[0]:
        c = cards[i]
        b = Build(D, **c["spec"])
        L.append(f"{fmt_build(D, b, True)}   (메타 상대 점수 {c['score']:+.3f} · 싱글 {D.RANK.get(c['key'], '-')}위 · 레플리카 {nrep.get(c['key'], 0)}팀)")
    L.append("```\n")
    thin = [c for c in (cards[i] for i in pick[0]) if (D.RANK.get(c["key"]) or 999) > 60 or nrep.get(c["key"], 0) < 5]
    if thin:
        L.append("⚠ 표본이 얇은 멤버: " + ", ".join(f"{D.name(c['key'])}(싱글 {D.RANK.get(c['key'], '-')}위, 레플리카 {nrep.get(c['key'], 0)}팀)" for c in thin)
                 + " — 상대 세트·승패 신호가 적어 값의 불확실성이 큽니다. 아래 후보 표의 대안과 같이 보세요.\n")
    L.append("## 통계적으로 구분되지 않는 후보들\n")
    hdr = ["팀 값", "±SE", "1위 확률", "무답 노출", "구성"]
    tr = []
    for t, v, p, s in rows:
        tr.append([f"{v:+.4f}", f"{s:.4f}", f"{p * 100:.0f}%", f"{ts.gap(list(t)) * 100:.1f}%",
                   " / ".join(D.name(Build(D, **cards[i]["spec"]).form) + ("" if cards[i]["mega"] else f"@{D.item_name(cards[i]['item'])}") for i in t)])
    L.append(table(tr, hdr))
    # 파티의 약점
    sub = V[list(pick[0])]
    worst = np.argsort(sub.max(axis=0))[:8]
    L.append("\n## 이 파티가 가장 버거운 상대 (내 최선의 답 기준)\n")
    wr = []
    for j in worst:
        bi = int(sub[:, j].argmax())
        wr.append([ids[j].replace("@mega", " (메가)"), f"{ow[j] * 100:.2f}%", f"{sub[bi, j]:+.2f}", D.name(cards[pick[0][bi]]["key"])])
    wr = [[D.name(r[0].split(" ")[0]) + (" (메가)" if "메가" in r[0] else "")] + r[1:] for r in wr]
    L.append(table(wr, ["상대", "조우 비중", "최선 값", "최선의 답"]))
    L.append("\n값: 1:1 끝장 시뮬레이션(정면 60% + 교체 등장 40%)을 op.gg 실전 승패 순위와 8:2 로 섞은 상성으로 만든 "
             "3/6 선출 게임(20×20)의 혼합전략 균형값을 상대 팀 표본에 대해 평균. 승률 예측이 아니다.")
    text = "\n".join(L)
    print(text)
    f = _out("team", text)
    pf = ROOT / "out" / "recommended_party.txt"
    pf.write_text("\n".join(party_line(D, Build(D, **cards[i]["spec"])) for i in pick[0]) + "\n", encoding="utf-8")
    _log(f"\n저장: {f}\n파티 파일: {pf}  (moves / pick / switch 에 --party 로 넣을 수 있음)")


# ── moves ───────────────────────────────────────────────────────
def _read_party(D, a):
    from .textio import parse_party
    if getattr(a, "party", None):
        txt = open(a.party, encoding="utf-8-sig").read()
    elif getattr(a, "names", None):
        txt = a.names
    else:
        raise SystemExit("--party 파일 또는 --names 이름목록이 필요합니다.")
    p = parse_party(D, txt)
    if not p:
        raise SystemExit("파티가 비어 있습니다.")
    return p


def cmd_moves(a):
    from .engine import Build
    from .meta import stones_of, opponents
    from .pipeline import party_worker
    from .sets import Evaluator
    from .textio import fmt_build, party_line, table
    D = load()
    party = _read_party(D, a)
    jobs = []
    for m in party:
        kw = {"free": a.free}
        if m["item"]:
            kw["item"] = m["item"]
            kw["fix_item"] = True
            kw["mega"] = m["item"] in D.STONE
        elif not stones_of(D, m["key"]):
            kw["mega"] = False
        if m["nature"] and m["sp"]:
            kw["nature"], kw["sp"] = m["nature"], m["sp"]
        if m["ability"]:
            kw["ability"] = m["ability"]
        if m.get("arch"):
            kw["arch"] = m["arch"]
        if a.keep and m["moves"]:
            kw["fixed_moves"] = m["moves"]
        if kw.get("mega") is None:          # 메가 가능 + 도구 미지정 → 둘 다 계산해서 팀 단위로 고른다
            jobs.append((m["key"], dict(kw, mega=True)))
            jobs.append((m["key"], dict(kw, mega=False)))
        else:
            jobs.append((m["key"], kw))
    _log(f"[moves] {len(party)}마리 · 세트 탐색 {len(jobs)}건 (병렬)…")
    res = {}
    with ProcessPoolExecutor(min(len(jobs), a.workers or max(1, (os.cpu_count() or 2) - 1))) as ex:
        for key, mega, r in ex.map(party_worker, jobs):
            res.setdefault(key, {})["mega" if mega else "base"] = r
    # 메가는 한 마리만: 메가형 이득이 가장 큰 한 마리
    choice = {}
    for m in party:
        r = res[m["key"]]
        choice[m["key"]] = "mega" if (m["item"] in D.STONE) else "base"
    free_mega = [m["key"] for m in party if not m["item"] and "mega" in res[m["key"]] and "base" in res[m["key"]]]
    fixed_mega = [m["key"] for m in party if m["item"] in D.STONE]
    if not fixed_mega and free_mega:
        gain = {k: res[k]["mega"]["score"] - res[k]["base"]["score"] for k in free_mega}
        k = max(gain, key=gain.get)
        if gain[k] > 0:
            choice[k] = "mega"
    # 도구 중복 해소: 겹치면 손해가 작은 쪽이 다음 도구로
    user_item = {m["key"]: m["item"] for m in party if m["item"]}
    item_of = {m["key"]: res[m["key"]][choice[m["key"]]]["spec"]["item"] for m in party}
    ev = None
    for _ in range(12):
        used = {}
        for k, it in item_of.items():
            used.setdefault(it, []).append(k)
        dup = [(it, ks) for it, ks in used.items() if it and len(ks) > 1]
        if not dup:
            break
        it, ks = dup[0]
        movable = [k for k in ks if k not in user_item and choice[k] == "base"]
        if not movable:
            break
        best = None
        for k in movable:
            taken = set(item_of.values())
            alts = [(x, v) for x, v in res[k]["base"]["items"] if x not in taken]
            if alts:
                loss = dict(res[k]["base"]["items"]).get(it, 0) - alts[0][1]
                if best is None or loss < best[0]:
                    best = (loss, k, alts[0][0])
        if not best:
            break
        _, k, new = best
        ev = ev or Evaluator(opponents(D))
        from .sets import optimize
        from .pipeline import _res_json
        _log(f"  도구 중복({D.item_name(it)}) → {D.name(k)} 를 {D.item_name(new)} 로 다시 탐색")
        kw = dict([j for j in jobs if j[0] == k][0][1])
        kw.update(item=new, fix_item=True, mega=False)
        res[k]["base"] = _res_json(optimize(D, k, ev, **kw))
        item_of[k] = new
    L = [f"# 기술 배치 추천 — 싱글 {D.SEASON.upper()} (op.gg 수집 {D.dir.name})\n"]
    L.append("점수 = 메타 상대(조우 가중 상위 80개체)와의 1:1 평균 값. 채용 70% 이상 기술은 고정(--free 로 해제).\n")
    L.append("## 추천 파티 (그대로 붙여 넣어 쓸 수 있음)\n```")
    final = []
    for m in party:
        r = res[m["key"]][choice[m["key"]]]
        b = Build(D, **r["spec"])
        final.append((m, r, b))
        L.append(party_line(D, b))
    L.append("```\n")
    for m, r, b in final:
        L.append(f"## {D.name(b.form)}\n")
        L.append(f"`{fmt_build(D, b, True)}`\n")
        cur = ""
        if m["moves"]:
            cb = Build(D, m["key"], m["moves"], b.item, b.entry_ability, m["nature"] or b.nature, m["sp"] or b.sp)
            ev = ev or Evaluator(opponents(D))
            cur = f" · 입력한 세트 {ev.score(cb, True):+.3f}"
        rs = f"{r['real_score']:+.3f}" if r["real_score"] is not None else "-"
        L.append(f"점수 **{r['score']:+.3f}** · op.gg 채용 상위 4기 세트 {rs}{cur}\n")
        if r.get("arch_scores"):
            from .sets import type_label
            L.append("유형별 최고 점수: " + " · ".join(f"{type_label(a)} {v:+.3f}" + (" ← 추천" if a == r.get("arch") else "")
                                               for a, v in sorted(r["arch_scores"].items(), key=lambda x: -x[1])) + "\n")
        rows = []
        for c in r["moves"]:
            st = "고정" if c["fixed"] else ("바꿈" if c["pct"] < 3 else "선택")
            rows.append([D.move_name(c["move"]), f"{c['pct']:.0f}%", st,
                         "-" if c["drop"] is None else f"{c['drop']:+.3f}", D.move_name(c["alt"]) if c["alt"] else "-"])
        L.append(table(rows, ["기술", "채용", "구분", "빼면 점수 하락", "최선의 대체"]))
        if r["items"]:
            L.append("\n도구 후보: " + ", ".join(f"{D.item_name(i)} {v:+.3f}" for i, v in r["items"][:4]))
        L.append("\nop.gg 최다 4기: " + ", ".join(D.move_name(x) for x in r["real_top4"]) + "\n")
    text = "\n".join(L)
    print(text)
    _log(f"저장: {_out('moves', text)}")


# ── pick / switch ───────────────────────────────────────────────
def _party_builds(D, party):
    """부족한 정보는 최적 세트 캐시 → 없으면 op.gg 대표 세트로 채운다."""
    from .engine import Build
    from .meta import modal_build
    from .pipeline import best_set
    out = []
    for m in party:
        mega = (m["item"] in D.STONE) if m["item"] else False
        base = best_set(D, m["key"], mega)
        spec = dict(base["spec"]) if base else modal_build(D, m["key"], mega).spec()
        if m["item"]:
            spec["item"] = m["item"]
        for f in ("nature", "sp", "moves", "ability"):
            if m[f]:
                spec[f] = m[f]
        out.append(Build(D, **spec))
    return out


def cmd_pick(a):
    from .textio import fmt_build, table
    from .pick import advise
    D = load()
    mine = _party_builds(D, _read_party(D, a))
    from .meta import stones_of
    raw = [D.mon(x) for x in a.opp.split(",")]
    opp_keys = [D.base_of(k) for k in raw]
    # 메가 이름으로 적었거나 --opp-mega 로 준 상대는 메가 확정
    mk = {D.base_of(k): D.DEX[k]["item"] for k in raw if D.DEX[k]["base_key"]}
    for x in (a.opp_mega.split(",") if a.opp_mega else []):
        k = D.mon(x)
        mk[D.base_of(k)] = D.DEX[k]["item"] if D.DEX[k]["base_key"] else (stones_of(D, k) or [None])[0]
    r = advise(D, mine, opp_keys, mk or None, a.mc)
    V = r["V"]
    L = [f"# 선출 추천\n", "내 파티:"]
    L += [f"  {i + 1}. {fmt_build(D, b)}" for i, b in enumerate(mine)]
    L.append("\n상대: " + ", ".join(D.name(k) for k in opp_keys) + "\n")
    nm = lambda t, side: "/".join(D.name(mine[i].form) if side == 0 else D.name(opp_keys[i]) for i in t)
    L.append(f"## 내보낼 3마리: **{nm(r['best'], 0)}**  (게임 값 {r['best_value']:+.3f} · 순수 보장값 {r['safe_value']:+.3f})")
    L.append(f"## 선봉: **{D.name(mine[r['lead']].form)}**\n")
    if len(r["mix"]) > 1:
        L.append("선출 혼합(균형에서 각 조합을 낼 비율 — 한 조합만 고집하면 읽힌다): "
                 + " · ".join(f"{nm(t, 0)} (선봉 {D.name(mine[ld].form)}) {p * 100:.0f}%" for t, p, ld in r["mix"]))
    L.append("상대 선출 예상(균형): " + " · ".join(f"{nm(t, 1)} {p * 100:.0f}%" for t, p in r["their_mix"]))
    L.append("보장값 기준 차선: " + " · ".join(f"{nm(t, 0)} ({v:+.3f})" for t, v in r["alts"]) + "\n")
    hdr = ["상대 ↓ / 나 →"] + [D.name(b.form) for b in mine] + ["최선의 답"]
    rows = []
    for j, k in enumerate(opp_keys):
        best = int(V[:, j].argmax())
        rows.append([D.name(k) + (f" (메가 {sum(w for b, w in r['opp'][j][1] if b.mega) * 100:.0f}%)" if any(b.mega for b, _ in r["opp"][j][1]) else "")]
                    + [f"{V[i, j]:+.2f}" for i in range(len(mine))] + [D.name(mine[best].form)])
    L.append(table(rows, hdr))
    risky = [opp_keys[j] for j in range(len(opp_keys)) if (V[list(r["best"]), j] >= 0).sum() < 1]
    if risky:
        L.append("\n⚠ 고른 3마리로 답이 없는 상대: " + ", ".join(D.name(k) for k in risky))
    L.append("\n값 +1 = 만피로 이김, 0 = 비등, −1 = 못 건드리고 짐 (1:1 끝장 시뮬레이션 + 실전 승패 신호)")
    text = "\n".join(L)
    print(text)
    _log(f"저장: {_out('pick', text)}")


def cmd_switch(a):
    from .meta import modal_build
    from .pick import switch
    from .textio import table
    D = load()
    mine = _party_builds(D, _read_party(D, a))
    hp = [float(x) / 100 for x in a.hp.split(",")] if a.hp else [1.0] * len(mine)
    hp += [1.0] * (len(mine) - len(hp))
    raw = D.mon(a.opp)
    ok = D.base_of(raw)
    mega = a.opp_is_mega or (D.DEX[raw]["base_key"] is not None)
    ob = modal_build(D, ok, mega, stone=D.DEX[raw]["item"] if D.DEX[raw]["base_key"] else None)
    active = None
    if a.active:
        ak = D.base_of(D.mon(a.active))
        active = next((i for i, b in enumerate(mine) if b.key == ak), None)
    rows = switch(D, list(zip(mine, hp)), ob, a.opp_hp / 100, active, a.mc)
    L = [f"# 교체 추천 — 상대 {D.name(ob.form)} (HP {a.opp_hp:.0f}%)\n", f"상대 추정 세트: {ob}\n"]
    L.append(table([[D.name(mine[i].form), f"{hp[i] * 100:.0f}%", "그대로 싸움" if st else "교체해서 들어감", f"{v:+.2f}", f"{p * 100:.0f}%"]
                    for i, v, st, p in rows],
                   ["내 포켓몬", "HP", "방식", "값", "1:1 승률"]))
    L.append(f"\n교체로 들어가는 쪽은 상대 최선의 기술을 한 번 먼저 맞는 것으로 계산. "
             f"승률 = 명중·난수·급소·마비를 {a.mc}판 굴린 결과(서로 최선의 계획 기준).")
    text = "\n".join(L)
    print(text)
    _log(f"저장: {_out('switch', text)}")


# ── ui (실전 선출 보드) ─────────────────────────────────────────
def cmd_ui(a):
    from . import ui
    D = load()
    if not getattr(a, "party", None) and not getattr(a, "names", None):
        a.party = str(ROOT / "out" / "recommended_party.txt")
        if not os.path.exists(a.party):
            raise SystemExit("--party 파일이 필요합니다(또는 먼저 team 을 실행해 out/recommended_party.txt 를 만드세요).")
        _log(f"[ui] 파티: {a.party}")
    mine = _party_builds(D, _read_party(D, a))
    f = ui.write(D, mine, a.out, log=_log)
    _log(f"저장: {f}\n브라우저로 열면 됩니다(인터넷 없이도 동작, 글꼴만 온라인일 때 적용).")


# ── check ───────────────────────────────────────────────────────
def cmd_check(a):
    from .matrix import sim_vs_empirical
    from .meta import opponents
    from .textio import fmt_build
    D = load()
    opps = opponents(D)
    L = [f"# 모델 점검 — 수집 {D.dir.name}, 시즌 {D.SEASON}\n",
         f"op.gg 포켓몬 통계 {len(D.USAGE)}종 · 레플리카 싱글 팀 {len(D.TEAMS)}개 · 상대 개체 {len(opps)}\n",
         "## 조우 가중 상위 20 (대표 세트)\n```"]
    for e, b, w in opps[:20]:
        L.append(f"{w * 100:5.2f}%  {fmt_build(D, b)}")
    L.append("```\n")
    seen, bs = set(), []
    for e, b, w in opps:
        if b.key not in seen:
            seen.add(b.key)
            bs.append(b)
    r, n = sim_vs_empirical(D, bs[:a.n])
    L.append(f"## 시뮬레이션 ↔ op.gg 실전 승패 신호\n\n상위 {a.n}종 {n}쌍 스피어만 ρ = **{r:+.3f}**  (0 이면 무관, 1 이면 순위 완전 일치)")
    text = "\n".join(L)
    print(text)
    _log(f"저장: {_out('check', text)}")


def cmd_audit(a):
    from . import audit
    from .meta import opponents
    D = load()
    seen, bs = set(), []
    for e, b, w in opponents(D):
        if b.key not in seen:
            seen.add(b.key)
            bs.append(b)
    rows = audit.run(D, bs[:a.n], a.pairs, a.model, a.effort, a.seed, a.concurrency, a.dry, log=_log)
    if a.dry:
        return
    text = audit.report(D, rows, a.model)
    if not a.no_review:
        rv = audit.review(D, rows, a.model, a.review_effort)
        text = (f"# 종합 판정 ({a.model}): 적정성 **{rv['adequate']}**\n\n{rv['verdict']}\n\n개선안:\n"
                + "\n".join(f"{i}. {x}" for i, x in enumerate(rv["improvements"], 1)) + "\n\n---\n\n" + text)
    print(text)
    _log(f"저장: {_out('audit', text)}")


def cmd_review(a):
    from . import review
    if a.dry:
        s = review.source()
        _log(f"[review] --dry: 보낼 소스 {len(s):,}자\n")
        _log(review.INSTRUCTIONS)
        return
    _log(f"[review] 결정 계층 소스를 {a.model} 에 전송 (effort={a.effort})…")
    r, n = review.run(a.model, a.effort, a.metrics)
    text = review.fmt(r, a.model)
    print(text)
    f = _out("review", text)
    review.save(r, f.with_suffix(".json"))
    _log(f"\n보낸 소스 {n:,}자 · 저장: {f}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m champions", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape")
    s.add_argument("--max-mons", type=int, default=None, help="기본: 싱글 순위 전 종")
    s.add_argument("--team-pages", type=int, default=None)
    s.add_argument("--delay", type=float, default=1.0)
    for name in ("prep", "team"):
        s = sub.add_parser(name)
        s.add_argument("--pool", type=int, default=None, help="후보 풀 크기(싱글 순위 상위 N). 기본: --max-rank 이내 전부")
        s.add_argument("--max-rank", type=int, default=200, help="이 순위보다 낮은 포켓몬은 추천하지 않음(기본 200, 0 = 제한 없음)")
        s.add_argument("--exclude", default=None)
        s.add_argument("--workers", type=int, default=None)
        if name == "team":
            s.add_argument("--must", default=None)
            s.add_argument("--restarts", type=int, default=4)
    s = sub.add_parser("moves")
    s.add_argument("--party")
    s.add_argument("--names")
    s.add_argument("--free", action="store_true", help="채용 70%% 이상 기술도 바꿀 수 있게")
    s.add_argument("--keep", action="store_true", help="입력한 기술은 고정하고 빈 칸만 채움")
    s.add_argument("--workers", type=int, default=None)
    s = sub.add_parser("pick")
    s.add_argument("--party")
    s.add_argument("--names")
    s.add_argument("--opp", required=True)
    s.add_argument("--opp-mega", default=None, help="메가인 걸 아는 상대(쉼표)")
    s.add_argument("--mc", type=int, default=0, help="확률 모드 판수(명중·난수·급소·마비). 0 = 기대값, 느려짐")
    s = sub.add_parser("switch")
    s.add_argument("--party")
    s.add_argument("--names")
    s.add_argument("--hp", default=None, help="내 파티 순서대로 남은 HP%% (0 = 기절)")
    s.add_argument("--active", default=None, help="지금 필드에 있는 내 포켓몬")
    s.add_argument("--opp", required=True)
    s.add_argument("--opp-hp", type=float, default=100)
    s.add_argument("--opp-is-mega", action="store_true")
    s.add_argument("--mc", type=int, default=64, help="확률 모드 판수 (승률 계산)")
    s = sub.add_parser("ui")
    s.add_argument("--party", help="기본: out/recommended_party.txt")
    s.add_argument("--names")
    s.add_argument("--out", default=None, help="기본: out/pick_board.html")
    s = sub.add_parser("check")
    s.add_argument("--n", type=int, default=50)
    s = sub.add_parser("review")
    s.add_argument("--model", default="gpt-6-astra")
    s.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    s.add_argument("--metrics", default="", help="현재 검증 수치(한 줄) — 검토에 참고로 전달")
    s.add_argument("--dry", action="store_true", help="API 호출 없이 보낼 분량만 출력")
    s = sub.add_parser("audit")
    s.add_argument("--n", type=int, default=50, help="조우 상위 몇 종에서 쌍을 뽑을지")
    s.add_argument("--pairs", type=int, default=30, help="API 에 물을 매치업 수")
    s.add_argument("--model", default="gpt-6-astra")
    s.add_argument("--effort", default="low", choices=["low", "medium", "high"], help="매치업 판정 추론 강도")
    s.add_argument("--review-effort", default="medium", choices=["low", "medium", "high"], help="종합 판정 추론 강도")
    s.add_argument("--no-review", action="store_true", help="종합 판정(적정성·개선안) 요청 생략")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--concurrency", type=int, default=4)
    s.add_argument("--dry", action="store_true", help="API 호출 없이 질문 예시만 출력")
    a = ap.parse_args()
    try:
        {"scrape": cmd_scrape, "prep": cmd_prep, "team": cmd_team, "moves": cmd_moves, "pick": cmd_pick,
         "switch": cmd_switch, "check": cmd_check, "audit": cmd_audit, "review": cmd_review, "ui": cmd_ui}[a.cmd](a)
    except KeyError as e:
        if "찾을 수 없음" in str(e):
            raise SystemExit("입력 오류: " + str(e).strip("'\""))
        raise


if __name__ == "__main__":
    main()
