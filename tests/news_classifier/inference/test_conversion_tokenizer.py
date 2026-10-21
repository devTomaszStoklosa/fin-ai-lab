from fin_ai_lab.news_classifier.inference.conversion_tokenizer import (
    first_mismatch,
    with_additional_special_tokens,
)

# Shaped like Bielik's real merged tokenizer files (issue #7).
_TOKENIZER_JSON = {
    "added_tokens": [
        {"id": 0, "content": "<unk>", "special": True},
        {"id": 1, "content": "<s>", "special": True},
        {"id": 2, "content": "</s>", "special": True},
        {"id": 3, "content": "<|im_start|>", "special": True},
        {"id": 4, "content": "<|im_end|>", "special": True},
        {"id": 5, "content": "<tool_call>", "special": True},
        {"id": 6, "content": "</tool_call>", "special": True},
    ]
}
_TOKENIZER_CONFIG = {
    "bos_token": "<s>",
    "eos_token": "<|im_end|>",
    "unk_token": "<unk>",
    "pad_token": "</s>",
    "extra_special_tokens": ["<|im_start|>", "<|im_end|>", "<tool_call>", "</tool_call>"],
    "tokenizer_class": "LlamaTokenizer",
}


def test_lists_special_tokens_without_a_named_role() -> None:
    config = with_additional_special_tokens(_TOKENIZER_CONFIG, _TOKENIZER_JSON)

    assert config["additional_special_tokens"] == ["<|im_start|>", "<tool_call>", "</tool_call>"]


def test_keeps_every_other_config_key_and_leaves_the_input_alone() -> None:
    config = with_additional_special_tokens(_TOKENIZER_CONFIG, _TOKENIZER_JSON)

    assert {key: config[key] for key in _TOKENIZER_CONFIG} == _TOKENIZER_CONFIG
    assert "additional_special_tokens" not in _TOKENIZER_CONFIG


def test_skips_added_tokens_not_marked_special() -> None:
    tokenizer_json = {
        "added_tokens": [
            {"id": 3, "content": "<|im_start|>", "special": True},
            {"id": 7, "content": "plain-word", "special": False},
        ]
    }

    config = with_additional_special_tokens(_TOKENIZER_CONFIG, tokenizer_json)

    assert config["additional_special_tokens"] == ["<|im_start|>"]


def test_recognizes_named_tokens_stored_as_dicts() -> None:
    tokenizer_config = {
        **_TOKENIZER_CONFIG,
        "bos_token": {"content": "<s>", "special": True},
    }

    config = with_additional_special_tokens(tokenizer_config, _TOKENIZER_JSON)

    assert "<s>" not in config["additional_special_tokens"]


def test_identical_tokenizations_have_no_mismatch() -> None:
    assert first_mismatch([1, 3, 10, 11], [1, 3, 10, 11]) is None


def test_reports_first_differing_position() -> None:
    # The real issue #7 failure: llama.cpp split <|im_start|> (3) into pieces.
    assert first_mismatch([1, 3, 10, 11], [1, 4144, 31957, 821]) == 1


def test_length_difference_counts_where_the_shorter_one_ends() -> None:
    assert first_mismatch([1, 3, 10], [1, 3, 10, 13]) == 3
    assert first_mismatch([1, 3, 10, 13], [1, 3]) == 2
