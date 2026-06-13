"""Tests for shared.defaults — default state structures."""

from shared.defaults import (
    AGENT_METRICS_DEFAULT,
    GENERATED_TOKENS_DEFAULT,
    INBOX_QUEUE_DEFAULT,
    PROCESSED_IMAGES_DEFAULT,
    PROCESSED_NPCS_DEFAULT,
    REQUIRED_DIRS,
    SCENARIOS_DEFAULT,
    STATE_FILE_DEFAULTS,
    TASKS_STATE_DEFAULT,
    TEXT_STATE_FILES,
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
        assert ".system/state/inbox-queue.json" in STATE_FILE_DEFAULTS
        assert ".agents/vision/state/processed-images.json" in STATE_FILE_DEFAULTS
        assert ".agents/lore/state/processed-npcs.json" in STATE_FILE_DEFAULTS
        assert ".agents/runtime/state/tasks-state.json" in STATE_FILE_DEFAULTS

    def test_required_dirs_contains_shared_state(self):
        assert ".system/state" in REQUIRED_DIRS

    def test_required_dirs_covers_all_agents(self):
        agent_names = ["ingestion", "vision", "lore", "token",
                       "classification", "wiki", "review", "repair", "wikilink"]
        for name in agent_names:
            assert any(name in d for d in REQUIRED_DIRS), f"Missing dir for: {name}"


class TestNewDefaults:
    def test_agent_metrics_default_empty_dict(self):
        assert AGENT_METRICS_DEFAULT == {}

    def test_agent_metrics_in_state_file_defaults(self):
        assert ".agents/runtime/state/agent-metrics.json" in STATE_FILE_DEFAULTS
        assert STATE_FILE_DEFAULTS[".agents/runtime/state/agent-metrics.json"] == {}

    def test_text_state_files_contains_all_four(self):
        expected = [
            ".agents/ingestion/state/processed-docx.txt",
            ".agents/wiki/state/processed.txt",
            ".agents/wiki/state/bad-wiki-docs.txt",
            ".agents/classification/state/bad-docs.txt",
        ]
        for path in expected:
            assert path in TEXT_STATE_FILES, f"Missing: {path}"

    def test_text_state_files_are_txt(self):
        for path in TEXT_STATE_FILES:
            assert path.endswith(".txt"), f"Expected .txt: {path}"

    def test_text_state_files_not_in_json_defaults(self):
        for path in TEXT_STATE_FILES:
            assert path not in STATE_FILE_DEFAULTS, f"Should not be in JSON defaults: {path}"
