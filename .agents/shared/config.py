"""Vault configuration — two layers.

Layer 1 (dataclasses): VaultConfig / VaultPaths / SystemPaths / LLMEndpointConfig
  Pure structure, no I/O. Loader lives in shared.loaders.

Layer 2 (get_config): Two-level JSON config system.
  .shared/config/global.json  ← always loaded first
  .shared/config/<script>.json ← loaded second, overrides global
  Environment variables NEXUS_* override both JSON layers.
  Falls back to embedded defaults when JSON files are absent.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Layer 1 — Dataclass-based vault config (unchanged public surface)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMEndpointConfig:
    url:      str
    model:    str
    type:     str      # "vision" | "text"
    provider: str


@dataclass(frozen=True)
class VaultPaths:
    """Derived path accessors from a single vault_root."""
    vault_root: Path

    @property
    def inbox(self) -> Path:
        return self.vault_root / "00-Inbox"

    @property
    def processing(self) -> Path:
        return self.vault_root / "01-Processing"

    @property
    def library(self) -> Path:
        return self.vault_root / "02-Library"

    @property
    def campaigns(self) -> Path:
        return self.vault_root / "03-Campaigns"

    @property
    def relationships(self) -> Path:
        return self.vault_root / "04-Relationships"

    @property
    def assets(self) -> Path:
        return self.vault_root / "05-Assets"

    @property
    def archive(self) -> Path:
        return self.vault_root / "99-Archive"


@dataclass(frozen=True)
class SystemPaths:
    """Derived path accessors from a single project_root."""
    project_root: Path

    @property
    def agents_dir(self) -> Path:
        return self.project_root / ".agents"

    @property
    def shared_state(self) -> Path:
        return self.project_root / ".shared" / "state"

    @property
    def logs_dir(self) -> Path:
        return self.agents_dir / "runtime" / "state" / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.agents_dir / "review" / "state" / "reports"

    def agent_state(self, agent_name: str) -> Path:
        return self.agents_dir / agent_name / "state"


@dataclass(frozen=True)
class VaultConfig:
    vault_paths:   VaultPaths
    system_paths:  SystemPaths
    llm_endpoints: dict[str, LLMEndpointConfig] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layer 2 — Pydantic AppConfig + JSON loader
# ---------------------------------------------------------------------------

# Embedded defaults — application works even with no JSON files on disk.
_GLOBAL_DEFAULTS: dict[str, Any] = {
    "vault_root": "knowledge-base",
    "llm": {
        "url":              "http://localhost:1234/v1/chat/completions",
        "model":            "qwen3-vl-4b-instruct",
        "provider":         "lmstudio",
        "timeout_seconds":  120,
        "temperature":      0.0,
        "max_tokens":       4096,
    },
    "logging": {
        "level": "INFO",
        "dir":   ".agents/runtime/state/logs",
    },
    "batch_size":           10,
    "inbox_images":         "00-Inbox/images",
    "processing_dir":       "01-Processing",
    "state_dir":            ".shared/state",
    "retry_attempts":       3,
    "retry_delay_seconds":  5,
    "token_moldura":        "00-Inbox/tokens/Molduras/moldura_default.png",
    "quality_threshold":    7,
}

# Relative location of the config directory inside the project root.
_CONFIG_SUBDIR = ".shared/config"


# ---------------------------------------------------------------------------
# Pydantic sub-models
# ---------------------------------------------------------------------------

class LLMConfig(BaseModel):
    url:             str   = "http://localhost:1234/v1/chat/completions"
    model:           str   = "qwen3-vl-4b-instruct"
    provider:        str   = "lmstudio"
    timeout_seconds: int   = 120
    temperature:     float = 0.0
    max_tokens:      int   = 4096


class LoggingConfig(BaseModel):
    level: str = "INFO"
    dir:   str = ".agents/runtime/state/logs"


class AppConfig(BaseModel):
    """Resolved, type-safe configuration for a single script.

    All Path fields are absolute. Extra script-specific keys are stored in
    ``extra`` so callers can still reach them without breaking validation.
    """

    project_root:        Path
    vault_root:          Path
    llm:                 LLMConfig     = Field(default_factory=LLMConfig)
    logging:             LoggingConfig = Field(default_factory=LoggingConfig)
    batch_size:          int           = 10
    inbox_images:        Path          = Path("00-Inbox/images")
    processing_dir:      Path          = Path("01-Processing")
    state_dir:           Path          = Path(".shared/state")
    retry_attempts:      int           = 3
    retry_delay_seconds: int           = 5
    token_moldura:       Path          = Path("00-Inbox/tokens/Molduras/moldura_default.png")
    quality_threshold:   int           = 7
    extra:               dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("project_root", "vault_root", "inbox_images",
                     "processing_dir", "state_dir", "token_moldura", mode="before")
    @classmethod
    def _to_path(cls, v: Any) -> Path:
        return Path(v)

    # Convenience accessors that mirror VaultPaths properties.
    @property
    def inbox(self) -> Path:
        return self.inbox_images.parent  # 00-Inbox/

    @property
    def logs_dir(self) -> Path:
        return self.project_root / self.logging.dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    """Walk up from *start* until finding a directory that contains knowledge-base/."""
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "knowledge-base").is_dir():
            return candidate
    raise FileNotFoundError(
        f"No project root found (no knowledge-base/ directory) searching up from {start}.\n"
        "Hint: make sure you are running from inside the NexusCampaigns tree."
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*.

    Nested dicts are merged; all other types are replaced.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _load_json_safe(path: Path) -> dict[str, Any]:
    """Load JSON file; return {} on missing file, raise on parse error."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in config file {path}: {exc}\n"
            "Hint: validate with `python -m json.tool <file>`."
        ) from exc


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Apply NEXUS_* environment variables on top of *cfg*.

    Mapping:
      NEXUS_VAULT_ROOT           → vault_root
      NEXUS_BATCH_SIZE           → batch_size  (int)
      NEXUS_QUALITY_THRESHOLD    → quality_threshold  (int)
      NEXUS_RETRY_ATTEMPTS       → retry_attempts  (int)
      NEXUS_RETRY_DELAY_SECONDS  → retry_delay_seconds  (int)
      NEXUS_LOG_LEVEL            → logging.level
      NEXUS_LOG_DIR              → logging.dir
      NEXUS_LLM_URL              → llm.url
      NEXUS_LLM_MODEL            → llm.model
      NEXUS_LLM_PROVIDER         → llm.provider
      NEXUS_LLM_MAX_TOKENS       → llm.max_tokens  (int)
      NEXUS_LLM_TIMEOUT          → llm.timeout_seconds  (int)
      NEXUS_LLM_TEMPERATURE      → llm.temperature  (float)
    """
    cfg = dict(cfg)

    _str_map = {
        "NEXUS_VAULT_ROOT": "vault_root",
    }
    _int_map = {
        "NEXUS_BATCH_SIZE":          "batch_size",
        "NEXUS_QUALITY_THRESHOLD":   "quality_threshold",
        "NEXUS_RETRY_ATTEMPTS":      "retry_attempts",
        "NEXUS_RETRY_DELAY_SECONDS": "retry_delay_seconds",
    }

    for env_key, cfg_key in _str_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            cfg[cfg_key] = val

    for env_key, cfg_key in _int_map.items():
        val = os.environ.get(env_key)
        if val is not None:
            try:
                cfg[cfg_key] = int(val)
            except ValueError:
                raise ValueError(f"Environment variable {env_key} must be an integer, got: {val!r}")

    # Nested llm.*
    llm_overrides: dict[str, Any] = {}
    _llm_str  = {"NEXUS_LLM_URL": "url", "NEXUS_LLM_MODEL": "model", "NEXUS_LLM_PROVIDER": "provider"}
    _llm_int  = {"NEXUS_LLM_MAX_TOKENS": "max_tokens", "NEXUS_LLM_TIMEOUT": "timeout_seconds"}
    _llm_flt  = {"NEXUS_LLM_TEMPERATURE": "temperature"}

    for env_key, sub_key in _llm_str.items():
        val = os.environ.get(env_key)
        if val is not None:
            llm_overrides[sub_key] = val
    for env_key, sub_key in _llm_int.items():
        val = os.environ.get(env_key)
        if val is not None:
            try:
                llm_overrides[sub_key] = int(val)
            except ValueError:
                raise ValueError(f"{env_key} must be an integer, got: {val!r}")
    for env_key, sub_key in _llm_flt.items():
        val = os.environ.get(env_key)
        if val is not None:
            try:
                llm_overrides[sub_key] = float(val)
            except ValueError:
                raise ValueError(f"{env_key} must be a float, got: {val!r}")

    if llm_overrides:
        cfg["llm"] = _deep_merge(cfg.get("llm", {}), llm_overrides)

    # Nested logging.*
    log_overrides: dict[str, Any] = {}
    if (v := os.environ.get("NEXUS_LOG_LEVEL")):
        log_overrides["level"] = v
    if (v := os.environ.get("NEXUS_LOG_DIR")):
        log_overrides["dir"] = v
    if log_overrides:
        cfg["logging"] = _deep_merge(cfg.get("logging", {}), log_overrides)

    return cfg


def _resolve_paths(cfg: dict[str, Any], project_root: Path) -> dict[str, Any]:
    """Make relative path values in *cfg* absolute, anchored to *project_root*."""
    cfg = dict(cfg)
    _path_keys = ("vault_root", "inbox_images", "processing_dir", "state_dir", "token_moldura")
    for key in _path_keys:
        if key in cfg:
            p = Path(cfg[key])
            if not p.is_absolute():
                cfg[key] = project_root / p
    return cfg


def _build_app_config(merged: dict[str, Any], project_root: Path) -> AppConfig:
    """Separate known AppConfig fields from extras; return validated AppConfig."""
    known = {
        "project_root", "vault_root", "llm", "logging",
        "batch_size", "inbox_images", "processing_dir", "state_dir",
        "retry_attempts", "retry_delay_seconds", "token_moldura", "quality_threshold",
    }
    data = {k: v for k, v in merged.items() if k in known}
    data["extra"] = {k: v for k, v in merged.items() if k not in known}
    data.setdefault("project_root", project_root)
    return AppConfig.model_validate(data)


# ---------------------------------------------------------------------------
# Singleton cache
# ---------------------------------------------------------------------------

_cache: dict[str, Union[AppConfig, dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_config(
    script_path: Union[str, Path],
    *,
    as_pydantic: bool = False,
    reload: bool = False,
) -> Union[AppConfig, dict[str, Any]]:
    """Return merged configuration for *script_path*.

    Resolution order (later overrides earlier):
      1. Embedded Python defaults (_GLOBAL_DEFAULTS)
      2. .shared/config/global.json
      3. .shared/config/<script_stem>.json
      4. NEXUS_* environment variables

    Args:
        script_path: ``__file__`` of the calling script, used to:
                     (a) auto-detect the project root, and
                     (b) derive the local config filename.
        as_pydantic: When True return a validated ``AppConfig`` instance.
                     When False (default) return a plain dict.
        reload:      Bypass the in-process cache and re-read from disk.

    Returns:
        AppConfig if as_pydantic=True, else dict[str, Any].

    Raises:
        FileNotFoundError: Project root not found.
        ValueError:        Malformed JSON or invalid env-var type.
        pydantic.ValidationError: Config values fail AppConfig constraints.

    Example::

        from shared.config import get_config, AppConfig

        config = get_config(__file__, as_pydantic=True)
        print(config.llm.url)
        print(config.inbox_images)

        # Dict mode (default):
        cfg = get_config(__file__)
        print(cfg["llm"]["model"])
    """
    script_path = Path(script_path).resolve()
    cache_key = f"{script_path}|{'pydantic' if as_pydantic else 'dict'}"

    if not reload and cache_key in _cache:
        return _cache[cache_key]

    project_root = _find_project_root(script_path)
    config_dir   = project_root / _CONFIG_SUBDIR
    script_stem  = script_path.stem  # e.g. "classify_images"

    # --- Merge layers ---
    merged = dict(_GLOBAL_DEFAULTS)
    merged = _deep_merge(merged, _load_json_safe(config_dir / "global.json"))
    merged = _deep_merge(merged, _load_json_safe(config_dir / f"{script_stem}.json"))
    merged = _apply_env_overrides(merged)
    merged = _resolve_paths(merged, project_root)

    if as_pydantic:
        result: Union[AppConfig, dict[str, Any]] = _build_app_config(merged, project_root)
    else:
        merged.setdefault("project_root", str(project_root))
        result = merged

    _cache[cache_key] = result
    return result


def clear_config_cache() -> None:
    """Invalidate the in-process config cache (useful in tests)."""
    _cache.clear()
