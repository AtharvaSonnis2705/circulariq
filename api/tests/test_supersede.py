from circulariq.ingest.supersede import topic_key


def test_topic_key_ignores_abbreviations_and_punctuation() -> None:
    assert topic_key("Master Circular for Debenture Trustees (DTs)") == topic_key(
        "Master Circular for Debenture Trustees"
    )
    assert topic_key("Master Circular for Research Analysts") != topic_key(
        "Master Circular for Investment Advisers"
    )
