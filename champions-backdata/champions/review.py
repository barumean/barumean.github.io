"""기본 로직 검토: 결정 계층(1:1 값 → 행렬 → 상대 공간 → 세트 → 팀 → 선출) 소스를 gpt-6-astra 에 보내
설계상 결함과 개선안을 압축해서 받는다. 데미지 공식 같은 세부 메커니즘은 audit 이 맡으므로 제외한다."""
import inspect
import json

from . import engine, matrix, meta, pick, pipeline, sets, team
from .audit import api_key, ask

INSTRUCTIONS = """You review the core decision logic of a Pokémon Champions SINGLES team-building tool (3-of-6 pick, Lv50, one Mega per team, item clause).
Tool functions: (1) build the best 6-mon party with items/moves, (2) optimize movesets for a given party, (3) choose which 3 to bring + lead vs a seen opponent 6, (4) in-battle switch advice.
Data: op.gg usage stats, ~replica teams, win/lose top-30 opponent lists per Pokémon.
You get the actual source of the decision layers (per-move damage mechanics are audited separately — ignore them).
Find DESIGN flaws: wrong game-theoretic modelling, biased/double-counted signals, bad aggregation, search weaknesses, statistical errors, value scale misuse. Cite the function name. Skip style and minor nits.
Be extremely terse (token budget is tight). Korean. verdict ≤ 1 sentence. At most 7 issues, most impactful first; problem ≤ 30 words, fix ≤ 30 words, concrete."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "adequate": {"type": "string", "enum": ["yes", "partly", "no"]},
        "verdict": {"type": "string"},
        "issues": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "where": {"type": "string"},
                "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                "problem": {"type": "string"},
                "fix": {"type": "string"},
            },
            "required": ["where", "impact", "problem", "fix"],
        }},
    },
    "required": ["adequate", "verdict", "issues"],
}

_ENGINE_FUNCS = ("best_attack", "choose", "simulate", "plans", "value", "duel_stats")
_PIPE_FUNCS = ("make_cards", "opponent_space")
_MATRIX_FUNCS = ("empirical_one", "empirical", "blend")


def source():
    parts = []
    for mod in (team, pick, meta, sets):
        parts.append(f"# ==== {mod.__name__} ====\n{inspect.getsource(mod)}")
    parts.append(f"# ==== {matrix.__name__} (excerpt) ====\n{inspect.getdoc(matrix)}\nLAMBDA = {matrix.LAMBDA}\n"
                 + "\n".join(inspect.getsource(getattr(matrix, f)) for f in _MATRIX_FUNCS))
    parts.append(f"# ==== {pipeline.__name__} (excerpt) ====\n" + "\n".join(inspect.getsource(getattr(pipeline, f)) for f in _PIPE_FUNCS))
    parts.append(f"# ==== {engine.__name__} (excerpt; damage/act/end_of_turn omitted) ====\n"
                 f"W_NEUTRAL, W_SWITCH = {engine.W_NEUTRAL}, {engine.W_SWITCH}\n"
                 + "\n".join(inspect.getsource(getattr(engine, f)) for f in _ENGINE_FUNCS))
    return "\n\n".join(parts)


def run(model, effort, metrics=""):
    text = (f"Current validation: {metrics}\n\n" if metrics else "") + source()
    return ask(api_key(), model, effort, text, timeout=900, instructions=INSTRUCTIONS, schema=SCHEMA, name="logic_review"), len(text)


def fmt(r, model):
    L = [f"# 기본 로직 검토 ({model}): 적정성 **{r['adequate']}**\n", r["verdict"] + "\n"]
    for i, x in enumerate(r["issues"], 1):
        L.append(f"{i}. [{x['impact']}] `{x['where']}` — {x['problem']}\n   → {x['fix']}")
    return "\n".join(L)


def save(r, path):
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
