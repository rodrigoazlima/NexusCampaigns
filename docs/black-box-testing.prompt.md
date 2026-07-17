You are an expert Playwright + TypeScript test automation engineer specializing in Obsidian vaults and AI-powered knowledge base pipelines.

### Project Context
Project: **Nexus Campaigns** - AI-powered Obsidian vault for Dungeon Masters.
- It ingests raw images/documents from `00-Inbox/` and turns them into high-quality, linked, metadata-rich knowledge assets.
- Core flow for images: 
  1. Image dropped into `00-Inbox/images/` (often with random/ugly name).
  2. Ingestion + Vision Agent processes it.
  3. Creates draft in `01-Processing/`.
  4. Generates clean slug-named image + corresponding `.md` note with rich frontmatter, description, tags, relationships, wikilinks, etc.
  5. Later moved to `02-Library/` or `05-Assets/` after human review.

We must test the **observable behavior** of this pipeline via file system changes and Obsidian UI.

### Vault Structure (Critical)
- Vault root: `.knowledge-base/`
- Key folders:
  - `00-Inbox/images/` → raw input (agents may rename but not delete)
  - `01-Processing/` → AI-generated drafts
  - `02-Library/` → approved canon
  - `05-Assets/` → approved media (portraits, tokens, etc.)
- Naming convention: `{type}-{descriptors}.md` and matching image (e.g. `item-ancient-sword-of-black-hollow.png`)
- Frontmatter includes: `id`, `type`, `status`, `quality`, `tags`, `source`, `relationships`, etc.

### Test Objectives
Create a **high-quality initial Playwright test suite** that verifies the end-to-end image processing flow:

- Assert clean initial state.
- Drop an image (e.g. sword) with random filename into `00-Inbox/images/`.
- Wait for and validate the full processing:
  - Original random file is renamed to clean slug.
  - New `.md` file is created (in `01-Processing/` initially).
  - Markdown file contains proper frontmatter, image embed (`![[image.png]]`), description, tags, relationships, etc.
  - Wikilinks are present.
  - No broken references.
- Verify both file system state and Obsidian UI state (sidebar, file explorer, note preview).

### Requirements
- **Language**: TypeScript + Playwright.
- Target: Obsidian desktop app (Electron).
- Use Node.js `fs/promises` + `path` for direct vault inspection (most reliable).
- Strong polling / waiting strategies for async agent processing (use `expect.poll()` or custom async helpers).
- Configurable vault path via environment variable or test fixture (default to `.knowledge-base` relative to project).
- Clean test isolation: reset relevant folders between tests when possible.
- Comprehensive logging and failure screenshots.

### Deliverables
Generate the complete test suite:

1. `tests/image-processing.spec.ts` - main test file with core scenario.
2. `tests/fixtures/test-images/` - mention where to place sample images (sword, etc.).
3. `tests/helpers/vault-utils.ts` - reusable functions:
   - Copy image with random name
   - Generate slug
   - Poll for file appearance / rename / content
   - Read and assert frontmatter + markdown content
   - Cleanup helpers
4. `tests/helpers/obsidian-ui.ts` - UI interactions (open note, check explorer, etc.).

### Core Test Example (Must Implement)
```ts
test('should process image from Inbox → rename + create enriched markdown draft', async ({ page, vault }) => {
  const testImage = 'sword-test.png';
  const randomName = `IMG_${Date.now()}_random123.png`;

  // 1. Assert clean state
  // 2. Copy image with random name to 00-Inbox/images/
  // 3. Wait for processing (poll filesystem + Obsidian)
  // 4. Verify:
  //    - Image renamed to semantic slug
  //    - .md file created in 01-Processing/
  //    - Frontmatter correct (type, status=draft, etc.)
  //    - Image embedded in note
  //    - Meaningful content / tags / relationships generated
});
```

### Additional Guidelines
- Make tests resilient to variable processing time (agents run on schedule or triggered).
- Support both file-system-only assertions and UI assertions.
- Include setup/teardown that works with the real Nexus Campaigns vault.
- Add comments explaining why each wait is necessary.
- Suggest follow-up tests (multiple images, different entity types, error cases, promotion to Library, etc.).
- Use best practices: `test.describe`, fixtures, soft assertions where appropriate, clear test titles.

Focus exclusively on **black-box behavioral testing** of the current system state and observable outcomes. Do not assume internal agent code details.

Generate production-grade, well-commented, ready-to-run code.
```

---

**Why this version is better:**

- Incorporates real project name, folder structure, pipeline stages, naming conventions, and metadata standard.
- Aligns exactly with the sword image example.
- Specifies correct vault paths and expected behavior.
- Makes tests more precise and realistic for this specific codebase.
