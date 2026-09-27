"""외부 심판 점검: 1:1 매치업을 OpenAI(gpt-6-astra)에 블라인드로 물어 시뮬레이션과 비교한다.

심판은 시뮬 결과를 보지 않고 스스로 승자·값을 예측한다(편향 방지). 비교 대상은 duel(A,B)
= 만피 정면 1:1 (교체 없음) 이라 심판에게 준 조건과 같다.
응답은 out/audit_cache.jsonl 에 프롬프트 해시로 저장해서 다시 돌려도 같은 질문은 재과금하지 않는다.
API 키: 환경변수 OPENAI_API_KEY → 없으면 secret.env (프로젝트 루트, legacy_v5/) 의 OPENAI_API_KEY.
"""
import hashlib
import json
import os
import random
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .data import ROOT

API = "https://api.openai.com/v1/responses"
CACHE = ROOT / "out" / "audit_cache.jsonl"

INSTRUCTIONS = """You are an expert Pokémon singles battle analyst auditing a battle simulator for Pokémon Champions (level 50, stats already computed and given to you — do not recompute them).

Setting: two Pokémon, both at full HP, fight 1v1 until one faints. No switching, no teammates, no Tera. Both sides play optimally for this 1v1 (they may use setup/status moves if that wins). Mega forms are already mega-evolved at the start. Assume average damage rolls and no critical hits; treat accuracy as expected value.

Predict the outcome from A's perspective on this scale:
  value = +(0.5 + 0.5 * A's remaining HP fraction) if A wins,
          -(0.5 + 0.5 * B's remaining HP fraction) if B wins,
          0 if it's a coin flip / double KO.
So +1 = A wins untouched, +0.5 = A barely wins, -1 = B wins untouched.

Reason about speed order, priority, damage per hit (roughly how many hits to KO each way), abilities and items.
Output must be terse: "reasoning" = ONE short Korean sentence; "key_factors" = at most 3 items of a few words each."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reasoning": {"type": "string"},
        "a_hits_to_ko": {"type": "number", "description": "A 의 최선 기술로 B 를 쓰러뜨리는 데 필요한 타수 (못 쓰러뜨리면 99)"},
        "b_hits_to_ko": {"type": "number"},
        "faster": {"type": "string", "enum": ["A", "B", "tie"]},
        "winner": {"type": "string", "enum": ["A", "B", "draw"]},
        "value": {"type": "number"},
        "confidence": {"type": "number", "description": "0~1"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reasoning", "a_hits_to_ko", "b_hits_to_ko", "faster", "winner", "value", "confidence", "key_factors"],
}


def api_key():
    k = os.environ.get("OPENAI_API_KEY")
    if k:
        return k
    for f in (ROOT / "secret.env", ROOT / "legacy_v5" / "secret.env"):
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    n, v = line.split("=", 1)
                    if n.strip() == "OPENAI_API_KEY":
                        return v.strip().strip("'\"")
    raise SystemExit("OPENAI_API_KEY 가 없습니다. 환경변수로 주거나 secret.env 에 OPENAI_API_KEY=sk-... 를 넣으세요.")


def describe(D, b, tag):
    st = "/".join(str(x) for x in b.stats)
    L = [f"{tag}: {D.name(b.form)} [{b.form}]  types={'/'.join(b.types)}",
         f"  ability={b.ability}  item={b.item or 'none'}  nature={b.nature}",
         f"  stats (HP/Atk/Def/SpA/SpD/Spe) = {st}"]
    if b.blade:
        L.append(f"  (Stance Change: Blade forme stats = {'/'.join(str(x) for x in b.blade)})")
    for m in b.moves:
        mv = D.MOVES[m]
        acc = mv["acc"] if mv["acc"] else "-"
        pri = f" priority={mv['priority']:+d}" if mv["priority"] else ""
        L.append(f"  - {m} ({mv['name']}): {mv['type']} {mv['cat']} power={mv['power'] or '-'} acc={acc}{pri}")
    return "\n".join(L)


def prompt(D, A, B):
    return describe(D, A, "A") + "\n\n" + describe(D, B, "B")


def _load_cache():
    c = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                c[r["hash"]] = r["answer"]
    return c


def ask(key, model, effort, text, timeout=300, instructions=INSTRUCTIONS, schema=SCHEMA, name="duel_verdict"):
    body = {
        "model": model,
        "instructions": instructions,
        "input": text,
        "reasoning": {"effort": effort},
        "text": {"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}, "verbosity": "low"},
        "store": False,
    }
    req = urllib.request.Request(API, json.dumps(body).encode(), {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:500]}") from None
    for item in resp.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    return json.loads(c["text"])
                if c.get("type") == "refusal":
                    raise RuntimeError("거부: " + c.get("refusal", ""))
    raise RuntimeError(f"응답에 텍스트가 없음: status={resp.get('status')} {resp.get('incomplete_details')}")


def sample_pairs(builds, k, seed):
    pairs = [(a, b) for i, a in enumerate(builds) for b in builds[i + 1:] if a.key != b.key]
    rnd = random.Random(seed)
    rnd.shuffle(pairs)
    return pairs[:k]


def run(D, builds, k=30, model="gpt-6-astra", effort="medium", seed=7, concurrency=4, dry=False, log=print):
    """[{A, B, sim, emp, judge}] 반환. judge 는 dict 또는 {'error': ...}."""
    from .engine import duel
    from .matrix import empirical
    pairs = sample_pairs(builds, k, seed)
    if dry:
        log(f"[audit] --dry: 첫 질문 예시 (총 {len(pairs)}건)\n")
        log(INSTRUCTIONS + "\n\n---\n" + prompt(D, *pairs[0]))
        return []
    key = api_key()
    cache = _load_cache()
    CACHE.parent.mkdir(exist_ok=True)
    rows = []
    for A, B in pairs:
        t = prompt(D, A, B)
        h = hashlib.sha256(f"{model}|{effort}|{INSTRUCTIONS}|{t}".encode()).hexdigest()[:16]
        rows.append({"A": A, "B": B, "text": t, "hash": h, "sim": duel(A, B), "emp": empirical(D, A.key, B.key)})
    todo = [r for r in rows if r["hash"] not in cache]
    log(f"[audit] {len(rows)}쌍 · 캐시 {len(rows) - len(todo)} · 새 요청 {len(todo)} ({model}, effort={effort})")

    def one(r):
        try:
            return r, ask(key, model, effort, r["text"]), None
        except Exception as e:  # 한 건 실패로 전체를 버리지 않는다
            return r, None, str(e)

    with ThreadPoolExecutor(max(1, concurrency)) as ex, CACHE.open("a", encoding="utf-8") as f:
        for n, (r, ans, err) in enumerate(ex.map(one, todo), 1):
            if err:
                log(f"  [{n}/{len(todo)}] 실패 {D.name(r['A'].form)} vs {D.name(r['B'].form)}: {err}")
                r["judge"] = {"error": err}
                continue
            cache[r["hash"]] = ans
            f.write(json.dumps({"hash": r["hash"], "a": r["A"].spec(), "b": r["B"].spec(), "answer": ans}, ensure_ascii=False) + "\n")
            f.flush()
            log(f"  [{n}/{len(todo)}] {D.name(r['A'].form)} vs {D.name(r['B'].form)}: 심판 {ans['value']:+.2f} / 시뮬 {r['sim']:+.2f}")
    for r in rows:
        r.setdefault("judge", cache.get(r["hash"]))
    return rows


def spearman(xs, ys):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(o):                       # 동률은 평균 순위
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for t in range(i, j + 1):
                r[o[t]] = (i + j) / 2
            i = j + 1
        return r
    if len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx) ** 0.5
    vy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (vx * vy) if vx and vy else None


ENGINE = """Simulator summary (Pokémon Champions singles, Lv50):
- 1v1 turn sim to faint (max 30 turns), avg damage roll, no crits, accuracy as expected value, paralysis = 0.75x expected action.
- Each side picks a plan: plain attack (best damage/KO move each turn), setup 1-2 turns then attack, or status move then attack; plan-pair matrix → value = mean of maximin & minimax.
- Matchup value = 0.6*head-on + 0.2*(A switches in, eats one hit) − 0.2*(B does). Team matrix blends this 80:20 with op.gg win/lose-list rank signal.
- Team pick = 3-of-6 selection game over these values. Prior op.gg check: Spearman(sim, op.gg signal) = 0.63."""

REVIEW_INSTRUCTIONS = """You audit a Pokémon battle simulator. Given its design and an audit where an LLM judge blind-predicted sampled 1v1 duels, decide if the model is adequate for team-building/lead-selection advice and list the highest-impact fixes.
Be extremely terse (token budget is tight): verdict ≤ 1 Korean sentence; at most 5 improvements, each ≤ 20 Korean words, most impactful first; name the concrete mechanic, not generic advice. Judge may itself be wrong — weigh by confidence and op.gg signal."""

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "adequate": {"type": "string", "enum": ["yes", "partly", "no"]},
        "verdict": {"type": "string"},
        "improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["adequate", "verdict", "improvements"],
}


def review(D, rows, model, effort="medium"):
    """감사 결과를 압축해서 한 번 더 물어 적정성·개선안만 받는다."""
    ok = [r for r in rows if r["judge"] and "error" not in r["judge"]]
    agree = sum(_sign(r["sim"]) == _sign(r["judge"]["value"]) for r in ok)
    rho = spearman([r["sim"] for r in ok], [r["judge"]["value"] for r in ok])
    L = [ENGINE, f"\nAudit: {len(ok)} duels, winner agreement {agree}/{len(ok)}, Spearman(sim, judge) = {rho if rho is None else round(rho, 2)}.",
         "Disagreements (A vs B | sim | judge | conf | op.gg | judge note):"]
    for r in ok:
        j = r["judge"]
        if _sign(r["sim"]) != _sign(j["value"]):
            e = "-" if r["emp"] is None else f"{r['emp']:+.1f}"
            L.append(f"{r['A']!r} vs {r['B']!r} | {r['sim']:+.2f} | {j['value']:+.2f} | {j['confidence']:.1f} | {e} | {'; '.join(j['key_factors'])}")
    return ask(api_key(), model, effort, "\n".join(L), instructions=REVIEW_INSTRUCTIONS, schema=REVIEW_SCHEMA, name="model_review")


def _sign(v, eps=0.05):
    return 0 if abs(v) < eps else (1 if v > 0 else -1)


def report(D, rows, model):
    from .textio import table
    ok = [r for r in rows if r["judge"] and "error" not in r["judge"]]
    L = [f"# 외부 심판 점검 — {model} · 수집 {D.dir.name}\n",
         f"표본 {len(rows)}쌍 · 유효 응답 {len(ok)} · 비교 대상: 시뮬 duel(A,B) (만피 정면 1:1, 교체 없음)\n"]
    if not ok:
        L.append("유효 응답이 없습니다.")
        return "\n".join(L)
    sim = [r["sim"] for r in ok]
    jv = [r["judge"]["value"] for r in ok]
    agree = [r for r in ok if _sign(r["sim"]) == _sign(r["judge"]["value"])]
    rho = spearman(sim, jv)
    mae = sum(abs(a - b) for a, b in zip(sim, jv)) / len(ok)
    L.append("## 요약\n")
    k_, n_ = len(agree), len(ok)
    z = 1.96                                               # Wilson 95% 구간(M2-4): 20쌍이면 구간이 넓다
    c = (k_ + z * z / 2) / (n_ + z * z)
    h = z * ((k_ * (n_ - k_) / n_ + z * z / 4) ** 0.5) / (n_ + z * z)
    L.append(f"- 승패 방향 일치: **{k_}/{n_} ({k_ / n_ * 100:.0f}%)**, Wilson 95% [{max(0, c - h):.2f}, {min(1, c + h):.2f}] "
             f"— 심판은 기준값(ground truth)이 아니며 같은 단순화를 쓰므로 공통 편향은 잡지 못합니다")
    L.append(f"- 값 스피어만 ρ(시뮬, 심판) = **{rho:+.3f}**" if rho is not None else "- ρ 계산 불가")
    L.append(f"- 평균 절대 차이 = {mae:.3f}")
    emp = [r for r in ok if r["emp"] is not None]
    if len(emp) >= 5:
        rs = spearman([r["sim"] for r in emp], [r["emp"] for r in emp])
        rj = spearman([r["judge"]["value"] for r in emp], [r["emp"] for r in emp])
        L.append(f"- op.gg 실전 신호가 있는 {len(emp)}쌍: ρ(시뮬, 실전) = {rs:+.3f} · ρ(심판, 실전) = {rj:+.3f}  ← 심판이 실전과 더 맞으면 시뮬 쪽을 의심")
    L.append("")
    # 불일치: 방향이 다르고 심판 확신이 높은 순
    bad = sorted([r for r in ok if r not in agree], key=lambda r: -(r["judge"]["confidence"] * abs(r["sim"] - r["judge"]["value"])))
    L.append(f"## 방향 불일치 {len(bad)}건 (심판 확신 × 차이 순)\n")
    if bad:
        tr = []
        for r in bad:
            j = r["judge"]
            tr.append([D.name(r["A"].form), D.name(r["B"].form), f"{r['sim']:+.2f}", f"{j['value']:+.2f}", f"{j['confidence']:.2f}",
                       "-" if r["emp"] is None else f"{r['emp']:+.2f}", j["faster"], f"{j['a_hits_to_ko']:g}/{j['b_hits_to_ko']:g}"])
        L.append(table(tr, ["A", "B", "시뮬", "심판", "확신", "실전", "심판:선공", "심판:확정타 A/B"]))
        L.append("")
        for r in bad:
            j = r["judge"]
            L.append(f"### {D.name(r['A'].form)} vs {D.name(r['B'].form)}  (시뮬 {r['sim']:+.2f} · 심판 {j['value']:+.2f})\n")
            L.append("```\n" + r["text"] + "\n```")
            L.append(f"심판: {j['reasoning']}\n")
            L.append("핵심: " + " · ".join(j["key_factors"]) + "\n")
    L.append("## 전체 표\n")
    tr = [[D.name(r["A"].form), D.name(r["B"].form), f"{r['sim']:+.2f}", f"{r['judge']['value']:+.2f}", f"{r['judge']['confidence']:.2f}",
           "✓" if r in agree else "✗"] for r in ok]
    L.append(table(tr, ["A", "B", "시뮬", "심판", "확신", "방향"]))
    L.append("\n심판도 틀릴 수 있다. 불일치 건은 데미지 계산기로 직접 확인한 뒤 엔진을 고칠 것.")
    return "\n".join(L)
