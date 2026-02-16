"""Tests for the working memory backend: CRUD, TTL, eviction, prompt packing."""

import json
import time
from datetime import datetime, timedelta, timezone

from src.framework.contracts import WorkingMemoryItem
from src.framework.storage.backends.working_memory import WorkingMemoryBackend
from src.framework.types import ItemType


def _make_item(agent_id="agent_1", item_type=ItemType.TASK_STATE, content=None, **kwargs):
    return WorkingMemoryItem(
        agent_id=agent_id,
        item_type=item_type,
        content=content or {"key": "value"},
        **kwargs,
    )


class TestWorkingMemoryCRUD:
    def test_put_and_get(self):
        wm = WorkingMemoryBackend()
        item = _make_item()
        eid = wm.put(item)
        assert eid == item.entity_id
        result = wm.get("agent_1", eid)
        assert result is not None
        assert result.content == {"key": "value"}

    def test_get_missing(self):
        wm = WorkingMemoryBackend()
        assert wm.get("agent_1", "nonexistent") is None

    def test_list_items(self):
        wm = WorkingMemoryBackend()
        wm.put(_make_item(item_type=ItemType.TASK_STATE, content={"a": 1}))
        wm.put(_make_item(item_type=ItemType.RETRIEVED_FACT, content={"b": 2}))
        wm.put(_make_item(item_type=ItemType.TASK_STATE, content={"c": 3}))

        all_items = wm.list_items("agent_1")
        assert len(all_items) == 3

        task_items = wm.list_items("agent_1", item_type=ItemType.TASK_STATE)
        assert len(task_items) == 2

    def test_remove(self):
        wm = WorkingMemoryBackend()
        item = _make_item()
        wm.put(item)
        assert wm.remove("agent_1", item.entity_id) is True
        assert wm.get("agent_1", item.entity_id) is None
        assert wm.remove("agent_1", item.entity_id) is False

    def test_clear(self):
        wm = WorkingMemoryBackend()
        wm.put(_make_item(content={"a": 1}))
        wm.put(_make_item(content={"b": 2}))
        count = wm.clear("agent_1")
        assert count == 2
        assert wm.list_items("agent_1") == []

    def test_per_agent_isolation(self):
        wm = WorkingMemoryBackend()
        wm.put(_make_item(agent_id="a"))
        wm.put(_make_item(agent_id="b"))
        assert len(wm.list_items("a")) == 1
        assert len(wm.list_items("b")) == 1


class TestWorkingMemoryTTL:
    def test_expired_item_not_returned(self):
        wm = WorkingMemoryBackend()
        item = _make_item(
            ttl_seconds=1,
            # Set timestamp in the past so it's already expired
        )
        item.timestamp_utc = datetime.now(timezone.utc) - timedelta(seconds=5)
        wm.put(item)
        assert wm.get("agent_1", item.entity_id) is None

    def test_non_expired_item_returned(self):
        wm = WorkingMemoryBackend()
        item = _make_item(ttl_seconds=3600)  # 1 hour TTL
        wm.put(item)
        assert wm.get("agent_1", item.entity_id) is not None

    def test_list_evicts_expired(self):
        wm = WorkingMemoryBackend()
        fresh = _make_item(content={"fresh": True}, ttl_seconds=3600)
        expired = _make_item(content={"expired": True}, ttl_seconds=1)
        expired.timestamp_utc = datetime.now(timezone.utc) - timedelta(seconds=5)

        wm.put(fresh)
        wm.put(expired)
        items = wm.list_items("agent_1")
        assert len(items) == 1
        assert items[0].content["fresh"] is True


class TestWorkingMemoryRelevance:
    def test_time_decay(self):
        wm = WorkingMemoryBackend(decay_rate=0.95)
        item = _make_item(relevance_score=1.0)
        item.timestamp_utc = datetime.now(timezone.utc) - timedelta(minutes=10)
        wm.put(item)

        score = wm.effective_relevance(item)
        # 0.95^10 ~ 0.5987
        assert 0.55 < score < 0.65

    def test_fresh_item_high_relevance(self):
        wm = WorkingMemoryBackend()
        item = _make_item(relevance_score=1.0)
        wm.put(item)
        score = wm.effective_relevance(item)
        assert score > 0.99


class TestWorkingMemoryPromptPacking:
    def test_empty_store(self):
        wm = WorkingMemoryBackend()
        assert wm.get_context_for_prompt("agent_1", max_tokens=1000) == ""

    def test_packs_items(self):
        wm = WorkingMemoryBackend()
        wm.put(_make_item(content={"task": "research startups"}, relevance_score=0.9))
        wm.put(_make_item(content={"task": "analyse data"}, relevance_score=0.5))

        prompt = wm.get_context_for_prompt("agent_1", max_tokens=1000)
        assert "[task_state]" in prompt
        assert "research" in prompt

    def test_respects_token_budget(self):
        wm = WorkingMemoryBackend()
        # Add many items
        for i in range(50):
            wm.put(_make_item(content={"data": "x" * 200}, relevance_score=1.0))

        prompt = wm.get_context_for_prompt("agent_1", max_tokens=100)
        # 100 tokens * 4 chars = 400 chars max
        assert len(prompt) <= 500  # Some slack for formatting

    def test_highest_relevance_first(self):
        wm = WorkingMemoryBackend()
        wm.put(_make_item(content={"low": True}, relevance_score=0.1))
        wm.put(_make_item(content={"high": True}, relevance_score=0.9))

        prompt = wm.get_context_for_prompt("agent_1", max_tokens=1000)
        lines = prompt.strip().split("\n")
        # High relevance item should come first
        assert "high" in lines[0]


class TestWorkingMemoryCheckpoint:
    def test_save_and_load(self, tmp_path):
        wm = WorkingMemoryBackend()
        wm.put(_make_item(agent_id="a1", content={"x": 1}))
        wm.put(_make_item(agent_id="a2", content={"y": 2}))

        path = str(tmp_path / "checkpoint.json")
        wm.save_checkpoint(path)

        wm2 = WorkingMemoryBackend()
        wm2.load_checkpoint(path)

        assert len(wm2.list_items("a1")) == 1
        assert len(wm2.list_items("a2")) == 1
        assert wm2.list_items("a1")[0].content == {"x": 1}
