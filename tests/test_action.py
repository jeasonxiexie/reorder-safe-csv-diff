import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from action_runner import main, markdown, reports, revision, table
from dupe_diff import compare


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerows(rows)
    return stream.getvalue().encode()


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.DEVNULL).decode().strip()

    def write(self, path, rows):
        dest = self.repo / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(csv_bytes(rows))

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'snapshot', '--allow-empty')
        return self.git('rev-parse', 'HEAD')

    def snapshots(self, old, new, path='orders.csv'):
        self.write(path, old)
        base = self.commit()
        self.write(path, new)
        return base, self.commit()

    def test_real_git_reorder_and_one_edit(self):
        base, head = self.snapshots([['id','item','qty'],['A','tea','1'],['A','coffee','2']],
                                    [['qty','item','id'],['3','coffee','A'],['1','tea','A']])
        r = reports(self.repo, base, head, ['id'])
        self.assertEqual(r['changed_files'], 1)
        self.assertEqual(r['files'][0]['report']['counts']['modified'], 1)
        self.assertEqual(r['files'][0]['report']['counts']['unchanged'], 1)

    def test_real_git_reorder_is_not_a_content_change(self):
        base, head = self.snapshots([['id','n'],['A','1'],['A','2']], [['n','id'],['2','A'],['1','A']])
        self.assertEqual(reports(self.repo, base, head, ['id'])['changed_files'], 0)

    def test_large_file_added_and_removed_are_counted(self):
        base = self.commit()
        self.write('new.csv', [['id','n']] + [['A', str(i)] for i in range(100)])
        head = self.commit()
        self.assertEqual(reports(self.repo, base, head, ['id'])['files'][0]['report']['counts']['added'],100)
        (self.repo/'new.csv').unlink()
        deleted = self.commit()
        self.assertEqual(reports(self.repo, head, deleted, ['id'])['files'][0]['report']['counts']['removed'],100)

    def test_no_csv_changes(self):
        (self.repo/'notes.txt').write_text('one')
        base=self.commit()
        (self.repo/'notes.txt').write_text('two')
        self.assertEqual(reports(self.repo,base,self.commit(),['id'])['files'],[])

    def test_header_only_file_added_is_a_change(self):
        base=self.commit()
        self.write('empty.csv',[['id','qty']])
        self.assertEqual(reports(self.repo,base,self.commit(),['id'])['changed_files'],1)

    def test_missing_key_is_error(self):
        base, head=self.snapshots([['id','qty'],['A','1']],[['id','qty'],['A','2']])
        with self.assertRaises(ValueError):
            reports(self.repo,base,head,['order_id'])

    def test_schema_change_is_error(self):
        base, head=self.snapshots([['id','qty'],['A','1']],[['id','amount'],['A','2']])
        with self.assertRaises(ValueError):
            reports(self.repo,base,head,['id'])

    def test_symlink_csv_is_rejected(self):
        base=self.commit()
        (self.repo/'link.csv').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            reports(self.repo,base,self.commit(),['id'])

    def test_revision_injection_is_rejected(self):
        for value in ('--help','HEAD','0'*40,'abc; echo secret','abc\nabc'):
            with self.assertRaises(ValueError):
                revision(value,self.repo)

    def test_summary_escapes_filename_and_contains_no_cell_values(self):
        path='a|<img>\n`x.csv'
        base,head=self.snapshots([['id','qty'],['PRIVATE_ID','1']],
                                 [['id','qty'],['PRIVATE_ID','SECRET_VALUE']],path)
        rendered=markdown(reports(self.repo,base,head,['id']))
        self.assertNotIn('PRIVATE_ID',rendered)
        self.assertNotIn('SECRET_VALUE',rendered)
        self.assertIn('&lt;img&gt;',rendered)
        self.assertIn('&#124;',rendered)
        self.assertIn('&#10;',rendered)

    def test_cli_outputs_fail_flag_and_report(self):
        base, head=self.snapshots([['id','qty'],['A','1']],[['id','qty'],['A','2']])
        out=self.repo/'output.txt'; summary=self.repo/'summary.md'
        env={'CSV_DIFF_WORKSPACE':str(self.repo),'CSV_DIFF_KEY':'id','CSV_DIFF_BASE':base,
             'CSV_DIFF_HEAD':head,'CSV_DIFF_FAIL':'true','GITHUB_OUTPUT':str(out),
             'GITHUB_STEP_SUMMARY':str(summary),'RUNNER_TEMP':str(self.repo)}
        with patch.dict(os.environ,env):
            self.assertEqual(main(),1)
        values=dict(line.split('=',1) for line in out.read_text().splitlines())
        self.assertEqual(values['changed-files'],'1')
        self.assertEqual(json.loads(Path(values['report-path']).read_text())['changed_files'],1)
        self.assertIn('Inferred edits',summary.read_text())
        with patch.dict(os.environ,{**env,'CSV_DIFF_FAIL':'false'}):
            self.assertEqual(main(),0)

    def test_malformed_csv_rejected(self):
        for data in (b'',b'id,id\nA,B\n',b'id,qty\nA\n',b'id\n"unfinished',b'id\n\xff\n'):
            with self.assertRaises((ValueError,csv.Error,UnicodeError)):
                table(data)

    def test_composite_key(self):
        base, head=self.snapshots([['id','item','qty'],['A','tea','1']],
                                  [['id','item','qty'],['A','coffee','1']])
        c=reports(self.repo,base,head,['id','item'])['files'][0]['report']['counts']
        self.assertEqual((c['modified'],c['added'],c['removed']),(0,1,1))


if __name__=='__main__':
    unittest.main()
