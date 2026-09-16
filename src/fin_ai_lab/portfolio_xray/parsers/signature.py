import hashlib
import json


def compute_signature(
    headers: list[str],
    *,
    delimiter: str | None,
    encoding: str,
    sheet_name: str | None = None,
) -> str:
    normalized_headers = [header.strip().lower() for header in headers if header]
    payload = {
        "headers": normalized_headers,
        "delimiter": delimiter,
        "encoding": encoding,
        "sheet_name": sheet_name,
    }
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
