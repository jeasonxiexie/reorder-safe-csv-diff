#!/usr/bin/env python3
"""Duplicate-aware CSV snapshot diff. Python 3.9+, standard library only.

Exact row multiplicities are factual; modifications under repeated keys are an
inferred *minimal-edit explanation*, never evidence of stable record identity.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys


def load_table(path: str, delimiter: str = ',') -> tuple[list[str], list[dict[str, str]]]:
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f, delimiter=delimiter, strict=True)
        try:
            headers = next(reader)
        except StopIteration:
            raise ValueError(f'{path}: CSV file is empty')
        if not headers or any(not h for h in headers) or len(set(headers)) != len(headers):
            raise ValueError(f'{path}: headers must be non-empty and unique')
        rows: list[dict[str, str]] = []
        for line, cells in enumerate(reader, start=2):
            if len(cells) != len(headers):
                raise ValueError(f'{path}: row ending near line {reader.line_num} has '
                                 f'{len(cells)} cells; expected {len(headers)}')
            rows.append(dict(zip(headers, cells)))
    return headers, rows


def hungarian(cost: list[list[int]]) -> tuple[list[int], int]:
    """Minimum-cost assignment for a square integer matrix, O(n^3)."""
    n = len(cost)
    if n == 0:
        return [], 0
    if any(len(row) != n for row in cost):
        raise ValueError('cost matrix must be square')
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [10**12] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta, j1 = 10**12, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [-1] * n
    for j in range(1, n + 1):
        assignment[p[j] - 1] = j - 1
    return assignment, sum(cost[i][j] for i, j in enumerate(assignment))


def match_remaining(before: list[tuple[str, ...]], after: list[tuple[str, ...]],
                    columns: list[str], keys: list[str], max_change_cells: int):
    """Find an edit explanation, not a claim that specific records share identity.

    Every inferred pair costs 2 * (# changed cells), up to max_change_cells.
    A deletion or addition costs max_change_cells+1, so allowed pairs cost less
    than delete+add. Exact rows were already cancelled upstream.
    """
    m, n = len(before), len(after)
    N = m + n
    nonkeys = [i for i, name in enumerate(columns) if name not in keys]
    INF = 10**9
    d_cost = max_change_cells + 1
    matrix = []
    for i in range(N):
        line = []
        for j in range(N):
            if i < m and j < n:
                changes = sum(before[i][col] != after[j][col] for col in nonkeys)
                line.append(2 * changes if changes <= max_change_cells else INF)
            elif i < m or j < n:
                line.append(d_cost)
            else:
                line.append(0)
        matrix.append(line)
    assignment, objective = hungarian(matrix)
    used_new = set()
    modifications, removed = [], []
    matched_edges = []
    for i in range(m):
        j = assignment[i]
        if j < n and matrix[i][j] < INF:
            used_new.add(j)
            matched_edges.append((i, j))
            changes = {
                columns[col]: {'before': before[i][col], 'after': after[j][col]}
                for col in nonkeys if before[i][col] != after[j][col]
            }
            modifications.append({'changed_cells': changes, 'pairing': 'inferred_not_proven'})
        else:
            removed.append(dict(zip(columns, before[i])))
    added = [dict(zip(columns, after[j])) for j in range(n) if j not in used_new]
    # Verify whether any *different real-row pairing* has equal optimal cost.
    # Dummy-node permutations alone do not count as genuine alternatives.
    # This only checks mathematical uniqueness under the declared cost model.
    if matched_edges and N <= 16:
        alternatives = False
        for i, j in matched_edges:
            original = matrix[i][j]
            matrix[i][j] = INF
            _, alt_cost = hungarian(matrix)
            matrix[i][j] = original
            if alt_cost == objective:
                alternatives = True
                break
        uniqueness = 'multiple_optima' if alternatives else 'unique_under_scoring_only'
    elif matched_edges:
        uniqueness = 'not_checked_group_too_large'
    else:
        uniqueness = 'not_applicable'
    return modifications, removed, added, objective, uniqueness


def compare(before_columns: list[str], before: list[dict[str, str]],
            after_columns: list[str], after: list[dict[str, str]],
            keys: list[str], max_change_cells=2, max_unmatched_per_key=80) -> dict:
    if set(before_columns) != set(after_columns):
        raise ValueError(f'columns differ: before_only={sorted(set(before_columns)-set(after_columns))}, '
                         f'after_only={sorted(set(after_columns)-set(before_columns))}')
    if not keys or len(set(keys)) != len(keys) or any(k not in before_columns for k in keys):
        raise ValueError('specify one or more existing, distinct --key columns')
    if max_change_cells < 0 or max_unmatched_per_key < 1:
        raise ValueError('invalid limits')
    columns = before_columns[:]
    a, b = defaultdict(Counter), defaultdict(Counter)
    for r in before:
        a[tuple(r[k] for k in keys)][tuple(r[k] for k in columns)] += 1
    for r in after:
        b[tuple(r[k] for k in keys)][tuple(r[k] for k in columns)] += 1
    groups = []
    totals = dict(unchanged=0, modified=0, added=0, removed=0,
                  unresolved_old=0, unresolved_new=0, duplicate_key_groups=0)
    for key in sorted(set(a) | set(b)):
        ca, cb = a[key], b[key]
        count_a, count_b = sum(ca.values()), sum(cb.values())
        duplicate_key = count_a > 1 or count_b > 1
        if duplicate_key:
            totals['duplicate_key_groups'] += 1
        common = ca & cb
        unchanged = sum(common.values())
        ra, rb = ca - common, cb - common
        old_remaining = sorted(ra.elements())
        new_remaining = sorted(rb.elements())
        g = dict(key=dict(zip(keys, key)), duplicate_key=duplicate_key,
                 exact_unchanged=unchanged, modifications=[], added=[], removed=[])
        totals['unchanged'] += unchanged
        if not old_remaining or not new_remaining:
            # No assignment is needed for an entirely one-sided residual.
            g['removed'] = [dict(zip(columns, r)) for r in old_remaining]
            g['added'] = [dict(zip(columns, r)) for r in new_remaining]
            totals['removed'] += len(old_remaining)
            totals['added'] += len(new_remaining)
        elif len(old_remaining) + len(new_remaining) > max_unmatched_per_key:
            g['unresolved'] = {
                'reason': 'too_many_unmatched_rows_for_safe_matching',
                'before': [dict(zip(columns, r)) for r in old_remaining],
                'after': [dict(zip(columns, r)) for r in new_remaining]
            }
            totals['unresolved_old'] += len(old_remaining)
            totals['unresolved_new'] += len(new_remaining)
        elif old_remaining or new_remaining:
            mods, rems, adds, _, uniqueness = match_remaining(old_remaining, new_remaining,
                                                              columns, keys, max_change_cells)
            g['modifications'], g['removed'], g['added'] = mods, rems, adds
            g['minimum_cost_pairing_uniqueness'] = uniqueness
            totals['modified'] += len(mods)
            totals['removed'] += len(rems)
            totals['added'] += len(adds)
        if g['exact_unchanged'] or g['modifications'] or g['removed'] or g['added'] or g.get('unresolved'):
            groups.append(g)
    return {
        'key_columns': keys, 'options': {'max_change_cells': max_change_cells,
                    'max_unmatched_per_key': max_unmatched_per_key},
        'interpretation': 'Exact row multiplicities are verified; inferred modifications are only '
                          'a minimum-cost explanation under the stated scoring rule. Duplicate keys prevent establishing record identity.',
        'counts': totals, 'groups': groups
    }


def print_text(report: dict, verbose: bool):
    c = report['counts']
    print(f"exact unchanged={c['unchanged']} | suggested modified={c['modified']} | "
          f"removed={c['removed']} | added={c['added']} | "
          f"unresolved={c['unresolved_old']} old/{c['unresolved_new']} new")
    print(f"duplicate-key groups={c['duplicate_key_groups']} | "
          'NOTE: paired changes are hypotheses, not proven identities.')
    for group in report['groups']:
        if not verbose and not (group['modifications'] or group['added'] or group['removed'] or group.get('unresolved')):
            continue
        print('\nKEY', json.dumps(group['key'], ensure_ascii=False),
              'exact unchanged', group['exact_unchanged'],
              'duplicate_key', group['duplicate_key'])
        if group.get('minimum_cost_pairing_uniqueness') == 'multiple_optima':
            print('  ! multiple equally optimal pairings: no unique explanation')
        for mod in group['modifications']:
            print('  ~ inferred:', json.dumps(mod['changed_cells'], ensure_ascii=False, sort_keys=True))
        for r in group['removed']:
            print('  -', json.dumps(r, ensure_ascii=False))
        for r in group['added']:
            print('  +', json.dumps(r, ensure_ascii=False))
        if group.get('unresolved'):
            print('  ? too many remaining rows; no pairing guessed')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', help='old UTF-8 CSV')
    parser.add_argument('after', help='new UTF-8 CSV')
    parser.add_argument('--key', required=True, help='comma-separated key columns (may repeat)')
    parser.add_argument('--delimiter', default=',', help='single character or tab')
    parser.add_argument('--max-change-cells', type=int, default=2,
                        help='maximum differing non-key cells for an inferred modification (default 2)')
    parser.add_argument('--max-unmatched-per-key', type=int, default=80,
                        help='limit residual group size before declining to guess')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true', help='include unchanged key groups')
    args = parser.parse_args(argv)
    delim = '\t' if args.delimiter == 'tab' else args.delimiter
    if len(delim) != 1:
        parser.error('--delimiter must be one character or "tab"')
    try:
        cols1, rows1 = load_table(args.before, delim)
        cols2, rows2 = load_table(args.after, delim)
        result = compare(cols1, rows1, cols2, rows2,
                         [x.strip() for x in args.key.split(',')],
                         args.max_change_cells, args.max_unmatched_per_key)
    except (ValueError, OSError, csv.Error) as exc:
        print(f'dupe_diff: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text(result, args.verbose)
    counts = result['counts']
    return 1 if any(counts[k] for k in ('modified','removed','added','unresolved_old','unresolved_new')) else 0


if __name__ == '__main__':
    sys.exit(main())
