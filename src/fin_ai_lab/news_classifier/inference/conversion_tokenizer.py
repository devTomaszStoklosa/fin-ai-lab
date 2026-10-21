"""Keeps the quantized Bielik's llama.cpp tokenizer in step with the
transformers tokenizer the model is fine-tuned with (issue #7).

Measured on every corpus prompt, llama.cpp turned 0 of them into the same
tokens as transformers. Two separate gaps, each enough on its own:

1. `scripts/news_classifier_quantize_bielik.py` saves the merged tokenizer
   with transformers 5, which lists `<|im_start|>` under
   `extra_special_tokens`. llama.cpp's converter runs on transformers 4.x
   (its own pinned venv), which only reads `additional_special_tokens` --
   so the GGUF stored `<|im_start|>` as plain text, and llama.cpp split it
   into 7 ordinary tokens. `with_additional_special_tokens` lists those
   tokens under the key both versions read.
2. llama.cpp puts a space after every special token, as transformers 4.x
   does; transformers 5 doesn't. `inference/quantized.py` switches that off
   when it loads the GGUF. The converter only takes this setting from
   `add_prefix_space` in `tokenizer_config.json`, and that key makes
   transformers 4.x look for a `tokenizer.model` file Bielik doesn't have.

With both, every prompt matched. `first_mismatch` lets the quantize script
check this again after each build.

Standard library only, same reason as `build_record.py`.
"""

_NAMED_SPECIAL_TOKENS = ("bos_token", "eos_token", "unk_token", "pad_token")


def _token_text(value: object) -> object:
    # Older configs store a named token as a serialized AddedToken dict.
    return value.get("content") if isinstance(value, dict) else value


def with_additional_special_tokens(tokenizer_config: dict, tokenizer_json: dict) -> dict:
    """`tokenizer_config` plus `additional_special_tokens`: every token
    `tokenizer.json` marks special that has no named role (BOS/EOS/UNK/PAD).
    The named ones already reach the converter through their own keys."""
    named = {_token_text(tokenizer_config.get(key)) for key in _NAMED_SPECIAL_TOKENS}
    unnamed = [
        token["content"]
        for token in tokenizer_json.get("added_tokens", [])
        if token.get("special") and token["content"] not in named
    ]
    return {**tokenizer_config, "additional_special_tokens": unnamed}


def first_mismatch(expected: list[int], actual: list[int]) -> int | None:
    """Position of the first token where two tokenizations differ, or None
    when they're identical. When one is a prefix of the other, the position
    is where the shorter one ends."""
    for position, (left, right) in enumerate(zip(expected, actual, strict=False)):
        if left != right:
            return position
    if len(expected) != len(actual):
        return min(len(expected), len(actual))
    return None
