from collections import deque

from circulariq.embed import MAX_TEXTS_PER_REQUEST, Embedder


def make_embedder(tpm: int) -> Embedder:
    # Bypass __init__ so no API key or network is needed to test batching.
    e = Embedder.__new__(Embedder)
    e._tpm = tpm
    e._rpm = 0
    e._window = deque()
    return e


def test_batches_respect_text_count_limit() -> None:
    batches = make_embedder(0)._batches(["short text"] * 300)
    assert [len(b) for b in batches] == [MAX_TEXTS_PER_REQUEST, MAX_TEXTS_PER_REQUEST, 44]
    assert [i for b in batches for i in b] == list(range(300))


def test_batches_respect_tpm_budget() -> None:
    text = " ".join(["word"] * 300)  # ~398 estimated tokens; budget is 80% of 1250 = 1000
    batches = make_embedder(1250)._batches([text] * 5)
    assert [len(b) for b in batches] == [2, 2, 1]
