import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.evaluation.store import (
    STALE_LOCK_S,
    append_line,
    DailyTokenLimitExceededError,
    EvaluationInProgressError,
    EvaluationStoreError,
    ResultStore,
    UsageLedger,
    UsageRecord,
)
from app.models import EvaluationResult, PrecheckResults, TokenUsage

_NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _result(comment_id=2002, rule_version="v1", passed=("ST0-001",)):
    return EvaluationResult(
        comment_id=comment_id, message_id=500, stress_test_id="ST0", rule_version=rule_version,
        model="claude-sonnet-5", evaluated_at=_NOW, correlation_id="c-1", stages_evaluated=[1],
        passed_rule_ids=list(passed), findings=[],
        prechecks=PrecheckResults(problem_count=None, selected_count=0, link_count=0,
                                  dataset_link_present=False, dataset_file_count=0, image_count=0),
        usage=TokenUsage(input_tokens=10),
    )


def test_a_stored_result_is_found_by_comment_and_rule_version(tmp_path):
    store = ResultStore(tmp_path)
    assert store.get(2002, "v1") is None
    store.put(_result())
    assert store.get(2002, "v1") == _result()
    assert store.get(2002, "v2") is None  # a new rule version is a new evaluation
    assert store.get(3003, "v1") is None


def test_putting_the_same_key_twice_keeps_the_first_result(tmp_path):
    store = ResultStore(tmp_path)
    first = store.put(_result(passed=("ST0-001",)))
    second = store.put(_result(passed=("ST0-002",)))
    assert second == first
    assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 1


def test_results_survive_a_new_store_instance(tmp_path):
    ResultStore(tmp_path).put(_result())
    assert ResultStore(tmp_path).get(2002, "v1") is not None


def test_a_corrupt_line_is_reported_by_line_number(tmp_path):
    ResultStore(tmp_path).put(_result())
    with open(tmp_path / "results.jsonl", "a") as handle:
        handle.write("{not json\n")
    with pytest.raises(EvaluationStoreError, match="line 2"):
        ResultStore(tmp_path).get(2002, "v1")


def test_a_torn_last_line_does_not_swallow_the_next_result(tmp_path):
    path = tmp_path / "results.jsonl"
    path.write_text(_result().model_dump_json() + "\n" + '{"comment_id": 7')  # crash mid-write
    append_line(path, _result(comment_id=3003).model_dump_json())
    lines = path.read_text().splitlines()
    assert lines[1] == '{"comment_id": 7'  # only the torn line is lost
    assert EvaluationResult.model_validate_json(lines[2]).comment_id == 3003


def test_an_unwritable_store_raises(tmp_path):
    (tmp_path / "results.jsonl").mkdir()  # a directory where the file should be
    with pytest.raises(EvaluationStoreError):
        ResultStore(tmp_path).put(_result())


def test_a_claim_blocks_a_second_run_and_is_released(tmp_path):
    store = ResultStore(tmp_path)
    with store.claim(2002, "v1"):
        with pytest.raises(EvaluationInProgressError):
            with store.claim(2002, "v1"):
                pass
        with store.claim(3003, "v1"):  # other keys are independent
            pass
    with store.claim(2002, "v1"):  # released after the first run
        pass


def test_a_claim_is_released_when_the_run_fails(tmp_path):
    store = ResultStore(tmp_path)
    with pytest.raises(RuntimeError):
        with store.claim(2002, "v1"):
            raise RuntimeError("Claude failed")
    with store.claim(2002, "v1"):
        pass


def test_a_stale_claim_from_a_crashed_run_is_taken_over(tmp_path):
    lock = tmp_path / "locks" / "2002-v1.lock"
    lock.parent.mkdir()
    lock.touch()  # left behind by a crashed run
    old = lock.stat().st_mtime - STALE_LOCK_S - 1
    os.utime(lock, (old, old))
    with ResultStore(tmp_path).claim(2002, "v1"):
        pass


def test_only_one_of_many_concurrent_claims_wins(tmp_path):
    store, wins, losses = ResultStore(tmp_path), [], []
    start, all_tried = threading.Barrier(8), threading.Event()

    def run():
        start.wait()
        try:
            with store.claim(2002, "v1"):
                wins.append(1)
                all_tried.wait(5)  # hold the claim until every other thread has tried
        except EvaluationInProgressError:
            losses.append(1)
            if len(losses) == 7:
                all_tried.set()

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert (len(wins), len(losses)) == (1, 7)


def _usage(at, total_input):
    return UsageRecord(recorded_at=at, comment_id=2002, stage=1, model="claude-sonnet-5",
                       usage=TokenUsage(input_tokens=total_input))


def test_usage_is_summed_per_utc_day(tmp_path):
    ledger = UsageLedger(tmp_path, daily_limit=10_000)
    ledger.record(_usage(_NOW, 100))
    ledger.record(_usage(_NOW.replace(hour=23, minute=59), 200))
    ledger.record(_usage(_NOW + timedelta(days=1), 400))  # next UTC day
    ledger.record(_usage(datetime(2026, 9, 28, 1, 0, tzinfo=timezone(timedelta(hours=5))), 800))  # 27th in UTC
    assert ledger.used_on(_NOW.date()) == 300
    assert ledger.used_on((_NOW + timedelta(days=1)).date()) == 400


def test_all_token_kinds_count_towards_the_limit(tmp_path):
    ledger = UsageLedger(tmp_path, daily_limit=10_000)
    ledger.record(UsageRecord(recorded_at=_NOW, comment_id=1, stage=1, model="m", usage=TokenUsage(
        input_tokens=1, cache_creation_input_tokens=10, cache_read_input_tokens=100, output_tokens=1000)))
    assert ledger.used_on(_NOW.date()) == 1111


def test_the_budget_allows_exactly_the_limit_and_refuses_over_it(tmp_path):
    ledger = UsageLedger(tmp_path, daily_limit=1_000)
    ledger.record(_usage(_NOW, 600))
    ledger.check_budget(400, _NOW)
    with pytest.raises(DailyTokenLimitExceededError, match="600 used today"):
        ledger.check_budget(401, _NOW)


def test_a_new_day_starts_with_a_fresh_budget(tmp_path):
    ledger = UsageLedger(tmp_path, daily_limit=1_000)
    ledger.record(_usage(_NOW, 1_000))
    ledger.check_budget(1_000, _NOW + timedelta(days=1))
