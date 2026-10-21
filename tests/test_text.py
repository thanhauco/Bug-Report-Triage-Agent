from triage_agent.text import extract_identifiers, tokenize


def test_tokenize_splits_identifiers_and_drops_stopwords():
    assert tokenize("The ConfigLoader in load_config is broken") == [
        "config",
        "loader",
        "load",
        "config",
        "broken",
    ]


def test_extract_identifiers_prefers_specific_patterns():
    text = "Crash in `parse_args` at app/config/loader.py when ConfigLoader calls load_config."
    identifiers = extract_identifiers(text)
    assert identifiers[:2] == ["parse_args", "app/config/loader.py"]
    assert "ConfigLoader" in identifiers
    assert "load_config" in identifiers


def test_extract_identifiers_deduplicates_and_limits():
    text = " ".join(f"name_{i} name_{i}" for i in range(20))
    identifiers = extract_identifiers(text, limit=5)
    assert identifiers == [f"name_{i}" for i in range(5)]


def test_extract_identifiers_ignores_plain_prose():
    assert extract_identifiers("the app crashes when I click save") == []
