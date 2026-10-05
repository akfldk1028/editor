"""Bounded OAuth transport for one logical twenty-program author batch."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Sequence


class OauthShardError(ValueError):
    """A shard plan or response set cannot represent the logical batch."""


@dataclass(frozen=True)
class OauthShard:
    index: int
    path_ids: tuple[str, ...]


def plan_oauth_shards(
    path_ids: Iterable[str],
    *,
    shard_size: int = 5,
) -> tuple[OauthShard, ...]:
    normalized = tuple(str(value).strip() for value in path_ids)
    if len(normalized) != 20 or len(set(normalized)) != 20:
        raise OauthShardError("logical author batch must contain 20 unique paths")
    size = int(shard_size)
    if size <= 0 or len(normalized) % size:
        raise OauthShardError("shard size must evenly partition the logical batch")
    return tuple(
        OauthShard(index=index // size + 1, path_ids=normalized[index:index + size])
        for index in range(0, len(normalized), size)
    )


def merge_oauth_shards(
    bundle_dir: Path | str,
    *,
    response_names: Sequence[str],
    expected_path_ids: Sequence[str],
    output_name: str,
) -> Path:
    """Append one exact logical response without rewriting authored items."""

    shards = plan_oauth_shards(expected_path_ids, shard_size=5)
    return merge_oauth_response_parts(
        bundle_dir,
        response_names=response_names,
        expected_path_groups=[list(shard.path_ids) for shard in shards],
        output_name=output_name,
    )


def merge_oauth_response_parts(
    bundle_dir: Path | str,
    *,
    response_names: Sequence[str],
    expected_path_groups: Sequence[Sequence[str]],
    output_name: str,
) -> Path:
    """Append ordered provider parts while preserving each authored object."""

    directory = Path(bundle_dir).resolve()
    if len(response_names) != len(expected_path_groups):
        raise OauthShardError("response shard count mismatch")
    programs: list[dict] = []
    expected_path_ids: list[str] = []
    for expected_group, name in zip(expected_path_groups, response_names):
        if Path(name).name != name:
            raise OauthShardError("response shard names must be local files")
        group = [str(value).strip() for value in expected_group]
        if not group or len(group) != len(set(group)):
            raise OauthShardError("response path group is invalid")
        try:
            payload = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise OauthShardError(f"invalid response shard: {name}") from exc
        items = payload.get("programs") if isinstance(payload, dict) else None
        if not isinstance(items, list) or len(items) != len(group):
            raise OauthShardError(f"response shard size mismatch: {name}")
        programs.extend(items)
        expected_path_ids.extend(group)
    if len(expected_path_ids) != len(set(expected_path_ids)):
        raise OauthShardError("response path identity mismatch")
    actual_path_ids = [
        str(item.get("book_composition_path_id") or "").strip()
        if isinstance(item, dict)
        else ""
        for item in programs
    ]
    if actual_path_ids != expected_path_ids:
        raise OauthShardError("response path identity mismatch")
    if Path(output_name).name != output_name:
        raise OauthShardError("merged response name must be a local file")
    output_path = directory / output_name
    try:
        with output_path.open("x", encoding="utf-8") as handle:
            json.dump(
                {"programs": programs},
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
            )
    except FileExistsError as exc:
        raise OauthShardError("merged response already exists") from exc
    return output_path


__all__ = [
    "OauthShard",
    "OauthShardError",
    "merge_oauth_response_parts",
    "merge_oauth_shards",
    "plan_oauth_shards",
]
