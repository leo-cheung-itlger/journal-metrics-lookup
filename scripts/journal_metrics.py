"""Public ShowJCR snapshot lookup. Python standard library only."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

REPOSITORY = 'https://github.com/hitfyd/ShowJCR'
API = 'https://api.github.com/repos/hitfyd/ShowJCR'
UNVERIFIED = 'NOT_VERIFIED'
FOUND = 'FOUND_THIRD_PARTY'


def default_data_dir():
    override = os.environ.get('JOURNAL_METRICS_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    base = Path(os.environ['LOCALAPPDATA']) if os.environ.get('LOCALAPPDATA') else Path.home() / '.cache'
    return base / 'journal-metrics-lookup'


def fetch(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': 'journal-metrics-lookup/1.0 (public research metadata)',
        'Accept': 'application/json, text/plain, */*'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def normalized_name(value):
    value = unicodedata.normalize('NFKC', html.unescape(value or '')).casefold().replace('&', ' and ')
    value = ' '.join(re.sub(r'[^\w\s]', ' ', value).split())
    return re.sub(r'^the\s+', '', value)


def normalize_issn(value):
    value = re.sub(r'[\s-]', '', str(value)).upper()
    if not re.fullmatch(r'\d{7}[\dX]', value):
        return None
    total = sum(int(d) * weight for d, weight in zip(value[:7], range(8, 1, -1)))
    check = (11 - total % 11) % 11
    if value[-1] != ('X' if check == 10 else str(check)):
        return None
    return value[:4] + '-' + value[4:]


def row_issns(row):
    text = '/'.join(row.get(key, '') for key in ('ISSN', 'EISSN', 'ISSN/EISSN'))
    return sorted({valid for raw in re.findall(r'\d{4}-?\d{3}[\dXx]', text)
                   if (valid := normalize_issn(raw))})


def parse_csv(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    rows = list(reader)
    if not rows or not reader.fieldnames or any(None in row for row in rows):
        raise ValueError('empty or malformed CSV')
    return reader.fieldnames, rows


def inspect_csv(kind, raw):
    headers, rows = parse_csv(raw)
    required = {'Journal', 'ISSN', 'EISSN'} if kind == 'jcr' else {
        'Journal', 'ISSN/EISSN', '年份', '大类', '大类分区', '小类1', '小类1分区'}
    if not required.issubset(headers):
        raise ValueError(f'{kind}: missing required columns {sorted(required - set(headers))}')
    if kind == 'jcr':
        years = {int(m[1]) for h in headers if (m := re.fullmatch(r'IF\((\d{4})\)', h))}
        if len(years) != 1:
            raise ValueError('jcr: expected one explicit IF metric year')
        year = years.pop()
        indices = [m[1] for h in headers if (m := re.fullmatch(r'Category_(\d+)', h))]
        if not indices or any(f'IF Quartile({year})_{i}' not in headers for i in indices):
            raise ValueError('jcr: missing year-specific category quartiles')
    else:
        years = {r['年份'].strip() for r in rows}
        if len(years) != 1 or not re.fullmatch(r'\d{4}', next(iter(years))):
            raise ValueError('cas: inconsistent or missing edition year')
        year = int(years.pop())
    return {'year': year, 'rows': len(rows), 'headers': headers,
            'sha256': hashlib.sha256(raw).hexdigest()}


def update_database(root=None, ref='master', getter=fetch):
    root = Path(root or default_data_dir()).resolve()
    tree = json.loads(getter(API + '/git/trees/' + urllib.parse.quote(ref, safe='') + '?recursive=1'))
    commit = tree['sha']
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or tree.get('truncated'):
        raise ValueError('invalid or truncated upstream tree')
    files, payloads = {}, {}
    for kind, pattern in [('jcr', r'JCR(\d{4})-UTF8\.csv'), ('cas', r'FQBJCR(\d{4})-UTF8\.csv')]:
        candidates = [(int(m[1]), item['path']) for item in tree['tree']
                      if (m := re.fullmatch(pattern, item['path'].rsplit('/', 1)[-1]))]
        if not candidates:
            raise ValueError(f'{kind}: no supported public CSV')
        label_year, source_path = max(candidates)
        url = f'https://raw.githubusercontent.com/hitfyd/ShowJCR/{commit}/' + urllib.parse.quote(source_path)
        raw = getter(url)
        info = inspect_csv(kind, raw)
        if info['year'] != label_year:
            raise ValueError(f'{kind}: filename year disagrees with content year')
        local_path = f'snapshots/{commit}/{source_path.rsplit("/", 1)[-1]}'
        files[kind] = dict(info, path=local_path, source_url=url, upstream_path=source_path)
        payloads[local_path] = raw
    readme_url = f'https://raw.githubusercontent.com/hitfyd/ShowJCR/{commit}/README.md'
    readme_raw = getter(readme_url)
    readme = readme_raw.decode('utf-8-sig')
    year = files['jcr']['year']
    lines = [line.strip() for line in readme.splitlines()
             if 'JCR' in line and str(year) in line and '发布' in line]
    claim = {'text': '\n'.join(lines) or UNVERIFIED, 'url': readme_url,
             'verification_status': UNVERIFIED}
    manifest = {'schema_version': 1, 'commit': commit, 'repository': REPOSITORY,
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'source_type': 'third_party_compilation', 'official_verified': False,
                'files': files, 'readme_claim': claim,
                'year_scope': 'JIF metric year and CAS edition year independently read from CSV content'}
    payloads[f'snapshots/{commit}/README.md'] = readme_raw
    # Fully fetch and validate before publishing; a failed update leaves the old manifest active.
    root.mkdir(parents=True, exist_ok=True)
    for relative, raw in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    temp = root / 'manifest.json.tmp'
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, root / 'manifest.json')
    return manifest


def resolve_doi(doi):
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='')
    message = json.loads(fetch(url))['message']
    if message.get('DOI', '').casefold() != doi.casefold():
        raise ValueError('Crossref DOI differs from requested DOI')
    if not message.get('container-title'):
        raise ValueError('Crossref has no journal container title')
    return {'doi': message['DOI'], 'article_titles': message.get('title', []),
            'journal_names': message.get('container-title', []),
            'issns': message.get('ISSN', []), 'issn_types': message.get('issn-type', []),
            'source_url': url, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'metadata_source': 'Crossref DOI registration metadata; does not verify journal metrics'}


def group_rows(rows):
    groups = {}
    for row in rows:
        key = tuple(row_issns(row)) or ('name:' + normalized_name(row['Journal']),)
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def unique_dicts(items):
    seen, result = set(), []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def partition(value):
    match = re.match(r'^\s*([1-4])(?:\s|区|$)', value)
    return int(match[1]) if match else UNVERIFIED


class Database:
    def __init__(self, root=None):
        self.root = Path(root or default_data_dir()).resolve()
        self.manifest = json.loads((self.root / 'manifest.json').read_text(encoding='utf-8'))
        if self.manifest.get('schema_version') != 1:
            raise ValueError('unsupported manifest schema')
        self.rows = {}
        for kind in ('jcr', 'cas'):
            info = self.manifest['files'][kind]
            path = (self.root / info['path']).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError('dataset path outside data directory')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != info['sha256']:
                raise ValueError(f'{kind}: checksum mismatch; run update')
            actual = inspect_csv(kind, raw)
            if actual['year'] != info['year'] or actual['rows'] != info['rows']:
                raise ValueError(f'{kind}: manifest year/row count disagrees with content')
            self.rows[kind] = parse_csv(raw)[1]

    def find(self, kind, ids, names):
        rows = self.rows[kind]
        if ids:
            groups = group_rows([r for r in rows if set(row_issns(r)) & ids])
            if groups:
                return groups, 'ISSN'
            # Name fallback is allowed only for source rows without identifiers.
            rows = [r for r in rows if not row_issns(r)]
        wanted = {normalized_name(name) for name in names if name}
        return group_rows([r for r in rows if normalized_name(r['Journal']) in wanted]), 'EXACT_NORMALIZED_NAME'

    def lookup(self, doi=None, name=None, issns=None, resolver=resolve_doi):
        output = {'status': UNVERIFIED, 'reason': 'NO_MATCH',
                  'query': {'doi': doi, 'name': name, 'issns': issns or []},
                  'journal': None, 'match_basis': {}, 'metadata': None,
                  'jif': {'value': None, 'raw': None, 'metric_year': self.manifest['files']['jcr']['year'],
                          'status': UNVERIFIED},
                  'jcr': {'status': UNVERIFIED, 'metric_year': self.manifest['files']['jcr']['year'], 'categories': []},
                  'cas': {'status': UNVERIFIED, 'edition_year': self.manifest['files']['cas']['year'],
                          'major_categories': [], 'minor_categories': []},
                  'official_verification': {'verified': False, 'status': UNVERIFIED,
                      'reason': 'Third-party ShowJCR data; no official journal-level verification performed'},
                  'provenance': self.manifest,
                  'checked_at': datetime.now(timezone.utc).isoformat(),
                  'scope': 'latest available in this local snapshot, not at article publication date'}
        names, raw_ids = ([name] if name else []), list(issns or [])
        metadata_types = {}
        if doi:
            doi = re.sub(r'^https?://(?:dx\.)?doi\.org/|^doi:\s*', '', doi.strip(), flags=re.I)
            if not re.fullmatch(r'10\.\d{4,9}/\S+', doi, flags=re.I):
                output['reason'] = 'INVALID_DOI'
                return output
            try:
                metadata = resolver(doi)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                output.update(reason='DOI_RESOLUTION_FAILED', error=str(exc))
                return output
            output['metadata'] = metadata
            names += metadata.get('journal_names', [])
            raw_ids += metadata.get('issns', [])
            metadata_types = {item['type']: normalize_issn(item.get('value', ''))
                              for item in metadata.get('issn_types', []) if item.get('type')}
            if metadata.get('journal_names'):
                output['journal'] = {'name': html.unescape(metadata['journal_names'][0]),
                    'issns': sorted({v for raw in metadata.get('issns', []) if (v := normalize_issn(raw))}),
                    'issn': metadata_types.get('print'), 'eissn': metadata_types.get('electronic'),
                    'identity_source': 'Crossref'}
        ids = {valid for raw in raw_ids if (valid := normalize_issn(raw))}
        if raw_ids and not ids:
            output['reason'] = 'INVALID_ISSN'
            return output
        matches, bases = {}, {}
        matches['jcr'], bases['jcr'] = self.find('jcr', ids, names)
        if len(matches['jcr']) == 1:
            ids = ids | set(row_issns(matches['jcr'][0][0]))
        matches['cas'], bases['cas'] = self.find('cas', ids, names)
        if not matches['jcr'] and len(matches['cas']) == 1:
            linked_ids = set(row_issns(matches['cas'][0][0]))
            if linked_ids:
                matches['jcr'], bases['jcr'] = self.find('jcr', linked_ids, [])
        if any(len(groups) > 1 for groups in matches.values()):
            output['reason'] = 'AMBIGUOUS'
            output['candidates'] = {kind: [{'name': g[0]['Journal'], 'issns': row_issns(g[0])}
                                          for g in groups] for kind, groups in matches.items()}
            return output
        selected = {kind: groups[0] for kind, groups in matches.items() if groups}
        if not selected:
            return output
        first = selected.get('jcr', selected.get('cas'))[0]
        output.update(status='MATCHED', reason=None, match_basis={k: bases[k] for k in selected})
        jcr_row = selected.get('jcr', [{}])[0]
        output['journal'] = {'name': first['Journal'], 'issns': row_issns(first),
                             'issn': normalize_issn(jcr_row.get('ISSN', '')) or metadata_types.get('print'),
                             'eissn': normalize_issn(jcr_row.get('EISSN', '')) or metadata_types.get('electronic'),
                             'identity_source': 'ShowJCR matched by ' + bases.get('jcr', bases.get('cas', '')),
                             'identifier_note': 'CAS ISSN/EISSN column does not independently identify print/electronic type'}
        if 'jcr' in selected:
            year = output['jif']['metric_year']
            values = {row[f'IF({year})'].strip() for row in selected['jcr']}
            if len(values) != 1:
                output.update(status=UNVERIFIED, reason='CONFLICTING_JIF_ROWS')
                return output
            raw = values.pop()
            try:
                number = float(raw)
                value = number if math.isfinite(number) and number >= 0 else None
            except ValueError:
                value = None
            output['jif'].update(raw=raw, value=value, status=FOUND if value is not None else UNVERIFIED)
            categories = []
            for row in selected['jcr']:
                for column in row:
                    if m := re.fullmatch(r'Category_(\d+)', column):
                        if not row[column].strip():
                            continue
                        index = m[1]
                        quartile = row.get(f'IF Quartile({year})_{index}', '').strip()
                        categories.append({'category': row[column].strip(),
                            'quartile': quartile if quartile in {'Q1', 'Q2', 'Q3', 'Q4'} else UNVERIFIED,
                            'rank': row.get(f'IF Rank({year})_{index}', '').strip() or UNVERIFIED})
            output['jcr'].update(status=FOUND if categories else UNVERIFIED, categories=unique_dicts(categories))
        if 'cas' in selected:
            majors, minors = [], []
            for row in selected['cas']:
                if row['大类'].strip():
                    majors.append({'category': row['大类'].strip(), 'partition': partition(row['大类分区']),
                                   'raw': row['大类分区']})
                for column in row:
                    if re.fullmatch(r'小类\d+', column) and row[column].strip():
                        raw = row.get(column + '分区', '')
                        minors.append({'category': row[column].strip(), 'partition': partition(raw), 'raw': raw})
            output['cas'].update(status=FOUND, major_categories=unique_dicts(majors), minor_categories=unique_dicts(minors))
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    update = sub.add_parser('update', help='Fetch latest supported public JCR/CAS CSVs into external data directory')
    update.add_argument('--ref', default='master', help='Upstream branch or commit; default master')
    sub.add_parser('status', help='Validate snapshot and print provenance')
    lookup = sub.add_parser('lookup', help='Lookup DOI, exact journal title, ISSN/eISSN')
    lookup.add_argument('--doi')
    lookup.add_argument('--name')
    lookup.add_argument('--issn', action='append', default=[])
    args = parser.parse_args()
    try:
        if args.command == 'update':
            result = update_database(args.data_dir, args.ref)
        elif args.command == 'status':
            result = Database(args.data_dir).manifest
        else:
            if not (args.doi or args.name or args.issn):
                parser.error('lookup needs --doi, --name or --issn')
            result = Database(args.data_dir).lookup(doi=args.doi, name=args.name, issns=args.issn)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': UNVERIFIED, 'reason': 'DATABASE_OR_NETWORK_ERROR', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
