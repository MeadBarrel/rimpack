"""Read known RimWorld mod metadata from an ``About.xml`` file.

The parser turns usable fields into immutable records and returns structured
diagnostics for missing, empty, or malformed metadata. Package IDs remain
required; other descriptive fields may be absent. See the RimWorld guide:
https://rimworldwiki.com/wiki/Modding_Tutorials/About.xml
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from rimpack.sdk.diagnostics import (
    Diagnostic,
    DiagnosticGroup,
    DuplicateFieldDiagnostic,
    EmptyValueDiagnostic,
    InvalidAttributeDiagnostic,
    InvalidVersionTagDiagnostic,
    MissingFieldDiagnostic,
    StrayTextDiagnostic,
    UnexpectedElementDiagnostic,
    UnknownAttributeDiagnostic,
    UnknownFieldDiagnostic,
    XmlContext,
    group_diagnostics,
)


@dataclass(frozen=True)
class AboutTextValue:
    """A text value plus RimWorld's optional compatibility flag.

    For example, ``<modVersion IgnoreIfNoMatchingField="true">1.2</modVersion>``
    becomes ``AboutTextValue("1.2", True)``.
    """

    value: str
    ignore_if_no_matching_field: bool = False


@dataclass(frozen=True)
class AboutDependency:
    """Information about another mod this mod depends on.

    ``package_id`` identifies the dependency; the display name, links, and
    alternative IDs are optional details.
    """

    package_id: str
    display_name: str | None = None
    steam_workshop_url: str | None = None
    download_url: str | None = None
    alternative_package_ids: tuple[str, ...] = ()
    alternative_package_ids_ignore_if_no_matching_field: bool = False


@dataclass(frozen=True)
class VersionedDescription:
    """A description that applies to one RimWorld version, such as ``1.6``."""

    version: str
    description: str


@dataclass(frozen=True)
class VersionedDependencyList:
    """Dependencies that apply to a particular RimWorld version."""

    version: str
    dependencies: tuple[AboutDependency, ...]


@dataclass(frozen=True)
class VersionedPackageIdList:
    """Package IDs grouped under one RimWorld version tag."""

    version: str
    package_ids: tuple[str, ...]


@dataclass(frozen=True)
class ModAbout:
    """Recognized metadata from one RimWorld ``About.xml`` file.

    Missing ``name`` or base ``description`` values are ``None``. A missing
    ``supportedVersions`` element is also ``None``; when present, its values are
    a tuple that may be empty. Other collections use tuples so parsed metadata
    is easy to compare and cannot be changed accidentally after parsing.
    """

    package_id: str
    name: str | None
    authors: tuple[str, ...]
    description: str | None
    supported_versions: tuple[str, ...] | None
    mod_version: AboutTextValue | None = None
    mod_icon_path: AboutTextValue | None = None
    url: str | None = None
    descriptions_by_version: tuple[VersionedDescription, ...] = ()
    mod_dependencies: tuple[AboutDependency, ...] = ()
    mod_dependencies_by_version: tuple[VersionedDependencyList, ...] = ()
    load_before: tuple[str, ...] = ()
    load_before_by_version: tuple[VersionedPackageIdList, ...] = ()
    force_load_before: tuple[str, ...] = ()
    load_after: tuple[str, ...] = ()
    load_after_by_version: tuple[VersionedPackageIdList, ...] = ()
    force_load_after: tuple[str, ...] = ()
    incompatible_with: tuple[str, ...] = ()
    incompatible_with_by_version: tuple[VersionedPackageIdList, ...] = ()


class XmlParseResult[T](NamedTuple):
    """A parsed value together with structured notes about its XML source."""

    value: T
    diagnostics: tuple[Diagnostic, ...]


def _local_name(tag: str) -> str:
    """Get the readable name from a possibly namespaced XML tag.

    For example, ``"{urn:rimworld}packageId"`` becomes ``"packageId"``.
    """
    return tag.rsplit("}", 1)[-1]


def _context_for_child(parent: ET.Element, child: ET.Element) -> XmlContext:
    """Create a diagnostic location for one direct child XML element.

    The location records the child's local tag and, only when that tag repeats
    among its siblings, its one-based occurrence. Counting skipped siblings too
    lets callers attach local parser errors to the exact source element.

    For one ``<li>`` under ``<loadAfter>``, this returns ``XmlContext("li")``.
    For the second ``<hint>`` in ``<li><hint/><hint/></li>``, it returns
    ``XmlContext("hint", 2)``, distinguishing its diagnostics from the first
    ``<hint>``.
    """
    tag = _local_name(child.tag)
    matching_siblings = [
        sibling for sibling in parent if _local_name(sibling.tag) == tag
    ]
    if len(matching_siblings) == 1:
        return XmlContext(tag)
    index = next(
        position
        for position, sibling in enumerate(matching_siblings, start=1)
        if sibling is child
    )
    return XmlContext(tag, index)


def _contextualize_child[T](
    parent: ET.Element, child: ET.Element, result: XmlParseResult[T]
) -> XmlParseResult[T]:
    """Add a selected child's XML location to its local parse result.

    Child parsers receive only the element and return unlocated diagnostics; its
    parent calls this helper afterward to add the child's tag and, when needed,
    one-based sibling index. The parsed value is unchanged, and an empty
    diagnostic tuple stays empty.

    For example, parsing ``<url/>`` locally yields ``EmptyValueDiagnostic()``.
    Contextualizing it under ``<ModMetaData>`` locates the issue at ``url``;
    for the second of two ``<url>`` siblings, the location is ``url[2]``.
    """
    return XmlParseResult(
        result.value,
        group_diagnostics(_context_for_child(parent, child), result.diagnostics),
    )


def _stray_text_diagnostic(
    fragment: str | None, expected_content: str
) -> StrayTextDiagnostic | None:
    """Create a leaf for one non-whitespace fragment, preserving its exact text."""
    if fragment is None or not fragment.strip():
        return None
    return StrayTextDiagnostic(fragment, expected_content)


def _matching_children(parent: ET.Element, name: str) -> list[ET.Element]:
    """Return direct children whose local tag name matches ``name``."""
    return [child for child in parent if _local_name(child.tag) == name]


def _child(parent: ET.Element, name: str) -> ET.Element | None:
    """Find a direct child, raising when it occurs more than once."""
    matches = _matching_children(parent, name)
    if len(matches) > 1:
        raise ValueError(f"Expected at most one <{name}> element")
    return matches[0] if matches else None


def _optional_child(parent: ET.Element, name: str) -> XmlParseResult[ET.Element | None]:
    """Select an optional direct child and describe duplicate occurrences.

    A missing field is ordinary for optional metadata. If it occurs more than
    once, no ambiguous child is selected and a duplicate diagnostic is returned.
    The caller supplies context for any selected child after parsing it.
    """
    matches = _matching_children(parent, name)
    if len(matches) > 1:
        return XmlParseResult(None, (DuplicateFieldDiagnostic(name, len(matches)),))
    return XmlParseResult(matches[0] if matches else None, ())


def _text_result(element: ET.Element) -> XmlParseResult[str | None]:
    """Read one element as trimmed leaf text, describing empty or nested values.

    This helper knows only the selected element. Its caller adds XML context if
    the returned diagnostics need to be located in the source tree.
    """
    if len(element):
        unexpected = _local_name(element[0].tag)
        return XmlParseResult(
            None,
            (UnexpectedElementDiagnostic(unexpected, "plain text"),),
        )
    value = (element.text or "").strip()
    if not value:
        return XmlParseResult(None, (EmptyValueDiagnostic(),))
    return XmlParseResult(value, ())


def _required_text(parent: ET.Element, name: str) -> str:
    """Read a required text field, raising for absent or unusable values."""
    element = _child(parent, name)
    if element is None:
        raise ValueError(f"Missing or empty required <{name}> element")
    text_result = _text_result(element)
    if text_result.value is not None:
        return text_result.value
    diagnostic = text_result.diagnostics[0]
    if isinstance(diagnostic, UnexpectedElementDiagnostic):
        raise ValueError(
            f"Unexpected nested <{diagnostic.tag}> in <{_local_name(element.tag)}>"
        )
    raise ValueError(f"Missing or empty required <{name}> element")


def _optional_text(parent: ET.Element, name: str) -> XmlParseResult[str | None]:
    """Select optional text and diagnose malformed values in its field context."""
    element_result = _optional_child(parent, name)
    element = element_result.value
    if element is None:
        return XmlParseResult(None, element_result.diagnostics)
    text_result = _text_result(element)
    contextual_result = _contextualize_child(parent, element, text_result)
    return XmlParseResult(
        contextual_result.value,
        element_result.diagnostics + contextual_result.diagnostics,
    )


def _reported_optional_text(
    parent: ET.Element, name: str
) -> XmlParseResult[str | None]:
    """Parse optional display text and diagnose when its field is absent.

    Unlike ordinary optional fields, metadata such as ``name`` and
    ``description`` is useful to report even when missing. Empty and malformed
    present values keep the more specific diagnostics from ``_optional_text``.
    """
    result = _optional_text(parent, name)
    if result.value is None and not result.diagnostics:
        return XmlParseResult(None, (MissingFieldDiagnostic(name),))
    return result


def _ignore_if_no_matching_field(element: ET.Element) -> bool:
    """Read ``IgnoreIfNoMatchingField`` as a case-insensitive true/false flag.

    Missing or invalid values return ``False``; invalid spellings are diagnosed
    by the focused attribute scan, including on otherwise skipped elements.
    """
    value = element.get("IgnoreIfNoMatchingField")
    return value is not None and value.strip().casefold() == "true"


def _list_items(
    element: ET.Element, *, skip_invalid_entries: bool
) -> XmlParseResult[tuple[str, ...]]:
    """Read ordered ``<li>`` values without knowing the container's parent.

    Malformed entries are either skipped with structured diagnostics or raise
    ``ValueError`` according to ``skip_invalid_entries``. Text around the list
    entries is always discarded and reported as one diagnostic per fragment.
    """
    diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(element.text, "<li> entries")
    if leading_text is not None:
        diagnostics.append(leading_text)

    values: list[str] = []
    for item in element:
        item_name = _local_name(item.tag)
        if item_name != "li":
            if not skip_invalid_entries:
                raise ValueError(f"Unexpected <{item_name}> in list container")
            item_diagnostics: tuple[Diagnostic, ...] = (
                UnexpectedElementDiagnostic(item_name, "a <li> entry"),
            )
            diagnostics.extend(
                group_diagnostics(_context_for_child(element, item), item_diagnostics)
            )
        else:
            text_result = _text_result(item)
            if text_result.value is None:
                if not skip_invalid_entries:
                    issue = text_result.diagnostics[0]
                    if isinstance(issue, UnexpectedElementDiagnostic):
                        raise ValueError(f"Unexpected nested <{issue.tag}> in <li>")
                    raise ValueError("Empty <li> entry")
                diagnostics.extend(
                    group_diagnostics(
                        _context_for_child(element, item), text_result.diagnostics
                    )
                )
            else:
                values.append(text_result.value)
        trailing_text = _stray_text_diagnostic(item.tail, "<li> entries")
        if trailing_text is not None:
            diagnostics.append(trailing_text)
    return XmlParseResult(tuple(values), tuple(diagnostics))


def _optional_list(parent: ET.Element, name: str) -> XmlParseResult[tuple[str, ...]]:
    """Select and parse an optional list, keeping valid entries and context."""
    element_result = _optional_child(parent, name)
    if element_result.value is None:
        return XmlParseResult((), element_result.diagnostics)
    items_result = _list_items(element_result.value, skip_invalid_entries=True)
    contextual_result = _contextualize_child(parent, element_result.value, items_result)
    return XmlParseResult(
        contextual_result.value,
        element_result.diagnostics + contextual_result.diagnostics,
    )


def _supported_versions(
    parent: ET.Element,
) -> XmlParseResult[tuple[str, ...] | None]:
    """Read supported versions without inferring defaults when none are present.

    A missing container yields ``None``; a present container yields a tuple,
    which may be empty. Invalid entries are diagnosed and skipped while valid
    neighboring versions are retained.
    """
    element_result = _optional_child(parent, "supportedVersions")
    element = element_result.value
    if element is None:
        if element_result.diagnostics:
            return XmlParseResult(None, element_result.diagnostics)
        return XmlParseResult(None, (MissingFieldDiagnostic("supportedVersions"),))

    items_result = _list_items(element, skip_invalid_entries=True)
    local_diagnostics = items_result.diagnostics
    if not items_result.value:
        local_diagnostics += (EmptyValueDiagnostic(),)
    contextual_result = _contextualize_child(
        parent,
        element,
        XmlParseResult(items_result.value, local_diagnostics),
    )
    return XmlParseResult(
        contextual_result.value,
        element_result.diagnostics + contextual_result.diagnostics,
    )


def _about_text_value(
    parent: ET.Element, name: str
) -> XmlParseResult[AboutTextValue | None]:
    """Read optional text with its ``IgnoreIfNoMatchingField`` flag."""
    element_result = _optional_child(parent, name)
    element = element_result.value
    if element is None:
        return XmlParseResult(None, element_result.diagnostics)
    text_result = _text_result(element)
    contextual_result = _contextualize_child(parent, element, text_result)
    value = (
        AboutTextValue(
            text_result.value,
            _ignore_if_no_matching_field(element),
        )
        if text_result.value is not None
        else None
    )
    return XmlParseResult(
        value,
        element_result.diagnostics + contextual_result.diagnostics,
    )


def _parse_dependency(element: ET.Element) -> XmlParseResult[AboutDependency | None]:
    """Parse one dependency element without requiring its ancestor context.

    A dependency needs one usable ``packageId``. Invalid IDs omit this entry;
    valid optional details and local diagnostics are collected in XML order.
    """
    diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(element.text, "dependency fields")
    if leading_text is not None:
        diagnostics.append(leading_text)

    known_fields = {
        "packageId",
        "displayName",
        "steamWorkshopUrl",
        "downloadUrl",
        "alternativePackageIds",
    }
    seen: set[str] = set()
    package_id: str | None = None
    display_name: str | None = None
    steam_workshop_url: str | None = None
    download_url: str | None = None
    alternative_package_ids: tuple[str, ...] = ()
    ignore_alternatives = False

    for child in element:
        field_name = _local_name(child.tag)
        if field_name in known_fields and field_name not in seen:
            seen.add(field_name)
            matches = _matching_children(element, field_name)
            if len(matches) > 1:
                diagnostics.append(DuplicateFieldDiagnostic(field_name, len(matches)))
            elif field_name == "alternativePackageIds":
                items_result = _list_items(child, skip_invalid_entries=True)
                contextual_result = _contextualize_child(element, child, items_result)
                diagnostics.extend(contextual_result.diagnostics)
                alternative_package_ids = contextual_result.value
                ignore_alternatives = _ignore_if_no_matching_field(child)
            else:
                text_result = _text_result(child)
                contextual_result = _contextualize_child(element, child, text_result)
                diagnostics.extend(contextual_result.diagnostics)
                if field_name == "packageId":
                    package_id = contextual_result.value
                elif field_name == "displayName":
                    display_name = contextual_result.value
                elif field_name == "steamWorkshopUrl":
                    steam_workshop_url = contextual_result.value
                elif field_name == "downloadUrl":
                    download_url = contextual_result.value

        trailing_text = _stray_text_diagnostic(child.tail, "dependency fields")
        if trailing_text is not None:
            diagnostics.append(trailing_text)

    if "packageId" not in seen:
        diagnostics.append(MissingFieldDiagnostic("packageId"))
    if package_id is None:
        return XmlParseResult(None, tuple(diagnostics))
    return XmlParseResult(
        AboutDependency(
            package_id=package_id,
            display_name=display_name,
            steam_workshop_url=steam_workshop_url,
            download_url=download_url,
            alternative_package_ids=alternative_package_ids,
            alternative_package_ids_ignore_if_no_matching_field=ignore_alternatives,
        ),
        tuple(diagnostics),
    )


def _dependency_list(
    element: ET.Element,
) -> XmlParseResult[tuple[AboutDependency, ...]]:
    """Parse dependency entries in order without receiving parent metadata."""
    diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(element.text, "dependency <li> entries")
    if leading_text is not None:
        diagnostics.append(leading_text)

    dependencies: list[AboutDependency] = []
    for item in element:
        if _local_name(item.tag) != "li":
            unexpected = (
                UnexpectedElementDiagnostic(_local_name(item.tag), "a dependency <li>"),
            )
            diagnostics.extend(
                group_diagnostics(_context_for_child(element, item), unexpected)
            )
        else:
            dependency_result = _parse_dependency(item)
            contextual_result = _contextualize_child(element, item, dependency_result)
            diagnostics.extend(contextual_result.diagnostics)
            if contextual_result.value is not None:
                dependencies.append(contextual_result.value)

        trailing_text = _stray_text_diagnostic(item.tail, "dependency <li> entries")
        if trailing_text is not None:
            diagnostics.append(trailing_text)
    return XmlParseResult(tuple(dependencies), tuple(diagnostics))


def _version_from_tag(element: ET.Element) -> XmlParseResult[str | None]:
    """Read the version encoded by this element's own tag, such as ``v1.6``."""
    tag = _local_name(element.tag)
    if re.fullmatch(r"v\d+(?:\.\d+)*", tag) is None:
        return XmlParseResult(None, (InvalidVersionTagDiagnostic(tag),))
    return XmlParseResult(tag[1:], ())


def _parse_versioned_package_id_container(
    container: ET.Element,
) -> XmlParseResult[tuple[VersionedPackageIdList, ...]]:
    """Parse version groups from a selected package-ID list container."""
    diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(container.text, "version groups")
    if leading_text is not None:
        diagnostics.append(leading_text)

    groups: list[VersionedPackageIdList] = []
    for version_element in container:
        version_result = _version_from_tag(version_element)
        items_result = _list_items(version_element, skip_invalid_entries=True)
        local_diagnostics = version_result.diagnostics + items_result.diagnostics
        diagnostics.extend(
            group_diagnostics(
                _context_for_child(container, version_element), local_diagnostics
            )
        )
        if version_result.value is not None:
            groups.append(
                VersionedPackageIdList(version_result.value, items_result.value)
            )
        trailing_text = _stray_text_diagnostic(version_element.tail, "version groups")
        if trailing_text is not None:
            diagnostics.append(trailing_text)
    return XmlParseResult(tuple(groups), tuple(diagnostics))


def _versioned_package_id_lists(
    parent: ET.Element, container_name: str
) -> XmlParseResult[tuple[VersionedPackageIdList, ...]]:
    """Select a versioned package-ID container and contextualize its groups."""
    container_result = _optional_child(parent, container_name)
    if container_result.value is None:
        return XmlParseResult((), container_result.diagnostics)
    parsed_result = _parse_versioned_package_id_container(container_result.value)
    contextual_result = _contextualize_child(
        parent, container_result.value, parsed_result
    )
    return XmlParseResult(
        contextual_result.value,
        container_result.diagnostics + contextual_result.diagnostics,
    )


def _parse_versioned_dependency_container(
    container: ET.Element,
) -> XmlParseResult[tuple[VersionedDependencyList, ...]]:
    """Parse version groups from a selected dependency container."""
    diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(container.text, "version groups")
    if leading_text is not None:
        diagnostics.append(leading_text)

    groups: list[VersionedDependencyList] = []
    for version_element in container:
        version_result = _version_from_tag(version_element)
        dependency_result = _dependency_list(version_element)
        local_diagnostics = (
            version_result.diagnostics + dependency_result.diagnostics
        )
        diagnostics.extend(
            group_diagnostics(
                _context_for_child(container, version_element), local_diagnostics
            )
        )
        if version_result.value is not None:
            groups.append(
                VersionedDependencyList(version_result.value, dependency_result.value)
            )
        trailing_text = _stray_text_diagnostic(version_element.tail, "version groups")
        if trailing_text is not None:
            diagnostics.append(trailing_text)
    return XmlParseResult(tuple(groups), tuple(diagnostics))


def _versioned_dependency_lists(
    parent: ET.Element,
) -> XmlParseResult[tuple[VersionedDependencyList, ...]]:
    """Select and parse the version-specific dependency container."""
    container_result = _optional_child(parent, "modDependenciesByVersion")
    if container_result.value is None:
        return XmlParseResult((), container_result.diagnostics)
    parsed_result = _parse_versioned_dependency_container(container_result.value)
    contextual_result = _contextualize_child(
        parent, container_result.value, parsed_result
    )
    return XmlParseResult(
        contextual_result.value,
        container_result.diagnostics + contextual_result.diagnostics,
    )


def _parse_versioned_description_container(
    container: ET.Element,
) -> XmlParseResult[tuple[VersionedDescription, ...]]:
    """Parse versioned descriptions from one selected container element."""
    diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(container.text, "version groups")
    if leading_text is not None:
        diagnostics.append(leading_text)

    descriptions: list[VersionedDescription] = []
    for version_element in container:
        version_result = _version_from_tag(version_element)
        text_result = _text_result(version_element)
        local_diagnostics = version_result.diagnostics + text_result.diagnostics

        diagnostics.extend(
            group_diagnostics(
                _context_for_child(container, version_element),
                local_diagnostics,
            )
        )
        if version_result.value is not None and text_result.value is not None:
            descriptions.append(
                VersionedDescription(version_result.value, text_result.value)
            )

        trailing_text = _stray_text_diagnostic(version_element.tail, "version groups")
        if trailing_text is not None:
            diagnostics.append(trailing_text)
    return XmlParseResult(tuple(descriptions), tuple(diagnostics))


def _versioned_descriptions(
    parent: ET.Element,
) -> XmlParseResult[tuple[VersionedDescription, ...]]:
    """Select and parse optional descriptions grouped by game version."""
    container_result = _optional_child(parent, "descriptionsByVersion")
    if container_result.value is None:
        return XmlParseResult((), container_result.diagnostics)
    parsed_result = _parse_versioned_description_container(container_result.value)
    contextual_result = _contextualize_child(
        parent, container_result.value, parsed_result
    )
    return XmlParseResult(
        contextual_result.value,
        container_result.diagnostics + contextual_result.diagnostics,
    )


def _parse_authors(root: ET.Element) -> XmlParseResult[tuple[str, ...]]:
    """Collect valid authors, placing intact singular ``<author>`` first.

    Missing or empty author metadata yields an empty tuple with diagnostics;
    malformed values are skipped while usable values from either form remain.
    """
    author_result = _optional_text(root, "author")
    authors_result = _optional_list(root, "authors")
    authors = ([author_result.value] if author_result.value else []) + list(
        authors_result.value
    )
    diagnostics = list(author_result.diagnostics + authors_result.diagnostics)

    authors_elements = _matching_children(root, "authors")
    if len(authors_elements) == 1 and not authors_result.value:
        if not authors_result.diagnostics:
            empty_list_result = XmlParseResult((), (EmptyValueDiagnostic(),))
            diagnostics.extend(
                _contextualize_child(root, authors_elements[0], empty_list_result)
                .diagnostics
            )
    elif not authors and not diagnostics:
        diagnostics.append(MissingFieldDiagnostic("author or authors"))

    return XmlParseResult(tuple(authors), tuple(diagnostics))


def _scan_unmodeled_dependency_fields(
    container: ET.Element,
) -> tuple[Diagnostic, ...]:
    """Find unknown fields inside dependency entries, including skipped entries."""
    modeled_fields = {
        "packageId",
        "displayName",
        "steamWorkshopUrl",
        "downloadUrl",
        "alternativePackageIds",
    }
    diagnostics: list[Diagnostic] = []
    for dependency in container:
        if _local_name(dependency.tag) != "li":
            continue
        unknown = tuple(
            diagnostic
            for field in dependency
            if _local_name(field.tag) not in modeled_fields
            for diagnostic in group_diagnostics(
                _context_for_child(dependency, field),
                (UnknownFieldDiagnostic(_local_name(field.tag)),),
            )
        )
        diagnostics.extend(
            group_diagnostics(_context_for_child(container, dependency), unknown)
        )
    return tuple(diagnostics)


def _scan_unmodeled_fields(root: ET.Element) -> tuple[Diagnostic, ...]:
    """Find unknown root and dependency fields, including in skipped entries."""
    modeled_root_fields = {
        "packageId",
        "name",
        "author",
        "authors",
        "description",
        "supportedVersions",
        "modVersion",
        "modIconPath",
        "url",
        "descriptionsByVersion",
        "modDependencies",
        "modDependenciesByVersion",
        "loadBefore",
        "loadBeforeByVersion",
        "forceLoadBefore",
        "loadAfter",
        "loadAfterByVersion",
        "forceLoadAfter",
        "incompatibleWith",
        "incompatibleWithByVersion",
    }
    diagnostics: list[Diagnostic] = []
    for child in root:
        name = _local_name(child.tag)
        if name not in modeled_root_fields:
            diagnostics.extend(
                group_diagnostics(
                    _context_for_child(root, child),
                    (UnknownFieldDiagnostic(name),),
                )
            )
        elif name == "modDependencies":
            dependency_diagnostics = _scan_unmodeled_dependency_fields(child)
            diagnostics.extend(
                group_diagnostics(
                    _context_for_child(root, child), dependency_diagnostics
                )
            )
        elif name == "modDependenciesByVersion":
            groups: list[Diagnostic] = []
            for version_group in child:
                dependency_diagnostics = _scan_unmodeled_dependency_fields(
                    version_group
                )
                groups.extend(
                    group_diagnostics(
                        _context_for_child(child, version_group),
                        dependency_diagnostics,
                    )
                )
            diagnostics.extend(
                group_diagnostics(_context_for_child(root, child), tuple(groups))
            )
    return tuple(diagnostics)


def _scan_attributes(element: ET.Element) -> tuple[Diagnostic, ...]:
    """Find unknown attributes and invalid compatibility flags recursively.

    Each recursive call receives only the element being inspected; its caller
    adds that element's context after the scan returns.
    """
    recognized_attributes = {
        "modVersion": {"IgnoreIfNoMatchingField"},
        "modIconPath": {"IgnoreIfNoMatchingField"},
        "alternativePackageIds": {"IgnoreIfNoMatchingField"},
    }
    name = _local_name(element.tag)
    diagnostics: list[Diagnostic] = []
    for attribute, value in element.attrib.items():
        if attribute not in recognized_attributes.get(name, set()):
            diagnostics.append(UnknownAttributeDiagnostic(attribute, value))
        elif (
            attribute == "IgnoreIfNoMatchingField"
            and value.strip().casefold() not in {"true", "false"}
        ):
            diagnostics.append(
                InvalidAttributeDiagnostic(
                    attribute,
                    value,
                    ("True", "False"),
                )
            )

    for child in element:
        child_diagnostics = _scan_attributes(child)
        diagnostics.extend(
            group_diagnostics(_context_for_child(element, child), child_diagnostics)
        )
    return tuple(diagnostics)


def parse_about_xml(path: str | Path) -> XmlParseResult[ModAbout]:
    """Parse a RimWorld ``About.xml`` file into metadata and diagnostics.

    Optional malformed values are skipped and represented as structured records;
    valid neighboring metadata is retained. Use ``render_diagnostics`` for text::

        from rimpack.sdk.diagnostics import render_diagnostics

        result = parse_about_xml("Mods/Example/About/About.xml")
        print(result.value.package_id)
        print(render_diagnostics(result.diagnostics))

    Missing or unusable ``packageId`` values, an unexpected root, and invalid
    XML syntax still raise errors. Other descriptive metadata may be absent and
    is represented by ``None`` or an empty tuple with diagnostics.
    """
    root = ET.parse(path).getroot()
    if _local_name(root.tag) != "ModMetaData":
        raise ValueError("About.xml root element must be <ModMetaData>")

    dependencies_element_result = _optional_child(root, "modDependencies")
    if dependencies_element_result.value is None:
        dependencies_result: XmlParseResult[tuple[AboutDependency, ...]] = (
            XmlParseResult((), ())
        )
    else:
        dependencies_result = _contextualize_child(
            root,
            dependencies_element_result.value,
            _dependency_list(dependencies_element_result.value),
        )

    package_id = _required_text(root, "packageId")
    name_result = _reported_optional_text(root, "name")
    authors_result = _parse_authors(root)
    description_result = _reported_optional_text(root, "description")
    supported_versions_result = _supported_versions(root)
    mod_version_result = _about_text_value(root, "modVersion")
    mod_icon_path_result = _about_text_value(root, "modIconPath")
    url_result = _optional_text(root, "url")
    descriptions_result = _versioned_descriptions(root)
    dependencies_by_version_result = _versioned_dependency_lists(root)
    load_before_result = _optional_list(root, "loadBefore")
    load_before_by_version_result = _versioned_package_id_lists(
        root, "loadBeforeByVersion"
    )
    force_load_before_result = _optional_list(root, "forceLoadBefore")
    load_after_result = _optional_list(root, "loadAfter")
    load_after_by_version_result = _versioned_package_id_lists(
        root, "loadAfterByVersion"
    )
    force_load_after_result = _optional_list(root, "forceLoadAfter")
    incompatible_with_result = _optional_list(root, "incompatibleWith")
    incompatible_with_by_version_result = _versioned_package_id_lists(
        root, "incompatibleWithByVersion"
    )

    value = ModAbout(
        package_id=package_id,
        name=name_result.value,
        authors=authors_result.value,
        description=description_result.value,
        supported_versions=supported_versions_result.value,
        mod_version=mod_version_result.value,
        mod_icon_path=mod_icon_path_result.value,
        url=url_result.value,
        descriptions_by_version=descriptions_result.value,
        mod_dependencies=dependencies_result.value,
        mod_dependencies_by_version=dependencies_by_version_result.value,
        load_before=load_before_result.value,
        load_before_by_version=load_before_by_version_result.value,
        force_load_before=force_load_before_result.value,
        load_after=load_after_result.value,
        load_after_by_version=load_after_by_version_result.value,
        force_load_after=force_load_after_result.value,
        incompatible_with=incompatible_with_result.value,
        incompatible_with_by_version=incompatible_with_by_version_result.value,
    )

    root_field_results = (
        ("modDependencies", dependencies_element_result.diagnostics),
        ("modDependencies", dependencies_result.diagnostics),
        ("name", name_result.diagnostics),
        ("author", authors_result.diagnostics),
        ("description", description_result.diagnostics),
        ("supportedVersions", supported_versions_result.diagnostics),
        ("modVersion", mod_version_result.diagnostics),
        ("modIconPath", mod_icon_path_result.diagnostics),
        ("url", url_result.diagnostics),
        ("descriptionsByVersion", descriptions_result.diagnostics),
        ("modDependenciesByVersion", dependencies_by_version_result.diagnostics),
        ("loadBefore", load_before_result.diagnostics),
        ("loadBeforeByVersion", load_before_by_version_result.diagnostics),
        ("forceLoadBefore", force_load_before_result.diagnostics),
        ("loadAfter", load_after_result.diagnostics),
        ("loadAfterByVersion", load_after_by_version_result.diagnostics),
        ("forceLoadAfter", force_load_after_result.diagnostics),
        ("incompatibleWith", incompatible_with_result.diagnostics),
        ("incompatibleWithByVersion", incompatible_with_by_version_result.diagnostics),
    )
    diagnostics_by_field: dict[str, list[Diagnostic]] = {}
    for fallback_field, field_diagnostics in root_field_results:
        for diagnostic in field_diagnostics:
            if isinstance(diagnostic, DiagnosticGroup):
                field_name = diagnostic.context.tag
            elif isinstance(diagnostic, DuplicateFieldDiagnostic):
                field_name = diagnostic.tag
            else:
                field_name = fallback_field
            diagnostics_by_field.setdefault(field_name, []).append(diagnostic)

    parse_diagnostics: list[Diagnostic] = []
    leading_text = _stray_text_diagnostic(root.text, "About.xml fields")
    if leading_text is not None:
        parse_diagnostics.append(leading_text)
    visited_fields: set[str] = set()
    for child in root:
        field_name = _local_name(child.tag)
        if field_name in diagnostics_by_field and field_name not in visited_fields:
            parse_diagnostics.extend(diagnostics_by_field[field_name])
            visited_fields.add(field_name)
        trailing_text = _stray_text_diagnostic(child.tail, "About.xml fields")
        if trailing_text is not None:
            parse_diagnostics.append(trailing_text)
    for field_name, field_diagnostics in diagnostics_by_field.items():
        if field_name not in visited_fields:
            parse_diagnostics.extend(field_diagnostics)

    diagnostics = (
        group_diagnostics(XmlContext("ModMetaData"), tuple(parse_diagnostics))
        + group_diagnostics(XmlContext("ModMetaData"), _scan_unmodeled_fields(root))
        + group_diagnostics(XmlContext("ModMetaData"), _scan_attributes(root))
    )
    return XmlParseResult(value, diagnostics)
