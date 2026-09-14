"""JSON collections retain row associations and literal values; never treat them as text."""

import json

LIST_INVALID = "Enter a valid JSON array. Keep each entry together as an object or value."
LIST_REVIEW = "Verify every list entry and its row associations against the document; automatic list verification is not available."
LIST_CONFLICT = "Chunks returned different lists. Review the alternatives before accepting or correcting this collection."


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(LIST_INVALID)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(LIST_INVALID)


def parse_list(value: str) -> list:
    try:
        parsed = json.loads(
            value, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        if not isinstance(parsed, list):
            raise ValueError(LIST_INVALID)
        # Also reject finite-looking numeric literals which overflow to infinity.
        json.dumps(parsed, allow_nan=False)
        return parsed
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError(LIST_INVALID) from exc


def canonical_list(value: str) -> str:
    return json.dumps(
        parse_list(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
