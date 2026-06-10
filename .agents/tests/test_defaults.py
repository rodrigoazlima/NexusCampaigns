"""Tests for shared.defaults — default state structures."""

from shared.defaults import (
    GENERATED_TOKENS_DEFAULT,
    INBOX_QUEUE_DEFAULT,
    PROCESSED_IMAGES_DEFAULT,
    PROCESSED_NPCS_DEFAULT,
    REQUIRED_DIRS,
    SCENARIOS_DEFAULT,
    STATE_FILE_DEFAULTS,
    TASKS_STATE_DEFAULT,
    TOKEN_LINKS_DEFAULT,
)


class TestDefaults:
    def test_inbox_queue_empty_dict(self):
        assert INBOX_QUEUE_DEFAULT == {}

    def test_processed_images_v2(self):
        assert PROCESSED_IMAGES_DEFAULT["version"] == 2
        assert "images" in PROCESSED_IMAGES_DEFAULT
        assert "pathIndex" in PROCESSED_IMAGES_DEFAULT

    def test_processed_npcs_empty(self):
        assert PROCESSED_NPCS_DEFAULT == {}

    def test_token_links_empty(self):
        assert TOKEN_LINKS_DEFAULT == {}

    def test_generated_tokens_empty(self):
        assert GENERATED_TOKENS_DEFAULT == {}

    def test_scenarios_has_placeholder(self):
        assert len(SCENARIOS_DEFAULT) >= 1
        assert SCENARIOS_DEFAULT[0]["active"] is False

    def test_tasks_state_has_all_agents(self):
        expected_agents = [
            "repair-agent", "review-agent", "ingestion-agent",
            "vision-agent", "lore-agent", "token-agent",
            "wiki-agent", "classification-agent",
            "review-agent-short-files", "wikilink-agent",
        ]
        for agent in expected_agents:
            assert agent in TASKS_STATE_DEFAULT, f"Missing: {agent}"
            assert TASKS_STATE_DEFAULT[agent]["lastRun"].startswith("1970")

    def test_state_file_defaults_covers_all_files(self):
        assert ".shared/state/inbox-queue.json" in STATE_FILE_DEFAULTS
        assert ".agents/vision/state/processed-images.json" in STATE_FILE_DEFAULTS
        assert ".agents/lore/state/processed-npcs.json" in STATE_FILE_DEFAULTS
        assert ".agents/runtime/state/tasks-state.json" in STATE_FILE_DEFAULTS

    def test_required_dirs_contains_shared_state(self):
        assert ".shared/state" in REQUIRED_DIRS

    def test_required_dirs_covers_all_agents(self):
        agent_names = ["ingestion", "vision", "lore", "token",
                       "classification", "wiki", "review", "repair", "wikilink"]
        for name in agent_names:
            assert any(name in d for d in REQUIRED_DIRS), f"Missing dir for: {name}"
