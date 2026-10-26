"""只读核对 D6 B 验收候选来源；不检索、不加载配置、不生成答案。"""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import pymupdf

ROOT = Path(__file__).resolve().parents[1]


def normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def verify(root=ROOT):
    root = root.resolve()
    source_hashes = {}
    def source(relative):
        p = (root / relative).resolve()
        if not p.is_relative_to(root) or not p.is_file():
            raise ValueError("missing_or_outside_source: " + relative)
        source_hashes[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
        return p
    def require(condition, label):
        if not condition:
            raise ValueError(label)
    candidates = [json.loads(line) for line in source('artifacts/d6/acceptance_candidates.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    dev = [json.loads(line) for line in source('eval/dev.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    reservation = json.loads(source('artifacts/d6/dev_fact_family_reservations.json').read_text(encoding='utf-8'))
    reserved = {x['fact_family'] for x in reservation['reserved_families']}
    require(len(candidates) == 20, 'twenty_candidates')
    require(Counter(x['question_type'] for x in candidates) == {'fact': 10, 'method': 4, 'retrieval_paraphrase': 3, 'unanswerable': 3}, 'type_distribution')
    require(len({x['case_id'] for x in candidates}) == 20 and len({x['fact_family'] for x in candidates}) == 20, 'unique_ids_and_fact_families')
    require(not reserved.intersection(x['fact_family'] for x in candidates), 'reserved_development_facts_disjoint')
    require(not {normalized(x['question']).casefold() for x in dev}.intersection(normalized(x['question']).casefold() for x in candidates), 'no_exact_question_duplicates')
    require(all(x['review_status'] == 'ai_reviewed' and x.get('human_reviewed_by') is None and x.get('human_reviewed_at') is None for x in candidates), 'no_invented_human_review')
    corpus = {x['paper_id']: x for x in json.loads(source('eval/corpus.json').read_text(encoding='utf-8'))}
    pages, segments, chunk_rows = {}, {}, {}
    for paper_id, paper in corpus.items():
        pdf = source(paper['local_path'])
        require(source_hashes[paper['local_path']] == paper['pdf_sha256'], paper_id + '_pdf_hash')
        with pymupdf.open(pdf) as document:
            require(len(document) == paper['page_count'], paper_id + '_page_count')
            pages[paper_id] = [normalized(page.get_text()) for page in document]
        filtered = source('data/filtered/' + paper_id + '.jsonl')
        segments[paper_id] = {}
        for line in filtered.read_text(encoding='utf-8').splitlines():
            page = json.loads(line)
            for segment in page['segments']:
                if segment['indexable']:
                    segments[paper_id][segment['segment_id']] = segment
    database = source('data/index/papers.sqlite3')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        for paper_id in corpus:
            chunk_rows[paper_id] = db.execute('SELECT chunk_id,pdf_page,text,text_sha256,segment_id,parse_revision FROM chunks WHERE paper_id=?', (paper_id,)).fetchall()
    evidence_entries, negatives = [], []
    for case in candidates:
        require(case['split'] == 'acceptance' and len(case['paper_ids']) == 1 and case['paper_ids'][0] in corpus, case['case_id'] + '_scope')
        require(bool(case['expected_points']) and bool(case['question_zh']), case['case_id'] + '_annotation')
        paper_id = case['paper_ids'][0]
        require(bool(case['answerable']) == (case['question_type'] != 'unanswerable'), case['case_id'] + '_answerability')
        if case['answerable']:
            require(bool(case['expected_evidence']), case['case_id'] + '_positive_evidence')
            for index, evidence in enumerate(case['expected_evidence']):
                label = case['case_id'] + '_quote_' + str(index + 1)
                require(evidence['paper_id'] == paper_id and evidence['pdf_sha256'] == corpus[paper_id]['pdf_sha256'], label + '_source')
                page_no, quote = evidence['pdf_page'], normalized(evidence['quote'])
                require(type(page_no) is int and 1 <= page_no <= len(pages[paper_id]) and bool(quote), label + '_page')
                require(quote in pages[paper_id][page_no - 1], label + '_native_pdf')
                segment = segments[paper_id].get(evidence['segment_id'])
                require(segment is not None and segment['pdf_page'] == page_no and segment['filter_revision'] == evidence['filter_revision'] and quote in normalized(segment['text']), label + '_filtered_segment')
                matches = [c for c in chunk_rows[paper_id] if c[1] == page_no and c[4] == evidence['segment_id'] and quote in normalized(c[2])]
                require(bool(matches), label + '_formal_chunk')
                require(all(hashlib.sha256(c[2].encode('utf-8')).hexdigest() == c[3] for c in matches), label + '_text_sha')
                evidence_entries.append({'case_id': case['case_id'], 'target_index': index, 'paper_id': paper_id, 'pdf_page': page_no, 'segment_id': evidence['segment_id'], 'matching_chunk_ids': [c[0] for c in matches], 'native_pdf_match': True, 'filtered_segment_match': True, 'sqlite_match': True})
        else:
            require(not case['expected_evidence'] and bool(case['unanswerable_reason']), case['case_id'] + '_negative_fields')
            review = case['unanswerable_review']
            require(review['pdf_sha256'] == corpus[paper_id]['pdf_sha256'] and review['pages_checked'] == len(pages[paper_id]), case['case_id'] + '_negative_full_source_scope')
            require(bool(review.get('relevant_section_scope_review')), case['case_id'] + '_negative_method_scope')
            negatives.append({'case_id': case['case_id'], 'paper_id': paper_id, 'pages_checked': len(pages[paper_id]), 'source_identity_verified': True, 'answerability_semantic_review': 'ai_reviewed_pending_human', 'keyword_absence_is_not_proof': True})
    formal_exists = (root / 'eval/acceptance.jsonl').exists()
    if formal_exists:
        formal = [json.loads(line) for line in source('eval/acceptance.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        human = json.loads(source('artifacts/d6/acceptance_human_review.json').read_text(encoding='utf-8'))
        freeze = json.loads(source('artifacts/d6/acceptance_freeze_manifest.json').read_text(encoding='utf-8'))
        source('eval/acceptance_rubric.json')
        require(human['status'] == 'approved' and bool(human['actual_user_response']) and human['case_ids'] == [x['case_id'] for x in candidates], 'actual_twenty_annotation_confirmation')
        require(len(formal) == 20 and all(x['review_status'] == 'human_verified' and x['human_review_status'] == 'approved' and x['human_reviewed_by'] == human['human_reviewed_by'] and x['human_reviewed_at'] == human['human_reviewed_at'] for x in formal), 'formal_human_fields')
        review_fields = {'review_status', 'human_review_status', 'human_reviewed_by', 'human_reviewed_at', 'human_review_record'}
        require(all({k:v for k,v in a.items() if k not in review_fields} == {k:v for k,v in b.items() if k not in review_fields} for a,b in zip(candidates,formal)), 'formal_copy_only_review_metadata_changed')
        require(freeze['status'] == 'formally_frozen' and freeze['formal_freeze_completed'] is True and freeze['formal_acceptance_exists'] is True, 'formal_freeze_declared')
        require(freeze['candidate_sha256'] == human['candidate_sha256'] == source_hashes['artifacts/d6/acceptance_candidates.jsonl'], 'candidate_lock_matches_human_confirmation')
        require(freeze['formal_acceptance_sha256'] == human['formal_acceptance_sha256'] == source_hashes['eval/acceptance.jsonl'], 'formal_sha_binding')
        require(freeze['rubric_sha256'] == source_hashes['eval/acceptance_rubric.json'] and freeze['human_review_sha256'] == source_hashes['artifacts/d6/acceptance_human_review.json'], 'rubric_and_human_sha_binding')
    require(all(hashlib.sha256((root/name).read_bytes()).hexdigest() == digest for name,digest in source_hashes.items()), 'sources_unchanged_during_read')
    return {'task': 'D6-B-source-validation', 'status': 'passed_formally_frozen' if formal_exists else 'passed_pending_human_review', 'candidate_count': 20, 'answerable_count': 17, 'unanswerable_count': 3, 'type_counts': dict(Counter(x['question_type'] for x in candidates)), 'positive_quote_count': len(evidence_entries), 'evidence_entries': evidence_entries, 'negative_scope_checks': negatives, 'source_sha256': source_hashes, 'semantic_non_overlap_is_ai_review_not_program_proof': True, 'human_review_status': 'approved' if formal_exists else 'pending', 'formal_acceptance_activated': formal_exists, 'model_requests': 0, 'sqlite_read_only': True}


def main():
    try:
        report = verify()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({'status': 'failed', 'reason': str(error), 'model_requests': 0}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
