You are a senior Python engineer specializing in clean configuration management.

**Task:**
Create a robust, production-ready `shared/config.py` module that implements a two-level JSON-based configuration system for a multi-script Python codebase.

**Requirements:**

### Configuration Architecture
- **Level 1: Global Config** → `config/global.json` (always loaded first)
- **Level 2: Local Config** → `config/<script_name>.json` (loaded second, overrides global values)

Both files must contain sensible defaults so the application works even if the JSON files are missing or deleted.

### Core Features the Module Must Have:
1. **Automatic path resolution** based on `__file__` (support scripts in different subdirectories).
2. **Smart merging**: Local config overrides global config.
3. **Default fallback**: If JSON files don't exist, use embedded defaults.
4. **Type safety & validation** (use Pydantic v2 where appropriate).
5. **Path handling**: All paths should be `pathlib.Path` objects and resolved to absolute.
6. **Caching**: Optional singleton pattern so `get_config()` is cheap to call multiple times.
7. **Reload support**: Allow forcing reload.
8. **Environment variable override** support (optional but recommended).
9. **Clear error messages** with helpful suggestions.

### Expected Public API:

```python
from shared.config import get_config, AppConfig

config = get_config(__file__)           # Returns dict or AppConfig instance
llm_url = config.llm.url
batch_size = config.batch_size
inbox_images = config.inbox_images
```

Or Pydantic style:
```python
config = get_config(__file__, as_pydantic=True)
```

### Recommended Project Structure

```
NexusCampaigns/
├── .system/config/
│   ├── global.json
│   └── classify_images.json
├── .agents/
│   ├── vision/
    │   └── classify_images.py
    └── shared/
        └── config.py
```


### Instructions:
- Make `global.json` defaults contain common settings (project_root, vault_root, llm settings, logging, etc.).
- Make local configs able to override anything.
- Include a comprehensive set of default values based on typical agent scripts (LLM, paths, batching, prompts, state directories, etc.).
- Support both dict mode and Pydantic model mode.
- Add docstrings and type hints.
- Make the code clean, well-commented, and maintainable.

---

**Now generate the complete `shared/config.py` file.**

Include:
- The full code with proper imports
- Embedded default configurations (as Python dicts)
- Helper functions
- Main `get_config(script_path: str | Path, as_pydantic: bool = False)` function
- Example usage at the bottom in a comment

Focus on robustness and developer experience.
```

