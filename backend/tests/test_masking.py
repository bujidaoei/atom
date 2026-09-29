from app.masking import mask_secret


def test_mask_shows_only_the_ends():
    secret = "sk-exampleSecretValue99"
    masked = mask_secret(secret)
    assert masked.startswith("sk")
    assert masked.endswith("99")
    assert "example" not in masked
    assert set(masked[2:-2]) == {"*"}
    assert len(masked) == len(secret)


def test_short_secret_is_fully_hidden():
    assert mask_secret("abcd") == "****"
    assert mask_secret("") == ""
