"""
    Local regression evaluation: runs each case through the agent and checks its tool calls and answer.
    Cases live in eval/cases.json (gitignored). Start from eval/cases.sample.json, which targets the sample cafes.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

from agent_framework import ExpectedToolCall, LocalEvaluator, evaluate_agent, evaluator, tool_call_args_match

import agent

CASES_FILE = Path(__file__).parent / "eval" / "cases.json"


@evaluator
def mentions_expected(response: str, expected_output: str) -> bool:
    """Passes when the answer contains the case's expected phrase (case-insensitive); no phrase always passes."""
    return expected_output.lower() in response.lower()


@evaluator
def tools_called(conversation) -> dict:
    """Always passes; records the main agent's tool calls, in order, so the report can show them."""
    names = [c.name for m in conversation for c in (m.contents or []) if c.type == "function_call" and c.name]
    return {"passed": True, "reason": ", ".join(names) or "(none)"}


async def main() -> None:
    if not CASES_FILE.exists():
        sys.exit(f"{CASES_FILE} not found: copy eval/cases.sample.json to eval/cases.json and edit it.")
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))

    logging.basicConfig(level=logging.WARNING)
    agent.init_agent()
    async with agent._reader, agent.get_agent() as coffee_agent:
        results = await evaluate_agent(
            agent=coffee_agent,
            queries=[c["query"] for c in cases],
            expected_output=[c.get("expected_phrase", "") for c in cases],
            expected_tool_calls=[
                [ExpectedToolCall(t["name"], t.get("arguments")) for t in c.get("tools", [])] for c in cases
            ],
            evaluators=LocalEvaluator(tool_call_args_match, mentions_expected, tools_called),
        )

        for result in results:
            print(f"\n{result.passed}/{result.total} passed")
            for item in result.items:
                failed = [s.name for s in item.scores if s.passed is False]
                called = next(((s.sample or {}).get("reason", "") for s in item.scores if s.name == "tools_called"), "")
                print(f"\n  [{item.status}] {item.input_text}" + (f"  (failed: {', '.join(failed)})" if failed else ""))
                print(f"      tools:  {called}")
                print(f"      answer: {item.output_text or '(no answer)'}")


if __name__ == "__main__":
    asyncio.run(main())