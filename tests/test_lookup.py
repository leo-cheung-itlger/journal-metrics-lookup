"""Synthetic fixtures only; no third-party dataset is redistributed."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'scripts/journal_metrics.py'


class LookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('journal_metrics_test', SCRIPT)
        cls.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.m)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.jcr = [dict(Journal='Example & Research', ISSN='0022-3417', EISSN='1096-9896',
                         **{'IF(2025)': '5.4', 'Category_1': 'BIOLOGY',
                            'IF Quartile(2025)_1': 'Q1', 'IF Rank(2025)_1': '2/100',
                            'Category_2': 'MEDICINE', 'IF Quartile(2025)_2': 'Q2',
                            'IF Rank(2025)_2': '30/100'})]
        self.cas = [dict(Journal='EXAMPLE AND RESEARCH', **{'年份': '2025',
                         'ISSN/EISSN': '0022-3417/1096-9896', '大类': '医学',
                         '大类分区': '2 [4/100]', '小类1': '病理学', '小类1分区': '1 [2/20]',
                         '小类2': '肿瘤学', '小类2分区': '2 [4/20]'})]
        self.write_data()

    def write_data(self):
        files = {}
        for kind, rows in [('jcr', self.jcr), ('cas', self.cas)]:
            path = self.root / (kind + '.csv')
            with path.open('w', encoding='utf-8-sig', newline='') as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            files[kind] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'year': 2025, 'rows': len(rows), 'source_url': 'https://example.invalid/fixture'}
        (self.root / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'commit': 'fixture',
            'files': files, 'retrieved_at': '2026-10-08T00:00:00+00:00',
            'source_type': 'synthetic_test_fixture', 'readme_claim': None}), encoding='utf-8')

    def test_name_and_both_issn_forms_preserve_all_categories(self):
        db = self.m.Database(self.root)
        for query in [dict(name=' example and research '), dict(name='The Example &amp; Research'), dict(issns=['00223417']),
                      dict(issns=['1096-9896'])]:
            result = db.lookup(**query)
            self.assertEqual(result['status'], 'MATCHED')
            self.assertEqual(result['jif']['value'], 5.4)
            self.assertEqual(result['jif']['metric_year'], 2025)
            self.assertEqual(len(result['jcr']['categories']), 2)
            self.assertEqual(len(result['cas']['minor_categories']), 2)
            self.assertFalse(result['official_verification']['verified'])
            self.assertEqual(result['official_verification']['status'], 'NOT_VERIFIED')

    def test_doi_resolution_uses_identifier_even_when_title_changed(self):
        seen = []
        def resolver(doi):
            seen.append(doi)
            return {'doi': doi, 'journal_names': ['Former Journal Name'],
                    'issns': ['1096-9896'], 'source_url': 'https://example.invalid/doi'}
        result = self.m.Database(self.root).lookup(doi='https://doi.org/10.1234/test', resolver=resolver)
        self.assertEqual(seen, ['10.1234/test'])
        self.assertEqual(result['match_basis']['jcr'], 'ISSN')
        self.assertEqual(result['journal']['name'], 'Example & Research')

    def test_missing_invalid_and_identifier_mismatch_do_not_guess(self):
        db = self.m.Database(self.root)
        for query in [dict(name='No Such Journal'), dict(name='Example'),
                      dict(issns=['1234-5678']),
                      dict(name='Example & Research', issns=['2041-4889'])]:
            result = db.lookup(**query)
            self.assertEqual(result['status'], 'NOT_VERIFIED')
            self.assertIsNone(result['jif']['value'])

    def test_same_name_different_identifiers_is_ambiguous(self):
        second = dict(self.jcr[0], ISSN='2041-4889', EISSN='2041-4889')
        self.jcr.append(second)
        self.write_data()
        db = self.m.Database(self.root)
        result = db.lookup(name='Example and Research')
        self.assertEqual(result['status'], 'NOT_VERIFIED')
        self.assertEqual(result['reason'], 'AMBIGUOUS')
        self.assertEqual(len(result['candidates']['jcr']), 2)
        result = db.lookup(name='Example and Research', issns=['0022-3417'])
        self.assertEqual(result['status'], 'MATCHED')

    def test_conflicting_identifiers_are_ambiguous(self):
        self.jcr.append(dict(self.jcr[0], Journal='Different', ISSN='2041-4889', EISSN='2041-4889'))
        self.write_data()
        result = self.m.Database(self.root).lookup(issns=['0022-3417', '2041-4889'])
        self.assertEqual(result['status'], 'NOT_VERIFIED')
        self.assertEqual(result['reason'], 'AMBIGUOUS')

    def test_cas_only_keeps_jif_unverified(self):
        self.jcr[0]['ISSN'] = '2041-4889'
        self.jcr[0]['EISSN'] = '2041-4889'
        self.jcr[0]['Journal'] = 'Different'
        self.write_data()
        result = self.m.Database(self.root).lookup(issns=['1096-9896'])
        self.assertEqual(result['cas']['status'], 'FOUND_THIRD_PARTY')
        self.assertEqual(result['jif']['status'], 'NOT_VERIFIED')
        self.assertIsNone(result['jif']['value'])

    def test_missing_and_non_numeric_jif_preserve_raw_without_zero(self):
        for raw in ['', 'N/A', '<0.1']:
            self.jcr[0]['IF(2025)'] = raw
            self.write_data()
            result = self.m.Database(self.root).lookup(issns=['1096-9896'])
            self.assertIsNone(result['jif']['value'])
            self.assertEqual(result['jif']['raw'], raw)

    def test_schema_year_is_from_content_and_disagreement_rejected(self):
        info = self.m.inspect_csv('jcr', (self.root / 'jcr.csv').read_bytes())
        self.assertEqual(info['year'], 2025)
        self.cas[0]['年份'] = '2024'
        self.write_data()
        with self.assertRaisesRegex(ValueError, 'year'):
            self.m.Database(self.root)

    def test_corrupt_data_and_path_escape_rejected(self):
        (self.root / 'jcr.csv').write_text('corrupt', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.m.Database(self.root)
        manifest = json.loads((self.root / 'manifest.json').read_text())
        manifest['files']['jcr']['path'] = '../outside.csv'
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.m.Database(self.root)

    def test_doi_failure_is_structured_and_does_not_guess(self):
        def failed(doi):
            raise OSError('offline')
        result = self.m.Database(self.root).lookup(doi='10.1234/test', resolver=failed)
        self.assertEqual(result['status'], 'NOT_VERIFIED')
        self.assertEqual(result['reason'], 'DOI_RESOLUTION_FAILED')

    def test_resolved_doi_without_metrics_keeps_known_journal_identity(self):
        def resolver(doi):
            return {'doi': doi, 'journal_names': ['Missing &amp; Journal'], 'issns': ['1949-2553'],
                    'issn_types': [{'type': 'electronic', 'value': '1949-2553'}],
                    'source_url': 'https://example.invalid/doi'}
        result = self.m.Database(self.root).lookup(doi='10.1234/missing', resolver=resolver)
        self.assertEqual(result['status'], 'NOT_VERIFIED')
        self.assertEqual(result['journal']['name'], 'Missing & Journal')
        self.assertEqual(result['journal']['eissn'], '1949-2553')
        self.assertEqual(result['journal']['identity_source'], 'Crossref')
        self.assertIsNone(result['jif']['value'])

    def test_cas_name_variant_bridges_jcr_by_identifier(self):
        self.cas[0]['Journal'] = 'Former Example Name'
        self.write_data()
        result = self.m.Database(self.root).lookup(name='Former Example Name')
        self.assertEqual(result['jif']['value'], 5.4)
        self.assertEqual(result['match_basis']['jcr'], 'ISSN')

    def test_update_validates_content_and_preserves_old_snapshot_on_failure(self):
        old = (self.root / 'manifest.json').read_bytes()
        commit = 'a' * 40
        tree = {'sha': commit, 'tree': [
            {'path': 'public/JCR2025-UTF8.csv'}, {'path': 'public/FQBJCR2025-UTF8.csv'}]}
        def getter(url):
            if '/git/trees/' in url:
                return json.dumps(tree).encode()
            if url.endswith('README.md'):
                return 'JCR 2025 版（2026 年 6 月 17 日发布）'.encode()
            return (self.root / ('cas.csv' if 'FQBJCR' in url else 'jcr.csv')).read_bytes()
        manifest = self.m.update_database(self.root / 'updated', getter=getter)
        self.assertEqual(manifest['files']['jcr']['year'], 2025)
        self.assertEqual(manifest['files']['cas']['year'], 2025)
        self.assertFalse(manifest['official_verified'])
        self.assertEqual(self.m.Database(self.root / 'updated').lookup(issns=['1096-9896'])['status'], 'MATCHED')
        tree['tree'][0]['path'] = 'public/JCR2026-UTF8.csv'
        with self.assertRaisesRegex(ValueError, 'year'):
            self.m.update_database(self.root, getter=getter)
        self.assertEqual((self.root / 'manifest.json').read_bytes(), old)

    def test_truncated_tree_does_not_publish_snapshot(self):
        old = (self.root / 'manifest.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'truncated'):
            self.m.update_database(self.root, getter=lambda url: json.dumps(
                {'sha': 'b' * 40, 'truncated': True}).encode())
        self.assertEqual((self.root / 'manifest.json').read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
