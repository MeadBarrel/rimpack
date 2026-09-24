"""Generic about.xml parser

See https://rimworldwiki.com/wiki/Modding_Tutorials/About.xml
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AboutTextValue:
    value: str
    ignore_if_no_matching_field: bool = False


@dataclass(frozen=True)
class AboutDependency:
    package_id: str
    display_name: str | None = None
    steam_workshop_url: str | None = None
    download_url: str | None = None
    alternative_package_ids: tuple[str, ...] = ()
    alternative_package_ids_ignore_if_no_matching_field: bool = False


@dataclass(frozen=True)
class VersionedDescription:
    version: str
    description: str


@dataclass(frozen=True)
class VersionedDependencyList:
    version: str
    dependencies: tuple[AboutDependency, ...]


@dataclass(frozen=True)
class VersionedPackageIdList:
    version: str
    package_ids: tuple[str, ...]


@dataclass(frozen=True)
class AboutModMetadata:
    package_id: str
    name: str
    authors: tuple[str, ...]
    description: str
    supported_versions: tuple[str, ...]
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
