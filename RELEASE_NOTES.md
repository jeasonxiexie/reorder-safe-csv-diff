# v0.1.0 — CSV review without row-order noise

First public release of a Python standard-library GitHub Action for CSV snapshot review.

- Ignores row and column reordering while preserving duplicate counts.
- Supports repeated grouping keys and optional composite keys.
- Suggests small edits and records ambiguity instead of claiming stable identity.
- Compares Git revisions without executing code from either snapshot.
- Writes a counts-only workflow summary and a local JSON report.
- Includes an end-to-end hosted demo workflow and synthetic example files.

Start with the README's pull request workflow. This is an early release; please
share small synthetic examples when reporting incorrect or confusing comparisons.
