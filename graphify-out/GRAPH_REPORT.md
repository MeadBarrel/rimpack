# Graph Report - rimpack  (2026-10-02)

## Corpus Check
- Corpus is ~42,363 words - fits in a single context window. You may not need a graph.

## Summary
- 1446 nodes · 3203 edges · 66 communities (47 shown, 19 thin omitted)
- Extraction: 86% EXTRACTED · 14% INFERRED · 0% AMBIGUOUS · INFERRED: 454 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- XML About Parsing
- XML Validation Diagnostics
- YAML Lexical Round-Tripping
- Module YAML Validation
- XML Diagnostic Trees
- Atomic Config Editing
- Setup Discovery
- Setup Workflow Tests
- Filesystem Identity Safety
- Setup YAML Editing
- Config Path Semantics
- Configuration Loading
- CLI Config Selection
- Module Reference Models
- Path and YAML Edge Cases
- Pydantic Schema Analysis
- Generated Pydantic Unions
- Steam Installation Discovery
- Configuration File Loading
- Steam Library Discovery Tests
- Stable Constraint Sorting
- Sorting Behavior Tests
- Safe Config File Selection
- Steam KeyValues Parsing
- Steam Library Metadata Validation
- Sorting Algorithm Verification
- Module YAML Parsing
- About.xml Domain Model
- Module Validation Errors
- Config Read Race Handling
- Modpack Specifications
- YAML Error Location Mapping
- CLI Config Specification
- Interactive Setup Prompting
- Implementation Guidance
- Rich Setup Prompt Styling
- Module Domain Model
- Workshop ID Normalization
- Setup Wizard Test Doubles
- Module Reference Validation
- Alias Specifications
- Cross-platform Path Handling
- Project Tooling Configuration
- Typed Setup Choices
- Unknown Config Diagnostics
- Source-aware Parse Errors
- Prompt Toolkit UI
- Package ID Identity
- Setup Cancellation Safety
- Validation Error Formatting
- Steam Manifest Validation
- Repository Guidance
- YAML Scalar Preservation
- Local Mod References
- Prefix Preservation Tests
- Sorting Cycle Errors
- Config File Path Selection
- CLI Entry Point
- Steam Registry Discovery
- Pydantic Validator Compatibility
- Pydantic Input Transform Validation
- Probe Agent Workflow
- Experiment Design
- Setup Prompt Styling Tests
- Probe Delegation
- Rimpack Package Root

## God Nodes (most connected - your core abstractions)
1. `load_config_snapshot()` - 41 edges
2. `Settings` - 41 edges
3. `parse_config_yaml()` - 36 edges
4. `parse_text()` - 36 edges
5. `parse_yaml()` - 36 edges
6. `Diagnostic` - 34 edges
7. `run_setup()` - 32 edges
8. `serialize_setup_settings()` - 31 edges
9. `load_config()` - 31 edges
10. `ModuleParseError` - 30 edges

## Surprising Connections (you probably didn't know these)
- `Implementation Notes` --semantically_similar_to--> `CLI Specification`  [INFERRED] [semantically similar]
  IMPLEMENTATION_NOTES.md → spec/cli.md
- `Implementation Notes` --semantically_similar_to--> `Global Configuration Specification`  [INFERRED] [semantically similar]
  IMPLEMENTATION_NOTES.md → spec/config.md
- `Implementation Notes` --semantically_similar_to--> `Setup Specification`  [INFERRED] [semantically similar]
  IMPLEMENTATION_NOTES.md → spec/setup.md
- `Implementation Notes` --semantically_similar_to--> `Sorting Specification`  [INFERRED] [semantically similar]
  IMPLEMENTATION_NOTES.md → spec/sorting.md
- `Stable Topological Sorting` --semantically_similar_to--> `Ordering Constraint Graph`  [INFERRED] [semantically similar]
  IMPLEMENTATION_NOTES.md → spec/sorting.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Modpack Module Inclusion and Effective Ordering** — spec_modpack_modpack, spec_modules_module_format, spec_sorting_preferred_order [EXTRACTED 1.00]
- **Shared Configuration Selection Across CLI and Setup** — spec_cli_config_selection, spec_config_settings_path_resolution, spec_setup_setup_wizard [EXTRACTED 1.00]

## Communities (66 total, 19 thin omitted)

### Community 0 - "XML About Parsing"
Cohesion: 0.09
Nodes (32): group_diagnostics(), _about_text_value(), _child(), _context_for_child(), _contextualize_child(), _dependency_list(), _ignore_if_no_matching_field(), _list_items() (+24 more)

### Community 1 - "XML Validation Diagnostics"
Cohesion: 0.06
Nodes (32): UnexpectedElementDiagnostic, diagnostic_group(), parse_text(), root_group(), test_context_indices_count_skipped_repeated_version_groups(), test_empty_supported_versions_after_bad_entries_returns_empty_tuple(), test_indexes_repeated_unknown_dependency_fields_and_attributes(), test_keeps_semicolon_separated_author_text_intact() (+24 more)

### Community 2 - "YAML Lexical Round-Tripping"
Cohesion: 0.05
Nodes (25): create_round_trip_yaml(), create_yaml_document(), _decode_source(), _document_end_tail(), dump_yaml_document(), _ends_with_line_break(), _has_marker_line(), _is_blank_or_comment_line() (+17 more)

### Community 3 - "Module YAML Validation"
Cohesion: 0.07
Nodes (28): assert_parses_each_reference_kind_in_before_and_after(), parse_yaml(), test_accepts_positive_workshop_ids_and_preserves_digit_spelling(), test_blank_collection_values_become_empty_tuples(), test_comments_multiline_paths_and_windows_backslashes_are_plain_text(), test_constraint_reference_matrix(), test_deeply_nested_unknown_values_fail_with_a_controlled_error(), test_duplicate_yaml_keys_are_rejected_with_source_marks() (+20 more)

### Community 4 - "XML Diagnostic Trees"
Cohesion: 0.06
Nodes (22): Diagnostic, DiagnosticGroup, DuplicateFieldDiagnostic, EmptyValueDiagnostic, InvalidAttributeDiagnostic, InvalidVersionTagDiagnostic, MissingFieldDiagnostic, _quoted_text() (+14 more)

### Community 5 - "Atomic Config Editing"
Cohesion: 0.06
Nodes (21): _blank_document_preamble(), _blank_or_comment_only(), ConcurrentConfigChange, ConfigEditError, ConfigSnapshot, _raise_concurrent_config_change(), save_config_snapshot(), _split_line_ending() (+13 more)

### Community 6 - "Setup Discovery"
Cohesion: 0.06
Nodes (22): _check_directory(), check_setup_paths(), _discover_candidates(), escape_terminal_controls(), _format_settings_review(), installation_layout_is_recognized(), InvalidManualPath, _is_directory() (+14 more)

### Community 7 - "Setup Workflow Tests"
Cohesion: 0.07
Nodes (24): main(), create_discovery(), create_installation(), make_ui(), test_clearing_workshop_removes_only_that_field_and_reviews_derived_overrides(), test_current_paths_remain_defaults_on_reruns_and_noop_preserves_bytes_and_mtime(), test_declined_or_cancelled_blank_source_remains_byte_identical(), test_declining_final_confirmation_does_not_create_selected_directories() (+16 more)

### Community 8 - "Filesystem Identity Safety"
Cohesion: 0.06
Nodes (21): capture_file_snapshot(), _capture_parent_identities(), _directory_identity(), _genuinely_absent(), _identity(), _is_link_or_junction(), _missing(), ParentDirectoryIdentity (+13 more)

### Community 9 - "Setup YAML Editing"
Cohesion: 0.08
Nodes (21): load_config_snapshot(), serialize_setup_settings(), Settings, parse_candidate(), test_adding_managed_fields_round_trips_document_markers_and_comments(), test_blank_source_normalizes_only_unsafe_blank_indentation_and_tabs(), test_blank_source_preserves_sdk_supported_unicode_line_separators(), test_block_scalar_managed_path_round_trips_as_a_path() (+13 more)

### Community 10 - "Config Path Semantics"
Cohesion: 0.07
Nodes (16): make_symlink(), set_home(), test_alternative_config_is_not_merged_with_or_replaced_by_default(), test_dangling_default_ancestor_is_not_an_absent_default(), test_dangling_default_ancestor_links_are_detected_without_privileges(), test_dangling_default_symlink_is_not_an_absent_default(), test_default_load_reads_existing_file(), test_direct_extra_mod_paths_accept_emptyable_list_spellings() (+8 more)

### Community 11 - "Configuration Loading"
Cohesion: 0.09
Nodes (19): ConfigParseError, parse_yaml(), test_absolute_paths_tilde_and_environment_expressions(), test_blank_extra_mod_paths_are_empty_tuples(), test_excessive_yaml_nesting_is_a_controlled_config_error(), test_invalid_known_field_is_not_hidden_by_unknown_fields(), test_meaningful_spaces_comments_and_windows_path_text(), test_non_yaml_indentation_does_not_turn_scalar_roots_into_comments() (+11 more)

### Community 12 - "CLI Config Selection"
Cohesion: 0.06
Nodes (14): SetupOutcome, test_changes_during_snapshot_read_are_detected(), test_cli_global_config_placement_and_help_do_not_load_settings(), forbidden_terminal_check(), test_cli_help_is_inert_and_global_config_must_precede_setup(), test_cli_nonterminal_invocation_fails_before_creating_files(), test_cli_passes_config_text_to_sdk_without_path_coercion(), fake_setup() (+6 more)

### Community 13 - "Module Reference Models"
Cohesion: 0.11
Nodes (17): LocModRecord, LocModReferenced, _LocRecordBase, ModOrderingConstraints, PidModRecord, PidModReferenced, _PidRecordBase, WidModRecord (+9 more)

### Community 14 - "Path and YAML Edge Cases"
Cohesion: 0.07
Nodes (11): _absolute(), _expand_home(), _file_stat(), _has_traceback_frame(), _invalid_unicode_escape(), _raise_validation_error(), _resolve_path(), _unsupported_complex_mapping_key() (+3 more)

### Community 15 - "Pydantic Schema Analysis"
Cohesion: 0.07
Nodes (13): SelectByRequiredField, test_alias_collisions_and_non_forbid_extras_fail_closed(), test_alias_paths_and_choices_fail_during_schema_construction(), test_emptyable_list_applies_to_future_collection_fields(), test_field_defaults_and_optional_aliases_affect_identity_inference(), test_function_plain_schemas_are_rejected_at_build_time(), test_init_only_explicit_non_init_and_ambiguous_schemas_fail_closed(), test_per_call_alias_name_overrides_are_outside_the_contract() (+5 more)

### Community 16 - "Generated Pydantic Unions"
Cohesion: 0.10
Nodes (10): _accepted_keys(), _Branch, _empty_string_as_empty_collection(), _Identity, _infer_identities(), _InputField, _inspect_branch(), _is_required() (+2 more)

### Community 17 - "Steam Installation Discovery"
Cohesion: 0.13
Nodes (12): _absolute_metadata_path(), _add_unique_path(), _discover_from_roots(), discover_rimworld_steam_installations(), _has_rimworld_markers(), _is_windows(), _library_paths(), _logical_drive_roots() (+4 more)

### Community 18 - "Configuration File Loading"
Cohesion: 0.10
Nodes (13): ConfigLoadResult, parse_config_yaml(), test_accepts_utf8_bom_and_rejects_invalid_encoding(), test_blank_and_comment_only_documents_use_defaults(), test_invalid_controls_in_comment_only_documents_are_config_errors(), test_invalid_yaml_control_characters_are_config_errors(), test_parser_does_not_resolve_configured_targets(), test_relative_file_arguments_become_absolute_and_ignore_later_cwd() (+5 more)

### Community 19 - "Steam Library Discovery Tests"
Cohesion: 0.10
Nodes (13): _make_install(), test_client_metadata_finds_separate_library_and_workshop_path(), test_direct_library_and_repeated_metadata_paths_are_deduplicated(), test_discovery_does_not_walk_game_or_workshop_trees(), test_malformed_library_vdf_is_skipped_without_aborting_other_roots(), test_manifest_fields_must_be_direct_children_of_app_state(), test_oversized_library_metadata_is_rejected(), test_public_discovery_uses_windows_candidate_roots() (+5 more)

### Community 20 - "Stable Constraint Sorting"
Cohesion: 0.12
Nodes (9): _build_adjacency(), _count_inversions(), _forward_kahn(), _record_edge(), _reverse_kahn(), SortingItem, stable_toposort(), _topological_order() (+1 more)

### Community 21 - "Sorting Behavior Tests"
Cohesion: 0.11
Nodes (9): OpaqueKey, test_before_after_mixed_repeated_and_missing_references(), test_constraint_collection_types_are_not_mutated(), test_empty_singleton_unconstrained_and_valid_inputs(), test_five_item_forward_reverse_and_prefix_tradeoff_regressions(), test_input_uniqueness_hashability_and_opaque_equal_references(), test_late_prerequisites_preserve_unrelated_trailing_order(), test_prefix_regressions_preserve_only_required_early_prerequisites() (+1 more)

### Community 22 - "Safe Config File Selection"
Cohesion: 0.12
Nodes (12): _actually_absent(), load_config(), select_config_path(), test_dangling_symlinks_are_errors_not_nonexistent_path_hints(), test_default_selection_and_missing_load_do_not_create_settings(), test_existing_directories_select_their_settings_file(), test_file_symlink_keeps_lexical_parent_for_relative_settings(), test_nonexistent_paths_use_yaml_extension_hints() (+4 more)

### Community 23 - "Steam KeyValues Parsing"
Cohesion: 0.12
Nodes (12): _manifest_install_directory(), _parse_vdf(), _parse_vdf_entries(), parse_block(), _read_vdf(), _single_named_entry(), _single_scalar(), _tokenize_vdf() (+4 more)

### Community 24 - "Steam Library Metadata Validation"
Cohesion: 0.10
Nodes (7): _quoted(), test_duplicate_library_indices_are_rejected(), test_game_markers_reject_a_resolved_path_outside_common(), test_legacy_and_modern_library_entries_find_multiple_installs(), test_only_direct_numeric_library_paths_are_trusted(), test_public_discovery_returns_empty_without_scanning_on_non_windows(), test_vdf_parser_enforces_token_and_nesting_limits()

### Community 25 - "Sorting Algorithm Verification"
Cohesion: 0.13
Nodes (11): _all_oriented_graphs(), _assert_graph_properties(), _inversion_count(), _items_from_edges(), _reference_best_of_two(), _reference_candidates(), _reference_urgencies(), test_candidate_winners_ties_and_independent_group_choices() (+3 more)

### Community 26 - "Module YAML Parsing"
Cohesion: 0.12
Nodes (9): _empty_yaml_document(), _mapping_at(), ModuleParseError, parse_module_yaml(), _raise_validation_error(), _yaml_error(), test_accepts_utf8_bom_and_reports_decode_errors(), test_invalid_yaml_control_characters_are_parse_errors() (+1 more)

### Community 27 - "About.xml Domain Model"
Cohesion: 0.14
Nodes (9): AboutDependency, AboutTextValue, ModAbout, VersionedDependencyList, VersionedDescription, VersionedPackageIdList, test_parses_supported_fields_and_versioned_collections(), test_reports_text_outside_versioned_list_and_dependency_groups() (+1 more)

### Community 28 - "Module Validation Errors"
Cohesion: 0.18
Nodes (8): _error_details(), _parse_failure(), test_boolean_null_numeric_and_date_like_scalars_are_text(), test_error_boundary_aggregates_relevant_details_and_suppresses_chaining(), test_missing_ambiguous_and_unknown_variant_keys_are_item_errors(), test_string_scalars_reach_the_selected_variant_validator(), test_tuple_failfast_stops_after_the_first_invalid_item(), _write_yaml()

### Community 29 - "Config Read Race Handling"
Cohesion: 0.12
Nodes (6): test_direct_extra_mod_paths_reject_invalid_collections(), test_direct_settings_accept_none_for_unset_overrides(), test_direct_settings_reject_invalid_path_inputs(), test_existing_unreadable_default_keeps_filesystem_error(), test_file_disappearing_before_read_obeys_default_missing_policy(), test_read_file_not_found_error_with_present_target_is_not_missing_config()

### Community 30 - "Modpack Specifications"
Cohesion: 0.17
Nodes (14): Modpack Specification, Modpack, Modpack Root Directory, Module Inclusion Order, Before and After Constraints, Modules Specification, Ordered Module Mod Entries, Module Format (+6 more)

### Community 31 - "YAML Error Location Mapping"
Cohesion: 0.13
Nodes (6): yaml_error_details(), test_module_validation_rejects_alias_references_in_python_and_json(), test_production_collections_reject_alias_references(), test_shared_parse_error_preserves_public_details(), test_shared_yaml_details_do_not_invent_coordinates(), test_shared_yaml_details_prefer_problem_mark()

### Community 32 - "CLI Config Specification"
Cohesion: 0.18
Nodes (13): Interactive Setup Wizard, Configuration File Selection, CLI Configuration Diagnostics, CLI Specification, Global --config Option, Setup CLI Entry Point, Global Configuration Specification, Effective Data and Mods Paths (+5 more)

### Community 33 - "Interactive Setup Prompting"
Cohesion: 0.17
Nodes (3): _root(), setup_command(), terminal_is_usable()

### Community 34 - "Implementation Guidance"
Cohesion: 0.17
Nodes (6): Implementation Notes, Module YAML Reading Constraints, Steam RimWorld Path Discovery, StrictYAML ReaderError Translation, Planned YAML Editing Guidance, Installation Candidate Discovery

### Community 36 - "Module Domain Model"
Cohesion: 0.17
Nodes (5): Module, _validated_identifier(), test_module_collections_default_and_normalize_only_empty_strings(), test_records_are_frozen(), _normalized_module()

### Community 37 - "Workshop ID Normalization"
Cohesion: 0.17
Nodes (4): WidReference, test_parses_all_reference_variants_and_unresolved_local_paths(), test_workshop_identity_handles_heavily_zero_padded_ids(), test_workshop_references_match_across_leading_zero_spellings()

### Community 40 - "Alias Specifications"
Cohesion: 0.20
Nodes (10): als Alias Reference, Aliases Specification, Mod Aliases (Future), Specification Index, Rimpack Product, Specification Organization, als Alias Reference (Future), Mod References Specification (+2 more)

### Community 41 - "Cross-platform Path Handling"
Cohesion: 0.18
Nodes (5): test_dangling_default_windows_junction_is_not_absent(), test_drive_relative_looking_text_is_literal_on_posix(), test_windows_absolute_and_ordinary_relative_paths_remain_valid(), test_windows_drive_relative_file_arguments_are_rejected(), test_windows_drive_relative_settings_are_rejected()

### Community 42 - "Project Tooling Configuration"
Cohesion: 0.20
Nodes (10): Basedpyright Hook, Pre-commit Configuration, Prek Hook Runner, Ruff Check Hook, Ruff Format Hook, Development Hook Commands, Project README, Rimpack (+2 more)

### Community 43 - "Typed Setup Choices"
Cohesion: 0.24
Nodes (3): prompt_choice(), prompt_confirmation(), ChoiceOption

### Community 44 - "Unknown Config Diagnostics"
Cohesion: 0.20
Nodes (5): UnknownConfigFieldDiagnostic, test_load_results_and_unknown_diagnostics_are_frozen(), test_unknown_config_field_renderer_escapes_without_mutating_payload(), test_unknown_fields_are_ignored_with_ordered_structured_diagnostics(), test_unknown_only_mapping_uses_defaults()

### Community 48 - "Setup Cancellation Safety"
Cohesion: 0.33
Nodes (4): SetupCancelled, test_cancelled_prompt_does_not_save_or_create_destination_parent(), choose(), confirm()

### Community 49 - "Validation Error Formatting"
Cohesion: 0.29
Nodes (3): validation_error_message(), test_shared_validation_format_handles_missing_details(), test_shared_validation_format_preserves_order_without_raw_input()

### Community 50 - "Steam Manifest Validation"
Cohesion: 0.29
Nodes (3): test_malformed_and_oversized_manifests_are_rejected(), test_unsafe_manifest_install_directories_are_rejected(), _write_manifest()

### Community 51 - "Repository Guidance"
Cohesion: 0.33
Nodes (4): Docstring Guidance, Repository Guidance, Approval Before Editing Implementation Notes, Design Patterns

### Community 54 - "Prefix Preservation Tests"
Cohesion: 0.33
Nodes (3): _assert_prefix_preservation(), _prefix_closures(), test_legacy_ten_item_fixture_obeys_new_prefix_rule()

## Knowledge Gaps
- **30 isolated node(s):** `rimpack`, `Evidence-Driven Probe Findings`, `Observable Success Criteria`, `Probe Prompt`, `Probe Delegation` (+25 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 749 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Settings` connect `Setup YAML Editing` to `Atomic Config Editing`, `Setup Discovery`, `Setup Workflow Tests`, `Cross-platform Path Handling`, `Config Path Semantics`, `Configuration Loading`, `Unknown Config Diagnostics`, `CLI Config Selection`, `Path and YAML Edge Cases`, `Configuration File Loading`, `Safe Config File Selection`, `Config Read Race Handling`?**
  _High betweenness centrality (0.043) - this node is a cross-community bridge._
- **Why does `XmlContext` connect `XML Diagnostic Trees` to `XML About Parsing`, `XML Validation Diagnostics`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Why does `PidReference` connect `Package ID Identity` to `Module Reference Models`?**
  _High betweenness centrality (0.017) - this node is a cross-community bridge._
- **Are the 30 inferred relationships involving `Settings` (e.g. with `serialize_setup_settings()` and `check_setup_paths()`) actually correct?**
  _`Settings` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `parse_config_yaml()` (e.g. with `test_config.py` and `parse_yaml()`) actually correct?**
  _`parse_config_yaml()` has 18 INFERRED edges - model-reasoned connections that need verification._
- **What connects `rimpack`, `Evidence-Driven Probe Findings`, `Observable Success Criteria` to the rest of the system?**
  _30 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `XML About Parsing` be split into smaller, more focused modules?**
  _Cohesion score 0.0886128364389234 - nodes in this community are weakly interconnected._