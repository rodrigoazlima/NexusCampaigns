# Agent Spec — Token (`10-generate-tokens.ps1` → `10-generate-tokens.py`)

**Trigger:** hourly  
**Input:** classified character images (`portrait`, `body`) in `processed-images.json` not yet in `generated-tokens.json`  
**Output:** `*-token.png` alongside source image in `00-Inbox/images/`

---

## Processing

1. Crop image to square (center crop).
2. Apply circular mask.
3. Composite onto moldura frame (`00-Inbox/tokens/Molduras/moldura_default.png`).
4. Save as `{base}.token.png` in same folder as source.

---

## generated-tokens.json Schema

```json
{
  "{sha256}": {
    "sourcePath": "relative/path",
    "tokenPath": "relative/path",
    "generatedAt": "ISO-8601"
  }
}
```

---

## Constraints

- Cannot modify `02-Library/`
