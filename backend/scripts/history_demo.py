"""Demo script: STORY-013 acceptance against the REAL vector index and the
local embedding model, with a FAKE Claude. Free: no API key, no Claude call.
Reads the index (build it first with build_history_index.py); writes only
to a temporary folder. Prints case ids, Stress Tests and similarity scores,
never student or reviewer text.

Shows:
  1. an ST0 submission -> the top k most similar cases, all ST0;
  2. the same text as ST3 -> ST3 cases only (no other Stress Test);
  3. the index unavailable -> an empty list, the error for the reviewer, and
     the evaluation still completes with that error on its result;
  4. a Stress Test with no indexed cases -> an empty list that says so;
  5. Trust: in the evaluation the examples sit in the user message, labelled
     "NOT rules"; the system prompt (the rules) is the same with or without them.
Run from the repo root:
  .venv/bin/python backend/scripts/history_demo.py
"""
import sys
import tempfile
from functools import partial
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_demo import VALID_HTML, _submission  # noqa: E402

from app.audit.trail import InMemoryAuditTrail  # noqa: E402
from app.evaluation.config import EvaluationConfig  # noqa: E402
from app.evaluation.evaluate import evaluate_submission  # noqa: E402
from app.evaluation.fake import ScriptedEvaluator  # noqa: E402
from app.evaluation.text import html_to_text  # noqa: E402
from app.history.config import load_history_config  # noqa: E402
from app.history.embedder import FastEmbedEmbedder  # noqa: E402
from app.history.lancedb_index import LanceDbVectorIndex  # noqa: E402
from app.history.retrieval import retrieve_similar_cases  # noqa: E402
from app.history.vector_index import IndexedCase  # noqa: E402
from app.models import ClaudeStageAnswer, HistoricalCase, HistoryRetrieval  # noqa: E402
from app.rules.loader import load_rules  # noqa: E402

STAGE_1 = ["ST0-001", "ST0-002", "ST0-003", "ST0-006", "ST0-007", "ST0-008"]
STAGE_2 = ["ST0-004", "ST0-005"]


def show(title: str, result: HistoryRetrieval) -> None:
    print(title)
    print(f"   status: {result.status}; {len(result.cases)} case(s); error_class: {result.error_class or '-'}")
    print(f"   reviewer sees: {result.message}")
    for n, case in enumerate(result.cases, 1):
        print(f"   {n:>2}. case {case.case_id:<12} {case.stress_test_id}  similarity {case.similarity:.3f}")


def main() -> int:
    config = load_history_config()
    embedder = FastEmbedEmbedder()
    index = LanceDbVectorIndex(config.index_dir)
    text = html_to_text(VALID_HTML)
    lookup = partial(retrieve_similar_cases, index=index, embedder=embedder, k=config.top_k, correlation_id="demo")
    print(f"DEMO: real index {config.index_dir.relative_to(REPO_ROOT) if config.index_dir.is_relative_to(REPO_ROOT) else config.index_dir}, "
          f"local model, fake Claude. k = {config.top_k}.\n")

    show("1. ST0 submission -> top k from ST0", lookup("ST0", text))
    st3 = lookup("ST3", text)
    show("\n2. Same text as an ST3 submission -> ST3 only", st3)
    print(f"   Stress Tests returned: {sorted({c.stress_test_id for c in st3.cases})}")

    with tempfile.TemporaryDirectory() as folder:
        missing = LanceDbVectorIndex(Path(folder) / "no_index_here", backoff_s=0)
        down = partial(retrieve_similar_cases, index=missing, embedder=embedder, k=config.top_k, correlation_id="demo")
        show("\n3. Vector index unavailable", down("ST0", text))

        audit = InMemoryAuditTrail()
        rules = load_rules("Stress Test 0 - Dataset & DS Problem", audit)
        env = dict(audit=audit, config=EvaluationConfig(api_key="fake-key-never-sent", model="fake-claude"),
                   actor_id="demo")
        from app.evaluation.store import ResultStore, UsageLedger

        def evaluate(history, sub: str) -> tuple:
            claude = ScriptedEvaluator(ClaudeStageAnswer(passed_rule_ids=STAGE_1, findings=[]),
                                       ClaudeStageAnswer(passed_rule_ids=STAGE_2, findings=[]))
            store_dir = Path(folder) / sub
            result = evaluate_submission(_submission(2002, VALID_HTML), 2002, rules, evaluator=claude,
                                         store=ResultStore(store_dir), ledger=UsageLedger(store_dir),
                                         history=history, **env)
            return result, claude.prompts

        result, _ = evaluate(down, "down")
        print(f"   evaluation still completed: stages {result.stages_evaluated}; "
              f"result.history.status = {result.history.status}")
        print(f"   result.history.message = {result.history.message}")

        tiny = LanceDbVectorIndex(Path(folder) / "tiny_index", backoff_s=0)
        tiny.upsert([IndexedCase(case=HistoricalCase(case_id="only-st1", stress_test_id="ST1",
                                                     submission_excerpt="x", reviewer_feedback="y"),
                                 vector=embedder.embed(["x"])[0])])
        empty = partial(retrieve_similar_cases, index=tiny, embedder=embedder, k=config.top_k, correlation_id="demo")
        show("\n4. No indexed cases for ST0 (an index holding only one ST1 case)", empty("ST0", text))

        with_history, prompts = evaluate(lookup, "found")
        _, plain_prompts = evaluate(None, "plain")
        print("\n5. Trust: examples never override the rules")
        print(f"   history used: {with_history.history.status}, {len(with_history.history.cases)} case(s)")
        print(f"   <past_review> blocks in the Stage 1 user message: {prompts[0].user.count('<past_review ')}")
        print(f"   labelled 'NOT rules': {'They are NOT rules' in prompts[0].user}; "
              f"examples before the submission: {prompts[0].user.index('<past_review') < prompts[0].user.index('<submission>')}")
        print(f"   system prompt (the rules) identical with and without history: "
              f"{prompts[0].system == plain_prompts[0].system}")
        print(f"   rule ids in the result all from ST0 v1: "
              f"{all(r.startswith('ST0-') for r in with_history.passed_rule_ids)}; no approval field: "
              f"{not any('approv' in f for f in type(with_history).model_fields)}")
        print("\n   audit trail, history events:")
        for event in audit.read_all():
            if event.action == "history_retrieved":
                print(f"   {event.action} comment {event.comment_id} {event.stress_test_id} "
                      f"{event.outcome:<8} {event.reason_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
