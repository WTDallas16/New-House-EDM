from src.normalize import normalize_text, normalize_title


def test_normalize_text_removes_feature_noise():
    assert normalize_text("Chris Lake & D.O.D feat. Someone") == "chris lake and d o d someone"


def test_normalize_title_removes_mix_suffixes():
    assert normalize_title("Big Track (Extended Mix)") == "big track"

