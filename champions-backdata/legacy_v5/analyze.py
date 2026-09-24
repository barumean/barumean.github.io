"""사용법: python analyze.py battles.csv
secret.env 예시:  OPENAI_API_KEY=sk-...
"""
import os
import sys
from pathlib import Path

from openai import OpenAI

# secret.env 로드 (python-dotenv 없이)
for line in Path(__file__).with_name("secret.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))

SYSTEM_PROMPT = """Analyze provided Pokémon battle data to extract meaningful insights, trends, or summaries as requested.

Carefully interpret the data prior to reaching any conclusions. For every answer:
- Begin with a step-by-step reasoning process: Describe the relevant observations, trends, or calculations used to arrive at your analysis.
- Conclude with a clear, concise summary or result statement presented after the reasoning.

Be prepared to perform multiple analyses or explore follow-up questions if the user requests further breakdowns or deeper insights. Always clarify your logical process before presenting conclusions.

**Output Format:**
- For most analyses, provide:
  - **Reasoning:** A detailed breakdown of the process, patterns, or statistics discovered (1–2 paragraphs).
  - **Conclusion:** A succinct summary of your findings (1–2 sentences), placed after the reasoning section.
- If the user requests tabular, visual, or JSON formats, adapt your output accordingly and specify reasoning and conclusions using designated fields.

---

**Example 1: (Simple Analysis, Text Output)**

Input: Who has the highest win rate?

Output:
Reasoning:
I reviewed the battle records for each Pokémon, calculated their number of wins divided by total battles, and compared these ratios. [Insert step-by-step logic with sample calculations.]
Conclusion:
[Pikachu] has the highest win rate at [85%], winning [17 out of 20] recorded battles.

---

**Example 2: (Advanced Analysis, JSON Output)**

Input: Summarize win rates for each Pokémon by type, as JSON.

Output:
{
  "Reasoning": "I grouped Pokémon by their elemental type (e.g., Water, Fire), computed win totals and total battles for each, then derived the win rates.",
  "Conclusion": "Water-type Pokémon show the highest average win rate of 62%, while Grass types are lowest at 38%.",
  "SummaryByType": {
    "Water": {"Wins": 31, "Total": 50, "WinRate": 0.62},
    "Grass": {"Wins": 19, "Total": 50, "WinRate": 0.38}
    // ...additional types
  }
}

---

*Remember: Always provide detailed reasoning first, followed by conclusions or final answers. Adapt outputs to match the user's requested detail or format. Repeat or extend analysis if prompted by follow-up questions.*

---

**Important Reminder:**
Begin every response with reasoning, followed by clear summaries or conclusions. Format outputs (text, JSON, table) as appropriate for the user's query. Continue iterative analyses if asked."""


def ask(client, user_text, prev_id=None):
    """질문 1회 전송 후 스트리밍 출력, response id 반환."""
    kwargs = dict(
        model="gpt-6-astra",
        input=[{"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
        text={"format": {"type": "text"}, "verbosity": "medium"},
        reasoning={"effort": "medium", "mode": "standard", "summary": "auto"},
        tools=[],
        stream=True,
        store=True,
        include=["reasoning.encrypted_content", "web_search_call.action.sources"],
    )
    if prev_id:
        kwargs["previous_response_id"] = prev_id  # 이전 대화(데이터 포함) 이어받기
    else:
        kwargs["instructions"] = SYSTEM_PROMPT  # 첫 요청에만 시스템 프롬프트

    resp_id = None
    for event in client.responses.create(**kwargs):
        if event.type in ("response.output_text.delta", "response.refusal.delta"):
            print(event.delta, end="", flush=True)
        elif event.type == "response.completed":
            resp_id = event.response.id
        elif event.type == "error":
            raise RuntimeError(event.message)
        elif event.type == "response.failed":
            raise RuntimeError(event.response.error)
    print()
    return resp_id


def main():
    if len(sys.argv) < 2:
        sys.exit("사용법: python analyze.py <데이터파일(csv/json/txt)>")
    data = Path(sys.argv[1]).read_text(encoding="utf-8-sig")  # 엑셀 CSV의 BOM 대응
    # ponytail: 데이터를 통째로 프롬프트에 넣음. 수만 행 이상이면 컨텍스트 초과 → pandas로 요약 후 전송하거나 file 업로드로 전환

    client = OpenAI()  # OPENAI_API_KEY 환경변수 자동 사용
    prev_id = None
    print("질문을 입력하세요 (종료: 빈 줄 또는 q)\n")
    while (q := input("> ").strip()) and q.lower() != "q":
        text = q if prev_id else f"<data>\n{data}\n</data>\n\n{q}"  # 데이터는 첫 질문에만
        prev_id = ask(client, text, prev_id)


if __name__ == "__main__":
    main()
