# pytest configuration for NexusCampaigns tests
# I am testing file changes.
#
# Source: D:\Library\rpg\dm\pathway\knowledge-base\tests\
# Copied 2026-06-15. Task 2 adaptation status (2026-06-15):
#
#   DONE — test_00_pipeline_constraints.py:
#     New tests validating AGENTS.md rules via shared agent modules:
#     VaultGuard, QualityGate, slug_utils, linking_rules. All pass.
#
#   DONE (path updated, graceful skip) — Python-module tests (09,10,15):
#     SCRIPT_PATH updated to .agents/*/tools/*.py. Tests skip at module level
#     because the agent API changed (old function names removed in refactor).
#     Next step: rewrite against new API or extend .agents/tests/.
#     - test_09 → .agents/lore/tools/generate_npcs.py
#     - test_10 → .agents/token/tools/generate_tokens.py
#     - test_15 → .agents/review/tools/flag_short_files.py
#
#   DONE (skip message updated) — test_06_match_token:
#     No NexusCampaigns equivalent. Token matching is handled by vision/token agents.
#
#   PENDING — PS-script tests (01,02,03,04,05,06-classify,07,08,11,12,13):
#     No equivalent PS scripts exist in NexusCampaigns (Python agents used instead).
#     Equivalent agents: .agents/cleanup, .agents/wiki, .agents/classification,
#     .agents/ingestion, .agents/repair, .agents/review, .agents/vision.
#     Tests skip gracefully (SCRIPT_PATH doesn't exist). Rewrite against Python
#     agent APIs or extend .agents/tests/ to add coverage.
#
#   UNCHANGED — test_classify_images.py:
#     Pure-logic tests — still valid and fully passing (164 pass, 4 skip).

from pathlib import Path

VAULT_ROOT = Path(__file__).parent.parent
