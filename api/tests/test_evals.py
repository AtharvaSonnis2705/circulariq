from evals.common import Expected, load_golden, matches, normalize
from evals.run_answers import citation_coverage, render_answer
from evals.run_retrieval import score_variant, sweep


def test_normalize_ignores_case_spacing_and_quote_style():
    assert normalize("“Choice of\n  Nomination”") == normalize('"choice of nomination"')


def test_matches_needs_both_document_and_evidence():
    e = Expected(doc="Master Circular for Debenture Trustees", evidence="within 60 days")
    title = "Master Circular for Debenture Trustees"
    assert matches(e, title, "Quarterly basis within  60 days from end of each quarter")
    assert not matches(e, "Master Circular for Mutual Funds", "within 60 days")
    assert not matches(e, title, "within 75 days")


def test_golden_set_is_well_formed():
    golden = load_golden()
    assert len({q.id for q in golden}) == len(golden)
    for q in golden:
        assert q.question.strip()
        if q.answerable:
            assert q.expected and q.must_include, q.id
        else:
            assert not q.expected, q.id


def test_score_variant_recall_and_mrr():
    # q1: found at rank 1; q2: one of two passages at rank 3, the other missing.
    m = score_variant([[1], [3, None]])
    assert m["recall@1"] == 0.5
    assert m["recall@5"] == 0.75
    assert m["mrr"] == round((1 + 1 / 3) / 2, 4)


def test_sweep_counts_refusals_and_leaks():
    rows = sweep(top_answerable=[0.9, 0.55], top_unanswerable=[0.3, 0.65])
    at_60 = next(r for r in rows if r["threshold"] == 0.6)
    assert at_60["false_refusals"] == 1 and at_60["false_answers"] == 1


def test_render_answer_numbers_citations_and_coverage():
    gen = {
        "blocks": ["Within 60 days.", " Except the last quarter."],
        "citations": [{"block": 0, "source": 2, "cited_text": "within 60 days"}],
    }
    text, cites = render_answer(gen)
    assert text == "Within 60 days.[c1] Except the last quarter."
    assert cites[0]["id"] == "c1" and cites[0]["source"] == 2
    assert 0.3 < citation_coverage(gen) < 0.4
