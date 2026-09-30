import xml.etree.ElementTree as ET

import pytest

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
)
from rimpack.sdk.modabout import (
    AboutDependency,
    AboutTextValue,
    ModAbout,
    VersionedDependencyList,
    VersionedDescription,
    VersionedPackageIdList,
    XmlParseResult,
    _list_items,
    _parse_dependency,
    parse_about_xml,
)

MINIMAL_XML = """\
<ModMetaData>
  <packageId>example.mod</packageId>
  <name>Example Mod</name>
  <author>First Author, Second Author</author>
  <description>A test mod.</description>
  <supportedVersions><li>1.6</li></supportedVersions>
</ModMetaData>
"""


def diagnostic_group(
    tag: str, *diagnostics: Diagnostic, index: int | None = None
) -> DiagnosticGroup:
    """Build an expected diagnostic context group for an XML element."""
    return DiagnosticGroup(XmlContext(tag, index), tuple(diagnostics))


def root_group(*diagnostics: Diagnostic) -> DiagnosticGroup:
    """Build the expected outer context for About.xml diagnostics."""
    return diagnostic_group("ModMetaData", *diagnostics)


def parse_text(tmp_path, xml: str) -> XmlParseResult[ModAbout]:
    """Write XML to a temporary About.xml and parse it."""
    path = tmp_path / "About.xml"
    path.write_text(xml, encoding="utf-8")
    return parse_about_xml(path)


def test_parses_supported_fields_and_versioned_collections(tmp_path):
    """Parse scalar metadata and every supported collection shape."""
    result = parse_text(
        tmp_path,
        """\
<ModMetaData>
  <packageId>example.mod</packageId>
  <name> Example Mod </name>
  <authors><li> First Author </li><li>Second Author</li></authors>
  <description> A test mod. </description>
  <supportedVersions><li>1.5</li><li>1.6</li></supportedVersions>
  <modVersion IgnoreIfNoMatchingField="True"> 2.0 </modVersion>
  <modIconPath IgnoreIfNoMatchingField="false"> Textures/icon.png </modIconPath>
  <url> https://example.test/mod </url>
  <descriptionsByVersion>
    <v1.5> First-version description. </v1.5>
  </descriptionsByVersion>
  <modDependencies>
    <li>
      <packageId>dependency.mod</packageId>
      <displayName> Dependency </displayName>
      <steamWorkshopUrl> steam://workshop/123 </steamWorkshopUrl>
      <downloadUrl> https://example.test/dependency </downloadUrl>
      <alternativePackageIds IgnoreIfNoMatchingField="True">
        <li>dependency.dev</li>
        <li>dependency.fork</li>
      </alternativePackageIds>
    </li>
  </modDependencies>
  <modDependenciesByVersion>
    <v1.6><li><packageId>new.dependency</packageId></li></v1.6>
  </modDependenciesByVersion>
  <loadBefore><li>before.mod</li></loadBefore>
  <loadBeforeByVersion><v1.5><li>before.v15</li></v1.5></loadBeforeByVersion>
  <forceLoadBefore><li>force.before</li></forceLoadBefore>
  <loadAfter><li>after.mod</li></loadAfter>
  <loadAfterByVersion><v1.6><li>after.v16</li></v1.6></loadAfterByVersion>
  <forceLoadAfter><li>force.after</li></forceLoadAfter>
  <incompatibleWith><li>incompatible.mod</li></incompatibleWith>
  <incompatibleWithByVersion>
    <v1.5><li>incompatible.v15</li></v1.5>
  </incompatibleWithByVersion>
</ModMetaData>
""",
    )

    assert isinstance(result, XmlParseResult)
    assert result.value == ModAbout(
        package_id="example.mod",
        name="Example Mod",
        authors=("First Author", "Second Author"),
        description="A test mod.",
        supported_versions=("1.5", "1.6"),
        mod_version=AboutTextValue("2.0", True),
        mod_icon_path=AboutTextValue("Textures/icon.png", False),
        url="https://example.test/mod",
        descriptions_by_version=(
            VersionedDescription("1.5", "First-version description."),
        ),
        mod_dependencies=(
            AboutDependency(
                package_id="dependency.mod",
                display_name="Dependency",
                steam_workshop_url="steam://workshop/123",
                download_url="https://example.test/dependency",
                alternative_package_ids=("dependency.dev", "dependency.fork"),
                alternative_package_ids_ignore_if_no_matching_field=True,
            ),
        ),
        mod_dependencies_by_version=(
            VersionedDependencyList(
                "1.6", (AboutDependency(package_id="new.dependency"),)
            ),
        ),
        load_before=("before.mod",),
        load_before_by_version=(VersionedPackageIdList("1.5", ("before.v15",)),),
        force_load_before=("force.before",),
        load_after=("after.mod",),
        load_after_by_version=(VersionedPackageIdList("1.6", ("after.v16",)),),
        force_load_after=("force.after",),
        incompatible_with=("incompatible.mod",),
        incompatible_with_by_version=(
            VersionedPackageIdList("1.5", ("incompatible.v15",)),
        ),
    )
    assert result.diagnostics == ()


def test_preserves_comma_containing_author_and_optional_defaults(tmp_path):
    """Keep singular author text intact and use empty optional defaults."""
    result = parse_text(tmp_path, MINIMAL_XML)

    assert result.value.authors == ("First Author, Second Author",)
    assert result.value.supported_versions == ("1.6",)
    assert result.value.mod_version is None
    assert result.value.mod_icon_path is None
    assert result.value.url is None
    assert result.value.descriptions_by_version == ()
    assert result.value.mod_dependencies == ()
    assert result.value.mod_dependencies_by_version == ()
    assert result.value.load_before == ()
    assert result.value.load_before_by_version == ()
    assert result.value.force_load_before == ()
    assert result.value.load_after == ()
    assert result.value.load_after_by_version == ()
    assert result.value.force_load_after == ()
    assert result.value.incompatible_with == ()
    assert result.value.incompatible_with_by_version == ()
    assert result.diagnostics == ()


def test_keeps_semicolon_separated_author_text_intact(tmp_path):
    """Do not split a singular author value on semicolons."""
    xml = MINIMAL_XML.replace(
        "First Author, Second Author", "First Author; Second Author"
    )

    assert parse_text(tmp_path, xml).value.authors == ("First Author; Second Author",)


def test_singular_author_precedes_authors_list(tmp_path):
    """Place the singular author before entries from the authors list."""
    xml = MINIMAL_XML.replace(
        "<author>First Author, Second Author</author>",
        "<authors><li>Other Author</li><li>Other Author</li></authors>"
        "<author>Primary, Author</author>",
    )

    assert parse_text(tmp_path, xml).value.authors == (
        "Primary, Author",
        "Other Author",
        "Other Author",
    )


def test_supports_default_namespace(tmp_path):
    """Match recognized tags by local name in a default namespace."""
    xml = MINIMAL_XML.replace(
        "<ModMetaData>", '<ModMetaData xmlns="urn:rimworld:test">'
    )
    result = parse_text(tmp_path, xml)

    assert result.value.package_id == "example.mod"


def test_reports_unmodeled_fields_and_attributes(tmp_path):
    """Report unknown root fields, dependency fields, and attributes."""
    xml = MINIMAL_XML.replace(
        "<name>Example Mod</name>", '<name source="legacy">Example Mod</name>'
    ).replace(
        "</ModMetaData>",
        "  <modDependencies><li><packageId>dep.mod</packageId>"
        "<legacyHint>ignored</legacyHint></li></modDependencies>\n"
        "  <steamAppId>12345</steamAppId>\n</ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    diagnostic_group(
                        "legacyHint", UnknownFieldDiagnostic("legacyHint")
                    ),
                ),
            ),
            diagnostic_group("steamAppId", UnknownFieldDiagnostic("steamAppId")),
        ),
        root_group(
            diagnostic_group("name", UnknownAttributeDiagnostic("source", "legacy")),
        ),
    )


def test_reports_text_outside_list_and_dependency_entries(tmp_path):
    """Diagnose stray text while retaining recognized list entries."""
    xml = MINIMAL_XML.replace(
        "<supportedVersions><li>1.6</li></supportedVersions>",
        "<supportedVersions>1.5<li>1.6</li>1.7</supportedVersions>",
    ).replace(
        "</ModMetaData>",
        "<loadAfter>missing.mod<li>retained.mod</li></loadAfter>"
        "<modDependencies>missing.dep<li>inside item"
        "<packageId>dependency.mod</packageId>after packageId</li>trailing.dep"
        "</modDependencies></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.supported_versions == ("1.6",)
    assert result.value.load_after == ("retained.mod",)
    assert result.value.mod_dependencies == (
        AboutDependency(package_id="dependency.mod"),
    )
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "supportedVersions",
                StrayTextDiagnostic("1.5", "<li> entries"),
                StrayTextDiagnostic("1.7", "<li> entries"),
            ),
            diagnostic_group(
                "loadAfter",
                StrayTextDiagnostic("missing.mod", "<li> entries"),
            ),
            diagnostic_group(
                "modDependencies",
                StrayTextDiagnostic("missing.dep", "dependency <li> entries"),
                diagnostic_group(
                    "li",
                    StrayTextDiagnostic("inside item", "dependency fields"),
                    StrayTextDiagnostic("after packageId", "dependency fields"),
                ),
                StrayTextDiagnostic("trailing.dep", "dependency <li> entries"),
            ),
        ),
    )


def test_keeps_stray_text_diagnostics_in_root_source_order(tmp_path):
    """Order diagnostics from different root fields as they appear in XML."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<loadAfter>FIRST<li>some.mod</li></loadAfter>"
        "<modDependencies>SECOND<li><packageId>dep.mod</packageId></li>"
        "</modDependencies></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.diagnostics == (
        root_group(
            diagnostic_group("loadAfter", StrayTextDiagnostic("FIRST", "<li> entries")),
            diagnostic_group(
                "modDependencies",
                StrayTextDiagnostic("SECOND", "dependency <li> entries"),
            ),
        ),
    )


def test_reports_stray_text_between_root_fields_in_source_order(tmp_path):
    """Report exact non-whitespace text in the root and between its children."""
    xml = (
        "<ModMetaData>ROOT_START"
        "<packageId>example.mod</packageId>ROOT_MIDDLE"
        "<name>Example Mod</name>"
        "<author>First Author, Second Author</author>"
        "<description>A test mod.</description>"
        "<supportedVersions><li>1.6</li></supportedVersions>"
        "</ModMetaData>"
    )

    result = parse_text(tmp_path, xml)

    assert result.diagnostics == (
        root_group(
            StrayTextDiagnostic("ROOT_START", "About.xml fields"),
            StrayTextDiagnostic("ROOT_MIDDLE", "About.xml fields"),
        ),
    )


def test_list_parser_is_independent_of_container_name(tmp_path):
    """Keep child diagnostics local until each field-selection caller wraps them."""
    authors_element = ET.fromstring(
        "<authors>prefix<li>kept</li>middle<li> </li>suffix</authors>"
    )
    load_before_element = ET.fromstring(
        "<loadBefore>prefix<li>kept</li>middle<li> </li>suffix</loadBefore>"
    )

    authors_result = _list_items(authors_element, skip_invalid_entries=True)
    load_before_result = _list_items(load_before_element, skip_invalid_entries=True)

    local_diagnostics = (
        StrayTextDiagnostic("prefix", "<li> entries"),
        StrayTextDiagnostic("middle", "<li> entries"),
        diagnostic_group("li", EmptyValueDiagnostic(), index=2),
        StrayTextDiagnostic("suffix", "<li> entries"),
    )
    assert authors_result.value == load_before_result.value == ("kept",)
    assert (
        authors_result.diagnostics
        == load_before_result.diagnostics
        == local_diagnostics
    )

    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<authors>prefix<li>kept</li>middle<li> </li>suffix</authors>"
        "<loadBefore>prefix<li>kept</li>middle<li> </li>suffix</loadBefore>"
        "</ModMetaData>",
    )
    result = parse_text(tmp_path, xml)

    assert result.diagnostics == (
        root_group(
            diagnostic_group("authors", *local_diagnostics),
            diagnostic_group("loadBefore", *local_diagnostics),
        ),
    )


def test_dependency_parser_reports_local_facts_without_ancestor_context():
    """Parse a dependency directly and return facts without parent labels."""
    element = ET.fromstring("<li> stray<packageId></packageId> tail</li>")

    result = _parse_dependency(element)

    assert result.value is None
    assert result.diagnostics == (
        StrayTextDiagnostic(" stray", "dependency fields"),
        diagnostic_group("packageId", EmptyValueDiagnostic()),
        StrayTextDiagnostic(" tail", "dependency fields"),
    )


def test_skips_duplicate_dependency_ids_but_reports_other_entry_issues(tmp_path):
    """Represent duplicate dependency fields and continue checking sibling fields."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<modDependencies><li><packageId>first.dep</packageId>"
        "<packageId>second.dep</packageId><displayName> </displayName></li>"
        "</modDependencies></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.mod_dependencies == ()
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    DuplicateFieldDiagnostic("packageId", 2),
                    diagnostic_group("displayName", EmptyValueDiagnostic()),
                ),
            ),
        ),
    )


def test_context_indices_count_skipped_repeated_version_groups(tmp_path):
    """Index repeated version tags in source order, even when their groups fail."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<loadBeforeByVersion><broken>discard first</broken>"
        "<broken>discard second</broken></loadBeforeByVersion></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.load_before_by_version == ()
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "loadBeforeByVersion",
                diagnostic_group(
                    "broken",
                    InvalidVersionTagDiagnostic("broken"),
                    StrayTextDiagnostic("discard first", "<li> entries"),
                    index=1,
                ),
                diagnostic_group(
                    "broken",
                    InvalidVersionTagDiagnostic("broken"),
                    StrayTextDiagnostic("discard second", "<li> entries"),
                    index=2,
                ),
            ),
        ),
    )


def test_reports_text_outside_versioned_description_groups(tmp_path):
    """Diagnose text outside versioned descriptions without losing valid groups."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<descriptionsByVersion>lost<v1.6>retained</v1.6>also lost"
        "</descriptionsByVersion></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.descriptions_by_version == (
        VersionedDescription("1.6", "retained"),
    )
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "descriptionsByVersion",
                StrayTextDiagnostic("lost", "version groups"),
                StrayTextDiagnostic("also lost", "version groups"),
            ),
        ),
    )


@pytest.mark.parametrize(
    "package_id_xml",
    [
        "",
        "<packageId/>",
        "<packageId><li>example.mod</li></packageId>",
    ],
)
def test_rejects_missing_or_unusable_package_id(tmp_path, package_id_xml):
    """Keep the root package identifier strict while relaxing descriptive data."""
    xml = MINIMAL_XML.replace("<packageId>example.mod</packageId>", package_id_xml)

    with pytest.raises(ValueError):
        parse_text(tmp_path, xml)


def test_reports_missing_descriptive_fields_without_failing(tmp_path):
    """Represent absent name, authors, description, and versions with diagnostics."""
    xml = MINIMAL_XML
    for field in (
        "<name>Example Mod</name>",
        "<author>First Author, Second Author</author>",
        "<description>A test mod.</description>",
        "<supportedVersions><li>1.6</li></supportedVersions>",
    ):
        xml = xml.replace(field, "")

    result = parse_text(tmp_path, xml)

    assert result.value.name is None
    assert result.value.authors == ()
    assert result.value.description is None
    assert result.value.supported_versions is None
    assert result.diagnostics == (
        root_group(
            MissingFieldDiagnostic("name"),
            MissingFieldDiagnostic("author or authors"),
            MissingFieldDiagnostic("description"),
            MissingFieldDiagnostic("supportedVersions"),
        ),
    )


def test_reports_empty_descriptive_fields_without_failing(tmp_path):
    """Return absent scalar values and empty collections for explicit blanks."""
    xml = (
        MINIMAL_XML.replace("<name>Example Mod</name>", "<name> </name>")
        .replace("<author>First Author, Second Author</author>", "<author/>")
        .replace(
            "<description>A test mod.</description>", "<description> </description>"
        )
        .replace(
            "<supportedVersions><li>1.6</li></supportedVersions>",
            "<supportedVersions/>",
        )
        .replace("</ModMetaData>", "<authors/>\n</ModMetaData>")
    )

    result = parse_text(tmp_path, xml)

    assert result.value.name is None
    assert result.value.authors == ()
    assert result.value.description is None
    assert result.value.supported_versions == ()
    assert result.diagnostics == (
        root_group(
            diagnostic_group("name", EmptyValueDiagnostic()),
            diagnostic_group("author", EmptyValueDiagnostic()),
            diagnostic_group("description", EmptyValueDiagnostic()),
            diagnostic_group("supportedVersions", EmptyValueDiagnostic()),
            diagnostic_group("authors", EmptyValueDiagnostic()),
        ),
    )


def test_reports_missing_base_description_with_versioned_descriptions(tmp_path):
    """Keep version-specific descriptions when the base description is absent."""
    xml = MINIMAL_XML.replace("<description>A test mod.</description>", "").replace(
        "</ModMetaData>",
        "<descriptionsByVersion><v1.6>Version description</v1.6>"
        "</descriptionsByVersion></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.description is None
    assert result.value.descriptions_by_version == (
        VersionedDescription("1.6", "Version description"),
    )
    assert result.diagnostics == (root_group(MissingFieldDiagnostic("description")),)


def test_skips_unusable_supported_versions_and_keeps_valid_neighbors(tmp_path):
    """Keep supported-version entries around malformed list items."""
    xml = MINIMAL_XML.replace(
        "<supportedVersions><li>1.6</li></supportedVersions>",
        "<supportedVersions><li><b>bad</b></li><li>1.5</li></supportedVersions>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.supported_versions == ("1.5",)
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "supportedVersions",
                diagnostic_group(
                    "li", UnexpectedElementDiagnostic("b", "plain text"), index=1
                ),
            ),
        ),
    )


def test_empty_supported_versions_after_bad_entries_returns_empty_tuple(tmp_path):
    """Return an empty tuple when every supported-version entry is unusable."""
    xml = MINIMAL_XML.replace(
        "<supportedVersions><li>1.6</li></supportedVersions>",
        "<supportedVersions><li><b>bad</b></li></supportedVersions>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.supported_versions == ()
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "supportedVersions",
                diagnostic_group("li", UnexpectedElementDiagnostic("b", "plain text")),
                EmptyValueDiagnostic(),
            ),
        ),
    )


def test_rejects_wrong_root(tmp_path):
    """Reject XML whose root is not ModMetaData."""
    with pytest.raises(ValueError):
        parse_text(tmp_path, "<NotAbout/> ")


def test_rejects_malformed_xml(tmp_path):
    """Fail fast when the input is not well-formed XML."""
    with pytest.raises(Exception):
        parse_text(tmp_path, "<ModMetaData>")


def test_skips_and_reports_malformed_optional_list_entries(tmp_path):
    """Skip malformed optional list entries and retain valid neighbors."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<loadBefore><li>kept.mod</li><li> </li>"
        "<li><b>bad.mod</b></li><unexpected>ignored.mod</unexpected>"
        "</loadBefore></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.load_before == ("kept.mod",)
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "loadBefore",
                diagnostic_group("li", EmptyValueDiagnostic(), index=2),
                diagnostic_group(
                    "li",
                    UnexpectedElementDiagnostic("b", "plain text"),
                    index=3,
                ),
                diagnostic_group(
                    "unexpected",
                    UnexpectedElementDiagnostic("unexpected", "a <li> entry"),
                ),
            ),
        ),
    )


def test_skips_and_reports_nested_optional_text(tmp_path):
    """Skip optional scalar values containing unexpected child elements."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<url><li>https://example.test</li></url></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.package_id == "example.mod"
    assert result.value.url is None
    assert result.diagnostics == (
        root_group(
            diagnostic_group("url", UnexpectedElementDiagnostic("li", "plain text")),
        ),
    )


def test_skips_bad_optional_dependency_details_and_entries(tmp_path):
    """Recover valid dependency details and entries around malformed ones."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<modDependencies><li><packageId>good.dep</packageId>"
        "<downloadUrl><li>bad URL</li></downloadUrl>"
        "<alternativePackageIds><li>good.alt</li><li><b>bad.alt</b></li>"
        "</alternativePackageIds></li><li><displayName>missing ID</displayName>"
        "</li><unexpected/></modDependencies></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.mod_dependencies == (
        AboutDependency(package_id="good.dep", alternative_package_ids=("good.alt",)),
    )
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    diagnostic_group(
                        "downloadUrl",
                        UnexpectedElementDiagnostic("li", "plain text"),
                    ),
                    diagnostic_group(
                        "alternativePackageIds",
                        diagnostic_group(
                            "li",
                            UnexpectedElementDiagnostic("b", "plain text"),
                            index=2,
                        ),
                    ),
                    index=1,
                ),
                diagnostic_group("li", MissingFieldDiagnostic("packageId"), index=2),
                diagnostic_group(
                    "unexpected",
                    UnexpectedElementDiagnostic("unexpected", "a dependency <li>"),
                ),
            ),
        ),
    )


def test_skips_and_reports_invalid_optional_version_groups(tmp_path):
    """Skip invalid version groups while retaining valid grouped metadata."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<modDependenciesByVersion><broken><li><packageId>ignored.dep</packageId>"
        "</li><li><displayName>missing version ID</displayName></li></broken>"
        "<v1.6><li><packageId>kept.dep</packageId></li>"
        "<li><displayName>missing ID</displayName></li></v1.6>"
        "</modDependenciesByVersion><loadBeforeByVersion>"
        "<bad><li>ignored.mod</li></bad><v1.6><li>kept.mod</li><li> </li>"
        "</v1.6></loadBeforeByVersion></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.mod_dependencies_by_version == (
        VersionedDependencyList("1.6", (AboutDependency("kept.dep"),)),
    )
    assert result.value.load_before_by_version == (
        VersionedPackageIdList("1.6", ("kept.mod",)),
    )
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependenciesByVersion",
                diagnostic_group(
                    "broken",
                    InvalidVersionTagDiagnostic("broken"),
                    diagnostic_group(
                        "li", MissingFieldDiagnostic("packageId"), index=2
                    ),
                ),
                diagnostic_group(
                    "v1.6",
                    diagnostic_group(
                        "li", MissingFieldDiagnostic("packageId"), index=2
                    ),
                ),
            ),
            diagnostic_group(
                "loadBeforeByVersion",
                diagnostic_group("bad", InvalidVersionTagDiagnostic("bad")),
                diagnostic_group(
                    "v1.6",
                    diagnostic_group("li", EmptyValueDiagnostic(), index=2),
                ),
            ),
        ),
    )


def test_reports_text_outside_versioned_list_and_dependency_groups(tmp_path):
    """Diagnose stray text in versioned list and dependency containers."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<modDependenciesByVersion>lost<v1.6>inside"
        "<li><packageId>kept.dep</packageId></li>tail</v1.6>also lost"
        "</modDependenciesByVersion><loadBeforeByVersion>lost"
        "<v1.6>before.mod<li>kept.mod</li>tail</v1.6>also lost"
        "</loadBeforeByVersion></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.mod_dependencies_by_version == (
        VersionedDependencyList("1.6", (AboutDependency("kept.dep"),)),
    )
    assert result.value.load_before_by_version == (
        VersionedPackageIdList("1.6", ("kept.mod",)),
    )
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependenciesByVersion",
                StrayTextDiagnostic("lost", "version groups"),
                diagnostic_group(
                    "v1.6",
                    StrayTextDiagnostic("inside", "dependency <li> entries"),
                    StrayTextDiagnostic("tail", "dependency <li> entries"),
                ),
                StrayTextDiagnostic("also lost", "version groups"),
            ),
            diagnostic_group(
                "loadBeforeByVersion",
                StrayTextDiagnostic("lost", "version groups"),
                diagnostic_group(
                    "v1.6",
                    StrayTextDiagnostic("before.mod", "<li> entries"),
                    StrayTextDiagnostic("tail", "<li> entries"),
                ),
                StrayTextDiagnostic("also lost", "version groups"),
            ),
        ),
    )


def test_scans_unknown_fields_and_attributes_in_skipped_dependency(tmp_path):
    """Scan skipped dependencies so their unknown fields remain visible."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        '<modDependencies><li><legacyHint source="legacy">ignored</legacyHint>'
        '<alternativePackageIds IgnoreIfNoMatchingField="maybe"/>'
        "</li></modDependencies></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.mod_dependencies == ()
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group("li", MissingFieldDiagnostic("packageId")),
            ),
        ),
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    diagnostic_group(
                        "legacyHint", UnknownFieldDiagnostic("legacyHint")
                    ),
                ),
            ),
        ),
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    diagnostic_group(
                        "legacyHint", UnknownAttributeDiagnostic("source", "legacy")
                    ),
                    diagnostic_group(
                        "alternativePackageIds",
                        InvalidAttributeDiagnostic(
                            "IgnoreIfNoMatchingField", "maybe", ("True", "False")
                        ),
                    ),
                ),
            ),
        ),
    )


def test_indexes_repeated_unknown_dependency_fields_and_attributes(tmp_path):
    """Give repeated unknown fields distinct contexts in both focused scans."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<modDependencies><li><packageId>dep.mod</packageId>"
        '<hint source="first"/><hint source="second"/></li>'
        "</modDependencies></ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.mod_dependencies == (AboutDependency("dep.mod"),)
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    diagnostic_group("hint", UnknownFieldDiagnostic("hint"), index=1),
                    diagnostic_group("hint", UnknownFieldDiagnostic("hint"), index=2),
                ),
            ),
        ),
        root_group(
            diagnostic_group(
                "modDependencies",
                diagnostic_group(
                    "li",
                    diagnostic_group(
                        "hint", UnknownAttributeDiagnostic("source", "first"), index=1
                    ),
                    diagnostic_group(
                        "hint", UnknownAttributeDiagnostic("source", "second"), index=2
                    ),
                ),
            ),
        ),
    )


def test_reports_duplicate_optional_fields_and_scans_each_attribute(tmp_path):
    """Diagnose ambiguous fields and retain attributes from each occurrence."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        '<url source="first">https://first.test</url>'
        '<url source="second">https://second.test</url></ModMetaData>',
    )

    result = parse_text(tmp_path, xml)

    assert result.value.url is None
    assert result.diagnostics == (
        root_group(DuplicateFieldDiagnostic("url", 2)),
        root_group(
            diagnostic_group(
                "url",
                UnknownAttributeDiagnostic("source", "first"),
                index=1,
            ),
            diagnostic_group(
                "url",
                UnknownAttributeDiagnostic("source", "second"),
                index=2,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("mod_version_xml", "expected_value", "expected_diagnostics"),
    [
        (
            '<modVersion IgnoreIfNoMatchingField="maybe"/>',
            None,
            (
                root_group(diagnostic_group("modVersion", EmptyValueDiagnostic())),
                root_group(
                    diagnostic_group(
                        "modVersion",
                        InvalidAttributeDiagnostic(
                            "IgnoreIfNoMatchingField", "maybe", ("True", "False")
                        ),
                    )
                ),
            ),
        ),
        (
            '<modVersion IgnoreIfNoMatchingField="maybe">1.2</modVersion>',
            AboutTextValue("1.2", False),
            (
                root_group(
                    diagnostic_group(
                        "modVersion",
                        InvalidAttributeDiagnostic(
                            "IgnoreIfNoMatchingField", "maybe", ("True", "False")
                        ),
                    )
                ),
            ),
        ),
    ],
)
def test_reports_invalid_ignore_attribute(
    tmp_path, mod_version_xml, expected_value, expected_diagnostics
):
    """Diagnose invalid compatibility flags even on empty optional values."""
    xml = MINIMAL_XML.replace("</ModMetaData>", f"{mod_version_xml}</ModMetaData>")

    result = parse_text(tmp_path, xml)

    assert result.value.mod_version == expected_value
    assert result.diagnostics == expected_diagnostics


def test_reports_and_skips_nested_versioned_descriptions(tmp_path):
    """Skip malformed versioned descriptions while preserving valid groups."""
    xml = MINIMAL_XML.replace(
        "</ModMetaData>",
        "<descriptionsByVersion><v1.5>kept description</v1.5>"
        "<v1.6>Text <b>bold</b></v1.6></descriptionsByVersion>"
        "</ModMetaData>",
    )

    result = parse_text(tmp_path, xml)

    assert result.value.descriptions_by_version == (
        VersionedDescription("1.5", "kept description"),
    )
    assert result.diagnostics == (
        root_group(
            diagnostic_group(
                "descriptionsByVersion",
                diagnostic_group(
                    "v1.6", UnexpectedElementDiagnostic("b", "plain text")
                ),
            ),
        ),
    )
