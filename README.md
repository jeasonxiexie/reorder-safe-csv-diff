# Reorder Safe CSV Diff

Review the CSV content that changed, even when rows move and IDs repeat.

A CSV export gets reordered. Git shows a wall of deleted and added lines.
This action cancels identical rows (including duplicate counts), then suggests
small edits within each key group. It writes a compact table to the workflow
summary. Python standard library only. No service, API key, or network call.

## Example

Four order lines share `order_id=A-100`. Reorder the rows and columns, then change
one quantity from 3 to 4. The included demo reports:

| Same rows | Inferred edits | Added | Removed |
| ---: | ---: | ---: | ---: |
| 3 | 1 | 0 | 0 |

Try the exact files locally:

```sh
python3 dupe_diff.py examples/old.csv examples/new.csv --key order_id
# Exit 1 means content differences; exit 2 means an error.
python3 -m unittest discover -s tests -v
```

## Install in a pull request workflow

Save this as `.github/workflows/csv-review.yml`. Replace `order_id` with your
grouping column; use `order_id,sku` if that better identifies a line.

```yaml
name: CSV review
on: [pull_request]
permissions:
  contents: read
jobs:
  compare:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: jeasonxiexie/reorder-safe-csv-diff@v0.1.0
        with:
          key: order_id
```

Open **Actions → CSV review → run summary** to see the table. The default is a
report, so real changes do not fail your build. Set `fail-on-change: 'true'`
to turn content changes or unresolved comparisons into a failing check.
For reproducible builds, pin this action to the release commit SHA.

## Inputs and outputs

| Input | Default | Meaning |
| --- | --- | --- |
| `key` | required | Comma-separated existing grouping columns; duplicates allowed |
| `base` | PR base SHA / push before SHA | Existing hexadecimal commit ID |
| `head` | PR head SHA / current SHA | Existing hexadecimal commit ID |
| `fail-on-change` | `false` | Fail on content changes or unresolved rows |

Both commits must exist locally; use `fetch-depth: 0`. For manual runs, supply
`base` and `head`. The first push of a new branch may have an all-zero before
SHA; supply an explicit base in that case. Renames are compared as deletion
and addition. Only changed files ending in lowercase `.csv` are inspected.

| Output | Meaning |
| --- | --- |
| `changed-files` | Number of files with content changes or unresolved rows |
| `report-path` | Full JSON report in runner temporary storage |

## What the comparison can tell you

An identical row count is exact snapshot equality. An inferred edit is only a
minimum-cost explanation under a changed-cell scoring rule. **Without a stable
unique ID, the action cannot prove that two rows are the same business entity.**
Small groups are checked for equally good alternative pairings; larger groups
are marked as unchecked. After exact cancellation, groups with more than 80
residual rows are unresolved, except pure additions/deletions. Default matching
permits at most two changed non-key cells. The JSON report records these limits.

Both snapshots must have the same column names. Column order is ignored.
UTF-8/BOM is supported. Empty or duplicate headers, malformed CSV, missing keys,
schema changes, or non-regular files fail visibly rather than returning a clean
comparison. Limits: 100 changed CSV files, 5 MiB, 50,000 rows, and 1 million
cells per file. No normalization of numbers, dates, case, or whitespace.
Linux GitHub-hosted runners with Python 3.9+ are the supported Action environment.

## Data and permissions

The Action reads Git blobs and does not execute code from compared revisions.
It needs `contents: read` only. It does not post comments or contact a service.
The summary contains file names and counts, with no CSV cell values.
**The JSON report contains source cell values.** It stays in runner temporary
storage unless you explicitly upload it. Treat it like the original CSV.
Use `pull_request`, keep credentials disabled in checkout, and avoid executing
untrusted pull request code in privileged workflows.

## Why this exists

Some comparisons require unique keys; others pair repeated IDs by occurrence.
This project is for the narrower case where repeated keys and row reordering
are normal. Multiset cancellation and minimum-cost assignment are established
methods; this is an engineering tool, not a claim of a new algorithm.

Built with AI assistance. The test suite covers brute-force assignment checks,
reordering, duplicate multiplicities, ambiguous matches, real Git snapshots,
added/deleted files, malformed input, and safe summaries. Real-world usefulness
and demand are still being evaluated.

If you try it, [open an issue](https://github.com/jeasonxiexie/reorder-safe-csv-diff/issues)
with a tiny synthetic example, your key columns, and the expected result.
Please keep real customer/order data private. MIT licensed.
