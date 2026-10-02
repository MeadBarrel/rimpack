"""Safe, one-document YAML loading shared by the SDK's input readers."""

from __future__ import annotations

from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import DuplicateKeyError, SafeConstructor
from ruamel.yaml.nodes import MappingNode

_MERGE_TAG = "tag:yaml.org,2002:merge"


class _MergeDuplicateCheckingConstructor(SafeConstructor):
    """Retain ruamel's duplicate checks for explicit keys beside YAML merges.

    The safe constructor normally permits repeated explicit keys in any map
    containing a merge because inherited keys are flattened before checking.
    This adapter checks only the map's own keys first, so an explicit key may
    still override an inherited value while repeated explicit keys fail.
    """

    def flatten_mapping(self, node: Any) -> Any:
        """Reject repeated local keys before ruamel combines inherited entries."""
        if isinstance(node, MappingNode) and any(
            key_node.tag == _MERGE_TAG for key_node, _ in node.value
        ):
            seen: dict[object, Any] = {}
            for key_node, _ in node.value:
                if key_node.tag == _MERGE_TAG:
                    continue
                key = self.construct_object(key_node, deep=True)
                # Match the safe constructor's YAML sequence-key normalization.
                if isinstance(key, list):
                    key = tuple(key)
                try:
                    previous = seen.get(key)
                except TypeError:
                    # The ordinary safe constructor will report unsupported,
                    # unhashable keys after this source-level duplicate check.
                    continue
                if previous is not None:
                    raise DuplicateKeyError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r}",
                        key_node.start_mark,
                        "Duplicate explicit keys are not allowed, including in "
                        "mappings with merge keys.",
                    )
                seen[key] = key_node
        return super().flatten_mapping(node)


def load_yaml(source: str) -> object:
    """Safely load exactly one YAML document with native YAML scalar types.

    Every call gets a fresh pure-Python safe loader with YAML 1.2 scalar
    resolution by default. Flow collections, anchors, aliases, merges, and safe
    standard tags are supported; supported version directives are honored and
    duplicate keys are rejected. Custom and Python-specific tagged objects are
    never constructed.
    """
    yaml = YAML(typ="safe", pure=True)
    yaml.Constructor = _MergeDuplicateCheckingConstructor
    yaml.allow_duplicate_keys = False
    return yaml.load(source)


def yaml_load_failure(error: BaseException) -> str | None:
    """Describe narrowly recognized ruamel failures raised outside ``YAMLError``.

    Resolver assertions, invalid Unicode escapes, and scalar-conversion failures
    are known invalid-source cases. The traceback check prevents unrelated
    application or library errors with similar messages from being hidden.
    """
    if isinstance(error, AssertionError) and _has_ruamel_frame(
        error, "ruamel.yaml.main", "version"
    ):
        if str(error).startswith("version minor part can only be 2 or 1, got "):
            return f"unsupported YAML version: {error.args[0]}"

    if isinstance(error, ValueError) and str(error) == (
        "chr() arg not in range(0x110000)"
    ):
        if _has_ruamel_frame(
            error, "ruamel.yaml.scanner", "scan_flow_scalar_non_spaces"
        ):
            return "invalid Unicode escape in YAML"

    if isinstance(error, (ValueError, OverflowError)) and _has_ruamel_frame(
        error, "ruamel.yaml.constructor", "construct_yaml_"
    ):
        return "invalid YAML scalar value"
    return None


def _has_ruamel_frame(error: BaseException, module: str, function: str) -> bool:
    """Return whether a traceback contains a specific ruamel parser frame."""
    traceback = error.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        frame_module = frame.f_globals.get("__name__")
        frame_function = frame.f_code.co_name
        if frame_module == module and (
            frame_function == function
            or function.endswith("_")
            and frame_function.startswith(function)
        ):
            return True
        traceback = traceback.tb_next
    return False
