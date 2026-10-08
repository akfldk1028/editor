"""Tolerant JSON reading and the small coercions every agent parser shares (nothing here raises)."""
import json

_MAX_REPAIR_ATTEMPTS = 400


def loads_tolerant(text):
    """JSON of `text`; a text cut mid-way is closed at its last complete value. None when unreadable."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return _close_truncated(text)


def _close_truncated(text):
    stack, cuts, in_string, escaped = [], [], False, False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if stack:
                stack.pop()
        elif char == ',':
            cuts.append((index, ''.join(stack)))
    for index, open_brackets in reversed(cuts[-_MAX_REPAIR_ATTEMPTS:]):
        closers = ''.join('}' if char == '{' else ']' for char in reversed(open_brackets))
        try:
            return json.loads(text[:index] + closers)
        except ValueError:
            continue
    return None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) and value else None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

