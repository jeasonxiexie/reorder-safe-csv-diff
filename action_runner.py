#!/usr/bin/env python3
"""Read CSV blobs from Git; never execute code from the compared revisions."""
from __future__ import annotations

import csv
import html
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from dupe_diff import compare

MAX_BYTES = 5 * 1024 * 1024
MAX_FILES = 100
MAX_ROWS = 50000
MAX_CELLS = 1000000
CHANGE_COUNTS = ('modified', 'added', 'removed', 'unresolved_old', 'unresolved_new')


def git(*args, cwd=None):
    return subprocess.run(['git', *args], cwd=cwd, check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def revision(value, cwd):
    # Only hexadecimal commit IDs, not shell fragments, options, or expressions.
    if not re.fullmatch(r'[0-9a-fA-F]{7,64}', value or '') or set(value) == {'0'}:
        raise ValueError('base and head must be existing nonzero hexadecimal commit IDs')
    return git('rev-parse', '--verify', value + '^{commit}', cwd=cwd).decode().strip()


def table(data):
    reader = csv.reader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True)
    headers = next(reader, None)
    if not headers or any(not c for c in headers) or len(headers) != len(set(headers)):
        raise ValueError('CSV headers must be non-empty and unique')
    rows = []
    for cells in reader:
        if len(cells) != len(headers):
            raise ValueError('CSV row width differs from its header')
        rows.append(dict(zip(headers, cells)))
        if len(rows) > MAX_ROWS or len(rows) * len(headers) > MAX_CELLS:
            raise ValueError('CSV row/cell limit exceeded')
    return headers, rows


def blob(commit, path, cwd):
    spec = commit + ':' + path
    size = int(git('cat-file', '-s', spec, cwd=cwd))
    if size > MAX_BYTES:
        raise ValueError('CSV exceeds the 5 MiB per-file limit')
    return git('cat-file', 'blob', spec, cwd=cwd)


def reports(cwd, base, head, keys):
    base, head = revision(base, cwd), revision(head, cwd)
    raw = git('diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z', '--no-renames', base, head,
              '--', '*.csv', cwd=cwd).split(b'\0')
    pairs = [(raw[i].decode(), raw[i+1].decode('utf-8')) for i in range(0, len(raw)-1, 2)]
    if len(pairs) > MAX_FILES:
        raise ValueError('more than 100 changed CSV files; split the change')
    result = []
    for status, path in pairs:
        if status not in ('A', 'D', 'M', 'T'):
            raise ValueError('unsupported Git change status')
        # Disallow symlink CSVs, rather than treating their link targets as data.
        for commit in ([head] if status == 'A' else [base] if status == 'D' else [base, head]):
            mode = git('--literal-pathspecs', 'ls-tree', commit, '--', path, cwd=cwd).split(b' ', 1)[0]
            if mode not in (b'100644', b'100755'):
                raise ValueError('CSV paths must be regular files')
        old = None if status == 'A' else table(blob(base, path, cwd))
        new = None if status == 'D' else table(blob(head, path, cwd))
        cols = (old or new)[0]
        report = compare(old[0] if old else cols, old[1] if old else [],
                         new[0] if new else cols, new[1] if new else [], keys)
        counts = report['counts']
        # Header-only additions/deletions and column-order changes are explicit.
        structural = status in ('A', 'D')
        result.append({'path': path, 'status': status, 'report': report,
                       'content_changed': structural or any(counts[k] for k in CHANGE_COUNTS)})
    return {'base': base, 'head': head, 'files': result,
            'changed_files': sum(f['content_changed'] for f in result)}


def markdown(result):
    lines = ['## Reorder Safe CSV Diff', '',
             '| File | Same rows | Inferred edits | Added | Removed | Unresolved |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for entry in result['files']:
        # Escape untrusted file names; table contains no cell values or headers.
        path = html.escape(entry['path']).replace('|', '&#124;').replace('`', '&#96;')
        path = path.replace('\n', '&#10;').replace('\r', '&#13;')
        c = entry['report']['counts']
        suffix = ' (file added)' if entry['status'] == 'A' else ' (file removed)' if entry['status'] == 'D' else ''
        lines.append(f"| {path}{suffix} | {c['unchanged']} | {c['modified']} | {c['added']} | {c['removed']} | {c['unresolved_old'] + c['unresolved_new']} |")
    if not result['files']:
        lines += ['', 'No changed `.csv` files.']
    lines += ['', f"**{result['changed_files']} file(s) with content changes or unresolved rows.**",
              '', 'Row/column order alone is ignored. Inferred edits are minimum-cost explanations, not proven record identities.',
              'The JSON report includes cell values. It stays in runner temporary storage unless you explicitly upload it.']
    return '\n'.join(lines) + '\n'


def main():
    try:
        keys = [s.strip() for s in os.environ.get('CSV_DIFF_KEY', '').split(',')]
        if not all(keys) or len(keys) != len(set(keys)):
            raise ValueError('key must contain distinct non-empty column names')
        fail = os.environ.get('CSV_DIFF_FAIL', 'false').lower()
        if fail not in ('true', 'false'):
            raise ValueError('fail-on-change must be true or false')
        cwd = os.environ.get('CSV_DIFF_WORKSPACE', os.environ.get('GITHUB_WORKSPACE', '.'))
        result = reports(cwd, os.environ.get('CSV_DIFF_BASE', ''),
                         os.environ.get('CSV_DIFF_HEAD', ''), keys)
        directory = Path(tempfile.mkdtemp(prefix='csv-diff-', dir=os.environ.get('RUNNER_TEMP')))
        output = directory / 'report.json'
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
                f.write(markdown(result))
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
                f.write(f"changed-files={result['changed_files']}\nreport-path={output}\n")
        print(f"Compared {len(result['files'])} CSV file(s); {result['changed_files']} with content changes or unresolved rows.")
        return 1 if fail == 'true' and result['changed_files'] else 0
    except (ValueError, UnicodeError, OSError, csv.Error, subprocess.CalledProcessError):
        # Avoid echoing attacker-controlled CSV contents or Git diagnostics into CI logs.
        print('CSV comparison failed. Check keys, matching headers, UTF-8, regular files, limits, and fetch-depth: 0.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
