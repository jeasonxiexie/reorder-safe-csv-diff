#!/usr/bin/env python3
import itertools
import random
import unittest
from dupe_diff import compare, hungarian

COLUMNS = ['group','item','qty','state']

def rows(data):
    return [dict(zip(COLUMNS, r)) for r in data]

def cmp(a, b, cols_a=COLUMNS, cols_b=COLUMNS, **opts):
    return compare(cols_a, a, cols_b, b, ['group'], **opts)

class DiffTests(unittest.TestCase):
    def test_reorder_no_change(self):
        before = rows([('A','apple','2','ok'),('A','banana','3','ok'),('A','pear','1','ok')])
        for perm in itertools.permutations(before):
            out = cmp(before, list(perm))['counts']
            self.assertEqual((out['unchanged'],out['modified'],out['added'],out['removed']), (3,0,0,0))
    def test_one_edit_with_reordering_and_duplicate_keys(self):
        before = rows([('A','apple','2','ok'),('A','banana','3','ok'),('A','pear','1','ok')])
        after = rows([('A','pear','1','ok'),('A','banana','4','ok'),('A','apple','2','ok')])
        c = cmp(before,after)['counts']
        self.assertEqual((c['unchanged'],c['modified'],c['added'],c['removed']), (2,1,0,0))
    def test_repeated_exact_rows_counted(self):
        before = rows([('A','apple','2','ok')] * 3)
        after = rows([('A','apple','2','ok')] * 2)
        c = cmp(before,after)['counts']
        self.assertEqual((c['unchanged'],c['removed'],c['modified']), (2,1,0))
    def test_changes_and_diffs_on_multiple_keys(self):
        before = rows([('A','apple','2','ok'),('B','banana','3','ok')])
        after = rows([('A','apple','4','ok'),('C','banana','3','ok')])
        c = cmp(before,after)['counts']
        self.assertEqual((c['unchanged'],c['modified'],c['added'],c['removed']), (0,1,1,1))
    def test_column_reorder(self):
        before = rows([('A','apple','2','ok')])
        after = [dict(state='ok', qty='3', item='apple', group='A')]
        c = cmp(before,after,cols_b=list(reversed(COLUMNS)))['counts']
        self.assertEqual(c['modified'], 1)
    def test_too_many_uncertain_records_declined(self):
        before = rows([('A',str(i),'2','ok') for i in range(6)])
        after = rows([('A',str(i),'4','ok') for i in range(6)])
        c = cmp(before,after,max_unmatched_per_key=5)['counts']
        self.assertEqual((c['unresolved_old'],c['unresolved_new'],c['modified']), (6,6,0))
    def test_disallowed_multi_column_changes(self):
        before = rows([('A','apple','2','ok')])
        after = rows([('A','pear','4','done')])
        c = cmp(before,after,max_change_cells=2)['counts']
        self.assertEqual((c['modified'],c['added'],c['removed']), (0,1,1))
    def test_permutation_invariance(self):
        for seed in range(100):
            r = random.Random(seed)
            a = rows([('A',str(i),'3','ok') for i in range(8)])
            b = rows([('A',str(i),'3','ok') for i in range(8)])
            b[3]['qty'] = '4'
            r.shuffle(a); r.shuffle(b)
            result = cmp(a,b)['counts']
            self.assertEqual((result['unchanged'],result['modified'],result['added'],result['removed']), (7,1,0,0))
    def test_hungarian_matches_brute_force(self):
        for seed in range(120):
            rng = random.Random(seed)
            n = rng.randrange(1,7)
            m = [[rng.randrange(0,30) for _ in range(n)] for _ in range(n)]
            assignment, cost = hungarian(m)
            brute = min(sum(m[i][p[i]] for i in range(n)) for p in itertools.permutations(range(n)))
            self.assertEqual(cost, brute)
            self.assertEqual(len(set(assignment)),n)
    def test_ambiguous_pairing_is_explicit(self):
        before = rows([('A','apple','1','ok'),('A','orange','2','ok')])
        after  = rows([('A','apple','2','ok'),('A','orange','1','ok')])
        result = cmp(before,after)
        self.assertEqual(result['counts']['modified'],2)
        self.assertEqual(result['groups'][0]['minimum_cost_pairing_uniqueness'], 'multiple_optima')
    def test_invalid_columns(self):
        with self.assertRaisesRegex(ValueError,'columns differ'):
            cmp([], [], cols_b=['group','item','qty','other'])

if __name__=='__main__':
    unittest.main(verbosity=2)
