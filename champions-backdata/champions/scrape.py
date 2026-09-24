"""op.gg 포켓몬 챔피언스 스크래퍼.

op.gg 페이지는 Next.js App Router(RSC)라서 데이터가 HTML 안의
`self.__next_f.push([1,"..."])` 청크에 JSON 으로 들어 있다. 브라우저 없이
HTTP GET → 청크 이어붙이기 → 원하는 키를 감싸는 객체를 잘라 json.loads 한다.

수집 대상
  tier            시즌 티어(싱글 순위)
  replica-teams   레플리카 팀(완전한 빌드) + 전체 도감/기술/아이템 사전
  pokedex/<key>   포켓몬별 싱글 배틀 통계(기술·도구·특성·성격·스탯포인트·파트너·승패 상대)

결과는 data/raw/<YYYY-MM-DD>/ 아래 JSON 으로 저장하고, 이미 받은 파일은 다시 받지 않는다.
"""
import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

BASE = "https://op.gg/ko/pokemon-champions"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

_CHUNK = re.compile(r'self\.__next_f\.push\((\[.*?\])\)</script>', re.S)


def fetch(url, delay=1.0, retries=3):
    """페이지 1개를 받아 RSC flight 텍스트를 돌려준다. 호출 사이에 delay 초 쉰다."""
    last = None
    for k in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko"})
            html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8")
            time.sleep(delay)
            parts = []
            for c in _CHUNK.findall(html):
                if c.startswith("[1,"):
                    parts.append(json.loads(c)[1])
            if not parts:
                raise ValueError("RSC 청크 없음 — 페이지 구조가 바뀌었을 수 있음: " + url)
            return "".join(parts)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
            time.sleep(delay * (2 + 3 * k))
    raise RuntimeError(f"받기 실패 {url}: {last}")


def _stack_at(s, pos):
    """pos 직전까지 열린 {/[ 의 시작 위치 스택. pos 가 든 행의 처음부터 문자열을 인식하며 훑는다."""
    start = s.rfind("\n", 0, pos) + 1
    m = re.match(r"[0-9a-f]+:", s[start:start + 12])
    i = start + (m.end() if m else 0)
    stack, ins, esc = [], False, False
    while i < pos:
        c = s[i]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
        elif c == '"':
            ins = True
        elif c in "{[":
            stack.append(i)
        elif c in "}]":
            stack.pop()
        i += 1
    return stack


def _span(s, start):
    depth, ins, esc = 0, False, False
    for e in range(start, len(s)):
        c = s[e]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
            continue
        if c == '"':
            ins = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return s[start:e + 1]
    raise ValueError("닫는 괄호 없음")


def object_with(s, key, nth=0):
    """'"key":' 가 nth 번째로 나오는 곳을 감싸는 객체를 dict 로 돌려준다."""
    pos = -1
    for _ in range(nth + 1):
        pos = s.find('"%s":' % key, pos + 1)
        if pos < 0:
            return None
    return json.loads(_span(s, _stack_at(s, pos)[-1]))


# ── 개별 페이지 파서 ───────────────────────────────────────────────

def scrape_tier(delay):
    s = fetch(f"{BASE}/tier", delay)
    o = object_with(s, "seasons")
    season = o["seasons"][0]
    out = {"season": season["id"], "formats": {}}
    for f in season["formats"]:
        out["formats"][f["id"]] = [
            {"rank": r["rank"], "key": r["key"], "name": r["name"],
             "types": r["pokemon"].get("types"), "isNew": r["pokemon"].get("isNew"),
             "rankChange": r.get("rankChange")}
            for r in f["rankings"]]
    return out


def scrape_replica_page(page, delay):
    s = fetch(f"{BASE}/replica-teams?page={page}", delay)
    return object_with(s, "teamCodes")


def scrape_pokemon(key, delay):
    s = fetch(f"{BASE}/pokedex/{key}", delay)
    o = object_with(s, "singleDetail")
    if o is None or not o.get("singleDetail"):
        return None
    sd, lk = o["singleDetail"], o["lookupData"]
    mv = {x["id"]: x["key"] for x in lk["moves"]}
    it = {x["id"]: x["key"] for x in lk["items"]}
    ab = {x["id"]: x["key"] for x in lk["abilities"]}
    na = {x["id"]: x for x in lk["natures"]}

    def conv(lst, table):
        return [[table.get(x["id"], str(x["id"])), x["usagePercent"]] for x in lst]

    def spread(sp):  # '02-20-00-00-00-20' — 16진수 스탯포인트 H-A-B-C-D-S
        return [int(v, 16) for v in sp.split("-")]

    return {
        "key": key,
        "updatedAt": o.get("updatedAt"),
        "moves": conv(sd["moves"], mv),
        "abilities": conv(sd["abilities"], ab),
        "items": conv(sd["items"], it),
        "natures": [[_nature_key(na.get(x["id"])), x["usagePercent"]] for x in sd["natures"]],
        "training": [[spread(x["spread"]), x["usagePercent"]] for x in sd["training"]],
        "teammates": [x["key"] for x in sd["team"]["ttog"]],
        "win": {"pokemon": [x["key"] for x in sd["win"]["pokemon"]], "moves": conv(sd["win"]["moves"], mv)},
        "lose": {"pokemon": [x["key"] for x in sd["lose"]["pokemon"]], "moves": conv(sd["lose"]["moves"], mv)},
    }


_STAT_KEY = {"attack": "atk", "defense": "def", "special-attack": "spa", "special-defense": "spd", "speed": "spe",
             "spAttack": "spa", "spDefense": "spd"}
NATURES = {  # 영문 키 → (올림, 내림)
    "hardy": None, "lonely": ("atk", "def"), "brave": ("atk", "spe"), "adamant": ("atk", "spa"), "naughty": ("atk", "spd"),
    "bold": ("def", "atk"), "docile": None, "relaxed": ("def", "spe"), "impish": ("def", "spa"), "lax": ("def", "spd"),
    "timid": ("spe", "atk"), "hasty": ("spe", "def"), "serious": None, "jolly": ("spe", "spa"), "naive": ("spe", "spd"),
    "modest": ("spa", "atk"), "mild": ("spa", "def"), "quiet": ("spa", "spe"), "bashful": None, "rash": ("spa", "spd"),
    "calm": ("spd", "atk"), "gentle": ("spd", "def"), "sassy": ("spd", "spe"), "careful": ("spd", "spa"), "quirky": None,
}


def _nature_key(n):
    if not n:
        return "serious"
    inc, dec = _STAT_KEY.get(n.get("increased"), n.get("increased")), _STAT_KEY.get(n.get("decreased"), n.get("decreased"))
    for k, v in NATURES.items():
        if v == (inc, dec):
            return k
    return "serious"


# ── 전체 수집 ─────────────────────────────────────────────────────

def run(max_mons=None, team_pages=None, delay=1.0, day=None, log=print):
    """max_mons=None 이면 싱글 순위에 있는 전 종(op.gg 에 통계가 있는 전체)."""
    day = day or date.today().isoformat()
    out = RAW / day
    (out / "pokemon").mkdir(parents=True, exist_ok=True)

    tier_f = out / "tier.json"
    if not tier_f.exists():
        tier_f.write_text(json.dumps(scrape_tier(delay), ensure_ascii=False), encoding="utf-8")
    tier = json.loads(tier_f.read_text(encoding="utf-8"))
    singles = tier["formats"]["single"]
    log(f"[tier] 시즌 {tier['season']} 싱글 {len(singles)}종")

    # 레플리카 팀 — 1쪽에서 도감·기술·아이템 사전도 같이 뽑는다
    rep_f = out / "replica_teams.json"
    dex_f = out / "dex.json"
    if not rep_f.exists() or not dex_f.exists():
        first = scrape_replica_page(1, delay)
        pages = -(-first["initialTotalCount"] // first["pageSize"])
        if team_pages:
            pages = min(pages, team_pages)
        dex = {"pokemon": first["pokemonList"], "moves": first["movesList"], "items": first["itemsList"],
               "types": first["typeTranslations"], "abilities": first.get("abilityTranslations")}
        dex_f.write_text(json.dumps(dex, ensure_ascii=False), encoding="utf-8")
        teams = list(first["teamCodes"])
        for p in range(2, pages + 1):
            try:
                teams += scrape_replica_page(p, delay)["teamCodes"]
            except RuntimeError as e:
                log(f"  [replica] {p}쪽 실패: {e}")
            if p % 10 == 0:
                log(f"  [replica] {p}/{pages}쪽")
        slim = [{"id": t["id"], "format": t["battleFormat"], "createdAt": t["createdAt"],
                 "author": (t.get("author") or {}).get("nickname"), "title": t.get("title"),
                 "slots": t["slots"]} for t in teams]
        rep_f.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")
    teams = json.loads(rep_f.read_text(encoding="utf-8"))
    log(f"[replica] 팀 {len(teams)}개 (싱글 {sum(t['format'] == 'SINGLE' for t in teams)})")

    todo = [r["key"] for r in (singles if max_mons is None else singles[:max_mons])]
    got = 0
    for n, key in enumerate(todo, 1):
        f = out / "pokemon" / f"{key}.json"
        if f.exists():
            got += 1
            continue
        try:
            d = scrape_pokemon(key, delay)
        except (RuntimeError, ValueError, KeyError) as e:
            log(f"  [pokedex] {key} 실패: {e}")
            continue
        if d:
            f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            got += 1
        if n % 10 == 0:
            log(f"  [pokedex] {n}/{len(todo)}")
    log(f"[pokedex] {got}/{len(todo)}종 저장 → {out}")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="op.gg 포켓몬 챔피언스 수집")
    ap.add_argument("--max-mons", type=int, default=None, help="기본: 싱글 순위 전 종")
    ap.add_argument("--team-pages", type=int, default=None)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    run(a.max_mons, a.team_pages, a.delay)
