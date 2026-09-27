"""파티 입력 파싱과 출력 서식.

파티 파일 한 줄 = 한 마리. 이름만 적어도 되고, 아는 만큼 더 적는다.
    한카리아스
    메가보만다
    누리레느 @ 자뭉열매
    마스카나 @ 기합의띠 | 고집 | 2/32/0/0/0/32 | 트릭플라워, 트리플악셀, 기습, 깨트리기
'|' 로 나눈 칸은 순서 상관없이: 성격(한글/영문), 스탯포인트(H/A/B/C/D/S), 기술(쉼표 구분), 특성(특성:이름),
유형(물리형/특수형/쌍두형, 역할까지 쓰려면 '물리 내구형'·'특수 공격형' — moves 추천을 그 유형으로 제한)
'#' 뒤는 주석.
"""
import re

from .scrape import NATURES

NATURE_KO = {"hardy": "노력", "lonely": "외로움", "brave": "용감", "adamant": "고집", "naughty": "개구쟁이",
             "bold": "대담", "docile": "온순", "relaxed": "무사태평", "impish": "장난꾸러기", "lax": "촐랑",
             "timid": "겁쟁이", "hasty": "성급", "serious": "성실", "jolly": "명랑", "naive": "천진난만",
             "modest": "조심", "mild": "의젓", "quiet": "냉정", "bashful": "수줍음", "rash": "덜렁",
             "calm": "차분", "gentle": "얌전", "sassy": "건방", "careful": "신중", "quirky": "변덕"}
KO_NATURE = {v: k for k, v in NATURE_KO.items()}
ARCH_WORD = {"물리형": "physical", "특수형": "special", "쌍두형": "mixed",
             "physical": "physical", "special": "special", "mixed": "mixed"}
STAT_KO = ["H", "A", "B", "C", "D", "S"]


def parse_line(D, line):
    line = line.split("#")[0].strip()
    if not line:
        return None
    parts = [p.strip() for p in line.split("|")]
    head = parts[0]
    item = None
    if "@" in head:
        head, item = [x.strip() for x in head.split("@", 1)]
        item = D.item(item) if item else None
    key = D.mon(head)
    if D.DEX[key]["base_key"]:                   # 메가 이름으로 적으면 스톤을 든 것으로
        item = item or D.DEX[key]["item"]
        key = D.DEX[key]["base_key"]
    out = {"key": key, "item": item, "nature": None, "sp": None, "moves": None, "ability": None, "arch": None}
    for p in parts[1:]:
        if not p:
            continue
        m = re.fullmatch(r"(물리|특수|쌍두)형?\s*(공격형|내구형)?", p)
        if p in ARCH_WORD or m:
            if m:
                a = {"물리": "physical", "특수": "special", "쌍두": "mixed"}[m.group(1)]
                r = {"공격형": "attacker", "내구형": "tank"}.get(m.group(2) or "")
                out["arch"] = f"{a}:{r}" if r else a
            else:
                out["arch"] = ARCH_WORD[p]
        elif p.startswith("혼합") or p.startswith("비정형") or p == "변신형":
            continue                                   # 표시용 라벨은 입력에서 무시
        elif p in KO_NATURE or p.lower() in NATURES:
            out["nature"] = KO_NATURE.get(p, p.lower())
        elif p.replace("/", "").replace(" ", "").isdigit() and p.count("/") == 5:
            out["sp"] = [int(x) for x in p.split("/")]
        elif p.startswith("특성:") or p.lower().startswith("ability:"):
            out["ability"] = D.ability(p.split(":", 1)[1])
        else:
            out["moves"] = [D.move(m) for m in p.replace("/", ",").split(",") if m.strip()]
    return out


def parse_party(D, text):
    """파일 내용 또는 쉼표로 이은 이름 목록."""
    if "\n" not in text and "|" not in text and "@" not in text:
        lines = text.split(",")
    else:
        lines = text.splitlines()
    return [x for x in (parse_line(D, l) for l in lines) if x]


def fmt_sp(sp):
    return " ".join(f"{STAT_KO[i]}{v}" for i, v in enumerate(sp) if v)


def fmt_build(D, b, with_stats=False):
    from .sets import arch_of
    s = f"{D.name(b.form)} [{arch_of(b)}] @ {D.item_name(b.item)} | 특성:{D.ability_name(b.entry_ability)} | {NATURE_KO.get(b.nature, b.nature)} | {fmt_sp(b.sp)} | " + \
        ", ".join(D.move_name(m) for m in b.moves)
    if with_stats:
        s += f"   (실능 {'/'.join(str(x) for x in b.stats)})"
    return s


def party_line(D, b):
    """다시 입력으로 쓸 수 있는 한 줄."""
    from .sets import arch_of
    return f"{D.name(b.key)} @ {D.item_name(b.item)} | {arch_of(b)} | 특성:{D.ability_name(b.entry_ability)} | {NATURE_KO.get(b.nature, b.nature)} | " + \
        "/".join(str(x) for x in b.sp) + " | " + ", ".join(D.move_name(m) for m in b.moves)


def bar(v, width=10):
    n = int(round(abs(v) * width))
    return ("+" if v >= 0 else "-") * n


def table(rows, header):
    w = [max(len(str(r[i])) for r in [header] + rows) for i in range(len(header))]

    def line(r):
        return "| " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(r)) + " |"
    return "\n".join([line(header), "|" + "|".join("-" * (x + 2) for x in w) + "|"] + [line(r) for r in rows])
