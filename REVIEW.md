# Project Review: MusicDeduplicator

## Summary

A single-file Python utility (`musicorganise.py`, 517 lines) that identifies and handles duplicate audio files using metadata fuzzy-matching and AcoustID audio fingerprinting. The tool has a solid core concept and reasonable feature set, but has several bugs, structural issues, and missing infrastructure that should be addressed before relying on it for destructive operations (move/delete).

---

## Critical Issues (Bugs & Data Loss Risks)

### 1. Intra-directory duplicates checked on already-deleted directories
**File:** `musicorganise.py:360`

After inter-directory duplicates are deleted/moved (step 4), the code iterates over *all* directories in the duplicate set for intra-directory checking (step 5) — including directories that were just deleted. The `os.path.exists()` guard at line 361 catches this, but it means the "kept" directory never gets intra-directory deduplication if it was the only one that survived, while the deleted ones are skipped. More importantly, the logic walks directories that may have been partially moved, leading to inconsistent state.

### 2. `summary_stats` referenced before definition
**File:** `musicorganise.py:178-179`

`get_file_metadata()` writes to `summary_stats['files_by_format']` at line 178, but `summary_stats` is defined at line 292. If `get_file_metadata()` is called before module-level execution reaches line 292 (e.g., through `validate_cached_data` → `get_file_metadata` during import-time config prompts or via multiprocessing), this will raise a `NameError`. In practice, normal flow avoids this because config prompts happen first and `find_duplicates` runs later, but this ordering dependency is fragile.

### 3. Module-level `input()` calls block non-interactive use
**File:** `musicorganise.py:41-66`

Configuration prompts (`input()`) execute at module import time, not inside `main()`. This makes the script impossible to use in automated pipelines, cron jobs, or test harnesses without a pre-existing `config.json`. It also means importing the module (e.g., for testing) triggers interactive prompts.

### 4. Multiprocessing is advertised but not used
**File:** `musicorganise.py:268, 503`

`find_duplicates()` accepts `use_multiprocessing` parameter, and `--no-multiprocessing` is a CLI flag, but the function body never uses multiprocessing. The `Pool`, `cpu_count`, and `get_context` imports (line 12) are dead code. The README prominently advertises multiprocessing support.

### 5. Batch processing is not implemented
**File:** `musicorganise.py:38`

`BATCH_SIZE` is loaded from config and prompted from the user, but it is never used anywhere in the code. Files are processed one at a time sequentially.

### 6. `tqdm` progress bars are not used
**File:** `musicorganise.py:15`

`tqdm` is imported but never used in the code. The README advertises "real-time progress bars."

---

## Moderate Issues (Code Quality & Correctness)

### 7. Overly broad exception handling
**File:** `musicorganise.py:183, 229`

```python
except (FileNotFoundError, Exception) as e:
```

`Exception` is a superclass of `FileNotFoundError`, so listing both is redundant. More importantly, catching bare `Exception` masks programming errors (e.g., `TypeError`, `KeyError`) that should propagate. This makes debugging difficult.

### 8. Inconsistent indentation
**File:** `musicorganise.py:206, 225-226, 433-434, 443-444`

Several blocks use 2-space indentation instead of the standard 4-space Python convention, mixed with 4-space elsewhere. This suggests copy-paste from different sources and makes the code harder to maintain.

### 9. SQLite connection per operation (no connection pooling)
**File:** `musicorganise.py:103, 116, 131, 141`

Each cache operation opens a new SQLite connection. When processing thousands of files, this creates significant overhead. A single connection (or connection pool) reused across operations would be substantially more efficient.

### 10. `fuzzy_match()` function is unused
**File:** `musicorganise.py:95-100`

The standalone `fuzzy_match()` function is defined but never called. Fuzzy matching *is* used inline in `get_acoustid()` (lines 214-216), but the dedicated function is dead code.

### 11. `gc` module imported but never used
**File:** `musicorganise.py:11`

The garbage collector module is imported but `gc.collect()` or similar is never called.

### 12. `threading` module imported but never used
**File:** `musicorganise.py:13`

### 13. No validation of `--path` argument
**File:** `musicorganise.py:480`

The script doesn't verify that `args.path` exists or is a directory before proceeding. A typo in the path silently produces "No duplicates found."

### 14. Cache file paths are relative, not configurable
**File:** `musicorganise.py:21-22`

`CONFIG_FILE` and `CACHE_DB` are relative paths, so they're created in whatever the current working directory is. Running the script from different directories creates separate, potentially conflicting cache files.

### 15. `float` comparison for mtime cache validation
**File:** `musicorganise.py:150`

```python
if cached_mtime == file_mtime
```

Floating-point equality comparison for file modification times can be unreliable across filesystems. A small epsilon tolerance or integer-based comparison would be safer.

---

## Security & Safety Concerns

### 16. API key stored in plaintext
**File:** `musicorganise.py:43-44`

The AcoustID API key is stored unencrypted in `config.json`. While this is a low-sensitivity key, it's a poor practice. At minimum, `config.json` should be added to `.gitignore`.

### 17. No `.gitignore` file
The repository has no `.gitignore`, risking accidental commits of:
- `config.json` (contains API key)
- `file_cache.db` (SQLite cache)
- `music_deduplicate.log`
- `__pycache__/`
- `.pyc` files

### 18. No confirmation prompt for destructive actions
**File:** `musicorganise.py:353-356`

The `delete` action with `--dry-run` omitted will immediately and permanently delete directories. There's no "Are you sure?" confirmation step, making accidental data loss easy.

---

## Missing Infrastructure

### 19. No `requirements.txt` or `pyproject.toml`
Dependencies must be discovered by reading the README or source code. A `requirements.txt` or modern `pyproject.toml` should list all dependencies with version pins.

### 20. No automated tests
There are zero tests. For a tool that performs destructive file operations, this is a significant risk. Key areas needing tests:
- Duplicate detection logic
- Cache validation
- Metadata extraction
- Directory hash calculation
- Move/delete operations (using temp directories)

### 21. No CI/CD pipeline
No GitHub Actions, pre-commit hooks, or linting configuration.

### 22. No type hints
The codebase uses no type annotations, making it harder to reason about function contracts and catch errors statically.

---

## README Issues

### 23. README is duplicated
**File:** `README.md:34-66`

The entire header, overview, features, and installation sections are duplicated verbatim starting at line 34. The file contains two copies of the same content.

### 24. Incorrect script filename in README
**File:** `README.md:126-127`

The README references `music_deduplicate.py` but the actual file is `musicorganise.py`.

### 25. README references `file_cache.json`
**File:** `README.md:193`

The README says caching goes to `file_cache.json`, but the code uses SQLite (`file_cache.db`). This is outdated documentation from a previous implementation.

### 26. `ratelimit` package missing from README install instructions
**File:** `README.md:32, 65`

The `ratelimit` package (used for `@sleep_and_retry` and `@limits` decorators) is not listed in the `pip install` command.

### 27. README advertises features that don't work
- "Multiprocessing Support" — not implemented
- "Batch Processing" — not implemented
- "Progress Bar" — not implemented

---

## Recommendations (Priority Order)

1. **Fix the README** — remove duplication, correct filename, update cache reference, list all dependencies, remove claims about unimplemented features.
2. **Add `.gitignore`** — exclude config.json, cache, logs, and Python artifacts.
3. **Add `requirements.txt`** — pin all dependencies.
4. **Move `input()` prompts inside `main()`** — allow non-interactive use and testability.
5. **Remove dead imports and unused functions** — `gc`, `threading`, `Pool`/`cpu_count`/`get_context`, `fuzzy_match()`, `tqdm`.
6. **Add path validation** — verify `--path` exists before processing.
7. **Add confirmation prompt** for delete action (when not using `--dry-run`).
8. **Narrow exception handling** — catch specific exceptions instead of bare `Exception`.
9. **Reuse SQLite connections** — pass a connection object rather than opening per-query.
10. **Implement multiprocessing, batching, and progress bars** — or remove the claims and CLI flags.
11. **Add basic tests** — at least for duplicate detection and cache logic.
12. **Add type hints** — improve maintainability and enable mypy/pyright checking.

---

## What Works Well

- The core duplicate detection algorithm (directory hashing via AcoustID + metadata fallback) is a sound approach.
- SQLite caching with mtime validation is a good performance optimization.
- The FLAC-priority logic for choosing which duplicate to keep is sensible.
- Rate limiting on AcoustID API calls is properly implemented.
- The `--dry-run` flag is an important safety feature.
- Error handling around file I/O operations (despite being too broad) at least prevents crashes.
- The CLI interface with argparse is well-structured.
