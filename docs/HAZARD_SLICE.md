# Hazard review slice

This file declares the bounded review universe for the final CryoDAQ hazard round.
Changed entries are reviewed exhaustively; unchanged entries are context needed to
trace their data, control, evidence, and operator-truth paths. A path absent from this
manifest is outside that round by declaration, not proven irrelevant to every possible
future hazard analysis.

## Frozen comparison

- Base: `f5d6434d20dffae62c9f03fbc12f68b03f48351b`
- Target: `5f0282b98ddc93da7e89119b10fe01ce2bc75e71`
- Generator: `tools/generate_hazard_slice.py`
- Changed means present at the target and selected by
  `git diff --name-only --diff-filter=ACMR <base>...<target>`, plus the two
  manifest-lane files while they are untracked during their first generation.

## Method

The generator parses local Python imports and starts from source modules containing
the declared actuation/OFF-evidence symbols. It follows the transitive consumer
direction. It then adds bounded semantic edges that imports cannot represent:

1. **Data flow/config/identity input** — driver readings and transports, descriptor
   binding, channel maps, safety/alarm/interlock configuration, broker/scheduler
   publication, persistence feedback, and the clocks used by safety predicates.
2. **IPC/message bus** — GUI and launcher command producers, ZMQ request/reply and
   publish/subscribe bridges, descriptor and operator-snapshot envelopes, and replay
   command handling.
3. **Callbacks/registries** — broker overflow, persistence-failure, supervision and
   interlock callbacks, plus driver/runtime-binding registration.
4. **OFF evidence/operator truth** — typed OFF results through SafetyManager, shutdown
   receipts, operator snapshots, replay, persistence, and visible operator state.
5. **Launcher/shutdown/process death** — source and frozen entry points, signal/process
   ownership, shutdown settlement, instance locks, and launcher receipts.
6. **Dynamic/frozen build** — the PyInstaller spec and hooks, entry-point metadata,
   driver registry, frozen path resolution, and ONEDIR contract tests.
7. **Changed guard/governance evidence** — changed governance/docs test trees, changed
   static guard/seal/contract/conformance tests, their CI/governance runners and
   workflows, and the claim-correction/governing documents that define what green
   evidence means.

These are path-semantic edges, deliberately not the full dependency closure. Generic
logging, formatting, and unrelated presentation dependencies are not added merely
because a selected module imports them.

## Blind spots and required human work

- The AST graph sees ordinary Python imports only. Dynamic imports, reflection, native
  extensions, subprocess protocols, shell indirection, and dependency injection are
  not inferred. A reviewer must inspect the frozen-build spec, entry points, registries,
  subprocess launch arguments, and runtime callback registration.
- The semantic edge sets are curated from the production wiring at the target. They are
  mechanically enumerated once declared, but declaration is a human judgement. A
  reviewer must compare every changed telemetry producer, command producer, topic,
  callback registration, descriptor/config loader, and shutdown owner against these
  sets; renamed or newly introduced paths can otherwise escape.
- This is not interprocedural taint analysis. It does not prove which tuple field,
  timestamp, status, descriptor, or receipt value reaches a predicate. The adversarial
  round must trace actual values from readings and commands to energizing writes, and
  from OFF outcomes to persisted receipts and operator truth.
- Static guard detection is bounded by governance/docs directories, filename markers,
  and known AST/repository-scan markers. A novel guard shape needs human classification.
- The three-dot Git comparison uses the merge base. It reports PR change membership,
  not authorship, review quality, or whether a changed line is behaviorally reachable.
- The manifest cannot close physical hardware, target-Windows, frozen-artifact,
  independent final-element, or laboratory acceptance gates.

## Re-run

Check out the frozen target so it is `HEAD`, then run:

```powershell
$env:PYTHONPATH = "$PWD\src"; python tools/generate_hazard_slice.py --base f5d6434d20dffae62c9f03fbc12f68b03f48351b --target <target-sha>
$env:PYTHONPATH = "$PWD\src"; python tools/generate_hazard_slice.py --base f5d6434d20dffae62c9f03fbc12f68b03f48351b --target <target-sha> --check
```

The generator refuses a target other than the checked-out `HEAD`, so the AST and
non-Python path inventory cannot silently describe different bytes.

## Declared entries

| Path | Inclusion edge(s) | Changed by PR? |
| --- | --- | --- |
| `.github/workflows/docs-gate.yml` | changed guard/governance evidence | yes |
| `.github/workflows/main.yml` | changed guard/governance evidence | yes |
| `.github/workflows/nightly.yml` | changed guard/governance evidence | yes |
| `.github/workflows/windows-onedir-smoke.yml` | changed guard/governance evidence | yes |
| `AGENTS.md` | changed guard/governance evidence | yes |
| `build_scripts/build.bat` | dynamic/frozen-build path | yes |
| `build_scripts/build.sh` | dynamic/frozen-build path | yes |
| `build_scripts/cryodaq.spec` | dynamic/frozen-build path | yes |
| `build_scripts/post_build.py` | dynamic/frozen-build path | yes |
| `build_scripts/windows_onedir_smoke.py` | dynamic/frozen-build path | yes |
| `config/alarms_v3.yaml` | data-flow/config/identity input | yes |
| `config/channel_descriptors.local.yaml.example` | data-flow/config/identity input | yes |
| `config/channel_descriptors.yaml` | data-flow/config/identity input | yes |
| `config/channels.yaml` | data-flow/config/identity input | no |
| `config/cooldown.yaml` | data-flow/config/identity input | no |
| `config/housekeeping.yaml` | data-flow/config/identity input | no |
| `config/instruments.local.yaml.example` | data-flow/config/identity input | yes |
| `config/instruments.yaml` | data-flow/config/identity input | yes |
| `config/interlocks.yaml` | data-flow/config/identity input | yes |
| `config/physical_alarms.yaml` | data-flow/config/identity input | yes |
| `config/safety.yaml` | data-flow/config/identity input | yes |
| `create_shortcut.py` | launcher/shutdown/process-death path | yes |
| `docs/CLAIM_CORRECTIONS.md` | changed guard/governance evidence | yes |
| `docs/DECISIONS.md` | changed guard/governance evidence | yes |
| `docs/HAZARD_SLICE.md` | manifest governance | yes |
| `docs/MONTANA_IMPLEMENTATION_AGENT_SPEC.md` | changed guard/governance evidence | yes |
| `docs/OPEN_CELLS.md` | changed guard/governance evidence | yes |
| `docs/ORCHESTRATION.md` | changed guard/governance evidence | yes |
| `governance/agent_context_schema.yaml` | changed guard/governance evidence | yes |
| `governance/agent_preventions.yaml` | changed guard/governance evidence | yes |
| `governance/agent_preventions_baseline.json` | changed guard/governance evidence | yes |
| `governance/publication_disposition_receipts.json` | changed guard/governance evidence | yes |
| `governance/red_reproductions/alarm_mixed_selector_027.json` | changed guard/governance evidence | yes |
| `governance/red_reproductions/alarm_phase_elapsed_subcondition_026.json` | changed guard/governance evidence | yes |
| `governance/red_reproductions/alarm_unknown_as_clear_033.json` | changed guard/governance evidence | yes |
| `governance/red_reproductions/alarm_unknown_as_clear_false_green_201.json` | changed guard/governance evidence | yes |
| `pyproject.toml` | dynamic/frozen-build path | yes |
| `requirements-lock.txt` | dynamic/frozen-build path | yes |
| `scripts/soak_mock_stack.py` | import consumer | yes |
| `scripts/soak_mock_stack_runner.py` | import consumer | yes |
| `src/cryodaq/__main__.py` | import consumer; launcher/shutdown/process-death path | no |
| `src/cryodaq/_frozen_main.py` | import consumer; launcher/shutdown/process-death path; dynamic/frozen-build path | yes |
| `src/cryodaq/analytics/cooldown_predictor.py` | data-flow/config/identity input | yes |
| `src/cryodaq/analytics/cooldown_service.py` | data-flow/config/identity input | yes |
| `src/cryodaq/channels/__init__.py` | data-flow/config/identity input | yes |
| `src/cryodaq/channels/config.py` | data-flow/config/identity input | yes |
| `src/cryodaq/channels/descriptors.py` | data-flow/config/identity input | yes |
| `src/cryodaq/channels/live_display.py` | data-flow/config/identity input | yes |
| `src/cryodaq/channels/persistence.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/alarm_config.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/alarm_providers.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/alarm_v2.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/broker.py` | data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/core/channel_manager.py` | data-flow/config/identity input | no |
| `src/cryodaq/core/channel_state.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/command_authority.py` | IPC/message-bus path | yes |
| `src/cryodaq/core/command_reply_contract.py` | IPC/message-bus path | yes |
| `src/cryodaq/core/descriptor_transport.py` | data-flow/config/identity input; IPC/message-bus path | yes |
| `src/cryodaq/core/disk_monitor.py` | data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/core/event_bus.py` | data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/core/event_logger.py` | data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/core/housekeeping.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/interlock.py` | data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/core/physical_alarms_config.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/physical_policy.py` | data-flow/config/identity input | yes |
| `src/cryodaq/core/rate_estimator.py` | data-flow/config/identity input | no |
| `src/cryodaq/core/safe_command_ipc.py` | IPC/message-bus path | yes |
| `src/cryodaq/core/safety_broker.py` | data-flow/config/identity input; callback/registry path | no |
| `src/cryodaq/core/safety_manager.py` | hazard-symbol seed; data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/core/safety_pattern_liveness.py` | import consumer; data-flow/config/identity input | yes |
| `src/cryodaq/core/scheduler.py` | hazard-symbol seed; data-flow/config/identity input | yes |
| `src/cryodaq/core/shutdown_settlement.py` | launcher/shutdown/process-death path | yes |
| `src/cryodaq/core/smu_channel.py` | data-flow/config/identity input | no |
| `src/cryodaq/core/zmq_bridge.py` | IPC/message-bus path; launcher/shutdown/process-death path | yes |
| `src/cryodaq/core/zmq_endpoints.py` | IPC/message-bus path; launcher/shutdown/process-death path | yes |
| `src/cryodaq/core/zmq_subprocess.py` | IPC/message-bus path; launcher/shutdown/process-death path | yes |
| `src/cryodaq/drivers/__init__.py` | data-flow/config/identity input | no |
| `src/cryodaq/drivers/base.py` | data-flow/config/identity input | no |
| `src/cryodaq/drivers/contracts.py` | hazard-symbol seed; data-flow/config/identity input; OFF evidence/operator truth | yes |
| `src/cryodaq/drivers/instruments/__init__.py` | data-flow/config/identity input | no |
| `src/cryodaq/drivers/instruments/etalon_multiline.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/instruments/keithley_2604b.py` | hazard-symbol seed; data-flow/config/identity input | yes |
| `src/cryodaq/drivers/instruments/lakeshore_218s.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/instruments/thyracont_vsp63d.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/passive_extensions/__init__.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/passive_extensions/asc_reference_tcp.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/registry.py` | import consumer; data-flow/config/identity input; callback/registry path; dynamic/frozen-build path | yes |
| `src/cryodaq/drivers/transport/__init__.py` | data-flow/config/identity input | no |
| `src/cryodaq/drivers/transport/gpib.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/transport/serial.py` | data-flow/config/identity input | yes |
| `src/cryodaq/drivers/transport/tcp.py` | data-flow/config/identity input | no |
| `src/cryodaq/drivers/transport/usbtmc.py` | data-flow/config/identity input | yes |
| `src/cryodaq/engine.py` | hazard-symbol seed; data-flow/config/identity input; IPC/message-bus path; callback/registry path; OFF evidence/operator truth; launcher/shutdown/process-death path | yes |
| `src/cryodaq/engine_wiring/operator_safety_snapshot.py` | hazard-symbol seed; OFF evidence/operator truth | yes |
| `src/cryodaq/engine_wiring/operator_snapshot_authorities.py` | hazard-symbol seed; OFF evidence/operator truth | yes |
| `src/cryodaq/engine_wiring/operator_snapshot_composer.py` | hazard-symbol seed; OFF evidence/operator truth | yes |
| `src/cryodaq/engine_wiring/operator_snapshot_live_authorities.py` | hazard-symbol seed; OFF evidence/operator truth | yes |
| `src/cryodaq/engine_wiring/operator_snapshot_production.py` | import consumer; OFF evidence/operator truth | yes |
| `src/cryodaq/engine_wiring/operator_snapshot_publisher.py` | IPC/message-bus path; OFF evidence/operator truth | yes |
| `src/cryodaq/engine_wiring/runtime_tasks.py` | data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/engine_wiring/supervision.py` | import consumer; data-flow/config/identity input; callback/registry path | yes |
| `src/cryodaq/gui/__main__.py` | import consumer | no |
| `src/cryodaq/gui/app.py` | import consumer; launcher/shutdown/process-death path | yes |
| `src/cryodaq/gui/first_run_config.py` | import consumer | yes |
| `src/cryodaq/gui/first_run_wizard.py` | import consumer | yes |
| `src/cryodaq/gui/shell/bottom_status_bar.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/gui/shell/main_window_v2.py` | import consumer; OFF evidence/operator truth | yes |
| `src/cryodaq/gui/shell/overlays/keithley_panel.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/gui/shell/top_watch_bar.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/gui/shell/views/operator_display.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/gui/state/operator_snapshot_ingress.py` | IPC/message-bus path; OFF evidence/operator truth | yes |
| `src/cryodaq/gui/state/operator_view_models.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/gui/zmq_client.py` | IPC/message-bus path | yes |
| `src/cryodaq/health/infra_authority.py` | import consumer | yes |
| `src/cryodaq/instance_lock.py` | launcher/shutdown/process-death path | yes |
| `src/cryodaq/launcher.py` | hazard-symbol seed; IPC/message-bus path; OFF evidence/operator truth; launcher/shutdown/process-death path | yes |
| `src/cryodaq/operator_snapshot.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/operator_snapshot_transport.py` | IPC/message-bus path; OFF evidence/operator truth | yes |
| `src/cryodaq/paths.py` | dynamic/frozen-build path | yes |
| `src/cryodaq/replay_engine/legacy_channel_maps.py` | data-flow/config/identity input | no |
| `src/cryodaq/replay_engine/operator_snapshot_session.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/replay_engine/server.py` | IPC/message-bus path | yes |
| `src/cryodaq/replay_engine/sources.py` | data-flow/config/identity input | yes |
| `src/cryodaq/storage/broker_replay.py` | data-flow/config/identity input | yes |
| `src/cryodaq/storage/channel_descriptors.py` | data-flow/config/identity input | yes |
| `src/cryodaq/storage/descriptor_archive.py` | data-flow/config/identity input | yes |
| `src/cryodaq/storage/operator_snapshot_revision.py` | OFF evidence/operator truth | yes |
| `src/cryodaq/storage/persistence_spool.py` | data-flow/config/identity input | yes |
| `src/cryodaq/storage/replay.py` | data-flow/config/identity input | yes |
| `src/cryodaq/storage/sqlite_writer.py` | data-flow/config/identity input; callback/registry path | yes |
| `start.bat` | launcher/shutdown/process-death path | no |
| `start.sh` | launcher/shutdown/process-death path | no |
| `start_mock.bat` | launcher/shutdown/process-death path | no |
| `start_mock.sh` | launcher/shutdown/process-death path | no |
| `tests/agents/assistant/test_c1_engine_adapter_seal.py` | changed guard/governance evidence | yes |
| `tests/agents/assistant/test_engine_query_client.py` | changed guard/governance evidence | yes |
| `tests/agents/assistant/test_periodic_png_recovery.py` | changed guard/governance evidence | yes |
| `tests/agents/test_engine_multiline_burst_command.py` | import consumer | yes |
| `tests/agents/test_engine_rag_rebuild_command.py` | import consumer | yes |
| `tests/analytics/test_c2_descriptor_selection_guard.py` | changed guard/governance evidence | yes |
| `tests/analytics/test_cooldown_service_sweepA.py` | changed guard/governance evidence | yes |
| `tests/channels/test_inert_activation.py` | changed guard/governance evidence | yes |
| `tests/core/test_alarm_reference_liveness.py` | import consumer | yes |
| `tests/core/test_annunciation_protocol.py` | import consumer | yes |
| `tests/core/test_audit_fixes.py` | import consumer | yes |
| `tests/core/test_calibration_commands.py` | import consumer | no |
| `tests/core/test_cooldown_alarm_v0_55_12.py` | import consumer | no |
| `tests/core/test_engine_alarm_ring_buffer.py` | import consumer | yes |
| `tests/core/test_engine_audible_faults.py` | import consumer | yes |
| `tests/core/test_engine_b3_command_context.py` | import consumer | yes |
| `tests/core/test_engine_b3_structure.py` | import consumer; changed guard/governance evidence | yes |
| `tests/core/test_engine_command_ingress_recovery_authority.py` | import consumer; changed guard/governance evidence | yes |
| `tests/core/test_engine_dual_channel.py` | import consumer | yes |
| `tests/core/test_engine_event_relay.py` | changed guard/governance evidence | yes |
| `tests/core/test_engine_force_kill.py` | import consumer | yes |
| `tests/core/test_engine_launch_authority.py` | import consumer | yes |
| `tests/core/test_engine_leak_rate_command.py` | import consumer | yes |
| `tests/core/test_engine_task_supervision.py` | import consumer | yes |
| `tests/core/test_experiment_commands.py` | import consumer | yes |
| `tests/core/test_f23_f24_f25_misc.py` | import consumer | yes |
| `tests/core/test_housekeeping.py` | import consumer | yes |
| `tests/core/test_interlock_action_dispatch.py` | import consumer | yes |
| `tests/core/test_interlock_nan_debounce.py` | import consumer | no |
| `tests/core/test_keithley_channel_state_publish.py` | import consumer | yes |
| `tests/core/test_nonfinite_setpoints.py` | import consumer | no |
| `tests/core/test_operator_log.py` | import consumer | yes |
| `tests/core/test_operator_snapshot_subprocess_ingress.py` | changed guard/governance evidence | yes |
| `tests/core/test_p0_fixes.py` | import consumer | yes |
| `tests/core/test_p1_fixes.py` | import consumer | yes |
| `tests/core/test_periodic_legacy_cutover.py` | import consumer; changed guard/governance evidence | yes |
| `tests/core/test_persistence_ordering.py` | import consumer | yes |
| `tests/core/test_physical_alarm_exactness.py` | changed guard/governance evidence | yes |
| `tests/core/test_reviewed_source_disconnect.py` | import consumer | yes |
| `tests/core/test_reviewed_source_production_lifecycle.py` | import consumer | yes |
| `tests/core/test_safe_off_fail_closed.py` | import consumer | no |
| `tests/core/test_safety_dual_channel.py` | import consumer | yes |
| `tests/core/test_safety_fixes.py` | import consumer | yes |
| `tests/core/test_safety_heartbeat_identity.py` | import consumer | yes |
| `tests/core/test_safety_manager.py` | import consumer | yes |
| `tests/core/test_safety_operator_snapshot_owner.py` | import consumer | yes |
| `tests/core/test_safety_pattern_liveness.py` | import consumer | yes |
| `tests/core/test_safety_rate_estimator_config.py` | import consumer | no |
| `tests/core/test_safety_safetyfix_wave.py` | import consumer | yes |
| `tests/core/test_safety_set_target.py` | import consumer | no |
| `tests/core/test_safety_wdog_reconcile.py` | import consumer | yes |
| `tests/core/test_scheduler.py` | import consumer | yes |
| `tests/core/test_scheduler_commit_receipts.py` | import consumer | yes |
| `tests/core/test_sensor_diagnostics_wiring.py` | changed guard/governance evidence | yes |
| `tests/core/test_source_off_result_consumers.py` | import consumer | yes |
| `tests/core/test_startup_safety_liveness_gate.py` | import consumer | yes |
| `tests/core/test_vacuum_guard.py` | changed guard/governance evidence | yes |
| `tests/core/test_zmq_command_server_supervision.py` | import consumer | yes |
| `tests/core/test_zmq_subprocess.py` | import consumer; changed guard/governance evidence | yes |
| `tests/docs/__init__.py` | changed guard/governance evidence | yes |
| `tests/docs/test_docs_freshness.py` | changed guard/governance evidence | yes |
| `tests/driver_conformance/__init__.py` | import consumer; changed guard/governance evidence | yes |
| `tests/driver_conformance/passive.py` | import consumer; changed guard/governance evidence | yes |
| `tests/drivers/test_capability_contracts.py` | import consumer | yes |
| `tests/drivers/test_engine_registry_adoption.py` | import consumer; changed guard/governance evidence | yes |
| `tests/drivers/test_gpib_bus_lock.py` | import consumer | yes |
| `tests/drivers/test_keithley_2604b.py` | import consumer | yes |
| `tests/drivers/test_keithley_connect_safety.py` | import consumer | yes |
| `tests/drivers/test_keithley_disconnect_verified_off.py` | import consumer | yes |
| `tests/drivers/test_keithley_dual_channel.py` | import consumer | no |
| `tests/drivers/test_keithley_safety.py` | import consumer | yes |
| `tests/drivers/test_keithley_safetyfix_wave.py` | import consumer | yes |
| `tests/drivers/test_keithley_watchdog.py` | import consumer | yes |
| `tests/drivers/test_keithley_watchdog_smoke.py` | import consumer | yes |
| `tests/drivers/test_multiline_reconfigure.py` | import consumer | yes |
| `tests/drivers/test_passive_conformance_harness.py` | import consumer; changed guard/governance evidence | yes |
| `tests/drivers/test_registry.py` | import consumer | yes |
| `tests/drivers/test_reviewed_source_roster.py` | import consumer | yes |
| `tests/drivers/test_shared_bus_contract.py` | import consumer | yes |
| `tests/drivers/test_source_control_contracts.py` | import consumer | yes |
| `tests/e2e/test_d7_4_phase1_real_socket.py` | import consumer | yes |
| `tests/e2e/test_d7_4_phase2_acceptance.py` | import consumer; changed guard/governance evidence | yes |
| `tests/engine_wiring/test_engine_recording_lifecycle_wiring.py` | import consumer | yes |
| `tests/engine_wiring/test_operator_safety_live_authority.py` | import consumer | yes |
| `tests/engine_wiring/test_operator_safety_snapshot.py` | import consumer | yes |
| `tests/engine_wiring/test_operator_snapshot_authorities.py` | import consumer; changed guard/governance evidence | yes |
| `tests/engine_wiring/test_operator_snapshot_composer.py` | import consumer | yes |
| `tests/engine_wiring/test_operator_snapshot_live_authorities.py` | import consumer | yes |
| `tests/engine_wiring/test_operator_snapshot_production.py` | import consumer | yes |
| `tests/engine_wiring/test_operator_snapshot_publisher.py` | changed guard/governance evidence | yes |
| `tests/governance/guard_coverage_inventory.json` | changed guard/governance evidence | yes |
| `tests/governance/test_active_guard_execution.py` | changed guard/governance evidence | yes |
| `tests/governance/test_agent_context_contract.py` | changed guard/governance evidence | yes |
| `tests/governance/test_agent_formatter_gate.py` | changed guard/governance evidence | yes |
| `tests/governance/test_agent_guidance_cross_references.py` | changed guard/governance evidence | yes |
| `tests/governance/test_agent_preventions.py` | changed guard/governance evidence | yes |
| `tests/governance/test_candidate_evidence_binding.py` | changed guard/governance evidence | yes |
| `tests/governance/test_guard_coverage.py` | changed guard/governance evidence | yes |
| `tests/governance/test_montana_integration_contract.py` | changed guard/governance evidence | yes |
| `tests/governance/test_prevention_removal_baseline.py` | changed guard/governance evidence | yes |
| `tests/governance/test_receipt_guard_eol.py` | changed guard/governance evidence | yes |
| `tests/governance/test_red_reproduction.py` | changed guard/governance evidence | yes |
| `tests/governance/test_source_off_result_test_doubles.py` | changed guard/governance evidence | yes |
| `tests/governance/test_standing_lane_authority.py` | changed guard/governance evidence | yes |
| `tests/gui/shell/test_accent_decoupling.py` | import consumer | no |
| `tests/gui/shell/test_bottom_status_bar_fault_beep.py` | changed guard/governance evidence | yes |
| `tests/gui/shell/test_command_outcome.py` | changed guard/governance evidence | yes |
| `tests/gui/shell/test_d7_1b_qualified_ingress.py` | import consumer | yes |
| `tests/gui/shell/test_d7_1b_repair.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_alarms_wiring.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_analytics_adapter.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_archive_wiring.py` | import consumer | no |
| `tests/gui/shell/test_main_window_v2_calibration_wiring.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_conductivity_wiring.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_disk_evidence.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_experiment_wiring.py` | import consumer | no |
| `tests/gui/shell/test_main_window_v2_f4_lazy_replay.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_instruments_wiring.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_keithley_wiring.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_operator_log_wiring.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_replay_safety_gate.py` | import consumer | yes |
| `tests/gui/shell/test_main_window_v2_safety_staleness.py` | import consumer | yes |
| `tests/gui/shell/test_navigation.py` | changed guard/governance evidence | yes |
| `tests/gui/shell/test_top_watch_bar_annunciation.py` | changed guard/governance evidence | yes |
| `tests/gui/state/test_operator_snapshot_ingress.py` | changed guard/governance evidence | yes |
| `tests/gui/state/test_operator_snapshot_runtime_roots.py` | import consumer | yes |
| `tests/gui/test_app_bridge_watchdog.py` | import consumer | yes |
| `tests/gui/test_app_instance_lock.py` | import consumer; changed guard/governance evidence | yes |
| `tests/gui/test_app_palette.py` | import consumer | no |
| `tests/gui/test_f35_descriptor_specialized_routing.py` | import consumer | yes |
| `tests/gui/test_first_run_config.py` | import consumer | yes |
| `tests/gui/test_first_run_wizard.py` | import consumer | yes |
| `tests/gui/test_fonts.py` | import consumer | no |
| `tests/gui/test_launcher_theme_switch.py` | import consumer | yes |
| `tests/gui/test_zmq_client_data_flow_watchdog.py` | import consumer | yes |
| `tests/gui/test_zmq_client_mutation_handshake.py` | import consumer | yes |
| `tests/gui/test_zmq_client_shutdown.py` | import consumer | yes |
| `tests/health/test_inert_import_boundary.py` | changed guard/governance evidence | yes |
| `tests/health/test_infra_authority.py` | import consumer | yes |
| `tests/integration/test_analytics_contract.py` | import consumer | yes |
| `tests/integration/test_diagnostic_alarm_pipeline.py` | import consumer | no |
| `tests/integration/test_f35_reference_driver_e2e.py` | import consumer; changed guard/governance evidence | yes |
| `tests/integration/test_launcher_shutdown_ownership.py` | import consumer | yes |
| `tests/integration/test_soak_periodic_artifact_multiprocess.py` | import consumer | yes |
| `tests/launcher/test_first_run_wizard_startup.py` | import consumer | yes |
| `tests/launcher/test_launcher_descriptor_poison_guards.py` | import consumer; changed guard/governance evidence | yes |
| `tests/launcher/test_launcher_replay.py` | import consumer; changed guard/governance evidence | yes |
| `tests/launcher/test_predictor_bootstrap.py` | import consumer | yes |
| `tests/periodic/test_periodic_delivery_contract.py` | changed guard/governance evidence | yes |
| `tests/periodic/test_soak_periodic_delivery.py` | import consumer | yes |
| `tests/replay_engine/test_operator_snapshot_session.py` | changed guard/governance evidence | yes |
| `tests/scripts/test_soak_mock_fixture.py` | import consumer | yes |
| `tests/scripts/test_soak_mock_stack.py` | import consumer | yes |
| `tests/scripts/test_soak_mock_stack_runner.py` | import consumer; changed guard/governance evidence | yes |
| `tests/scripts/test_soak_mock_stack_runner_artifact_capability.py` | import consumer | yes |
| `tests/scripts/test_soak_mock_stack_runner_bridge_handshake.py` | import consumer | yes |
| `tests/scripts/test_soak_mock_stack_runner_joined_receipts.py` | import consumer | yes |
| `tests/scripts/test_soak_mock_stack_runner_process_authority.py` | import consumer | yes |
| `tests/sinks/test_engine_shutdown_drains_dispatch.py` | import consumer | yes |
| `tests/sinks/test_engine_summary_metadata_key.py` | import consumer | no |
| `tests/storage/test_cold_rotation.py` | changed guard/governance evidence | yes |
| `tests/storage/test_cold_rotation_wiring.py` | import consumer | yes |
| `tests/storage/test_disk_full_handling.py` | import consumer | yes |
| `tests/storage/test_engine_live_descriptor_activation.py` | import consumer | yes |
| `tests/storage/test_live_commit_receipts.py` | changed guard/governance evidence | yes |
| `tests/storage/test_operator_log_idempotency.py` | import consumer; changed guard/governance evidence | yes |
| `tests/storage/test_scheduler_persistence_cancellation.py` | import consumer | yes |
| `tests/test_c2_repo_wide_spelling_sweep.py` | changed guard/governance evidence | yes |
| `tests/test_engine_config_error.py` | import consumer | yes |
| `tests/test_engine_cooldown_history.py` | import consumer | no |
| `tests/test_engine_import_surface.py` | import consumer; changed guard/governance evidence | yes |
| `tests/test_frozen_entry.py` | import consumer; dynamic/frozen-build path; changed guard/governance evidence | yes |
| `tests/test_launcher_backoff.py` | import consumer | yes |
| `tests/test_launcher_bridge_handshake.py` | import consumer | yes |
| `tests/test_launcher_engine_stderr.py` | import consumer | yes |
| `tests/test_launcher_periodic_runtime.py` | import consumer | yes |
| `tests/test_launcher_report_runtime.py` | import consumer | yes |
| `tests/test_launcher_shutdown_ownership.py` | import consumer | yes |
| `tests/test_launcher_signals.py` | import consumer | yes |
| `tests/test_launcher_soak_artifact_capability.py` | import consumer | yes |
| `tests/test_launcher_theme_menu.py` | changed guard/governance evidence | yes |
| `tests/test_operator_snapshot.py` | changed guard/governance evidence | yes |
| `tests/test_paths_frozen.py` | dynamic/frozen-build path | yes |
| `tests/test_pyinstaller_spec.py` | import consumer; dynamic/frozen-build path; changed guard/governance evidence | yes |
| `tests/test_rest_api.py` | import consumer | yes |
| `tests/test_windows_onedir_smoke_contract.py` | dynamic/frozen-build path | yes |
| `tests/tools/test_force_phase.py` | import consumer | yes |
| `tools/agent_context_gate.py` | changed guard/governance evidence | yes |
| `tools/candidate_evidence.py` | changed guard/governance evidence | yes |
| `tools/ci_active_checkout_runner.py` | changed guard/governance evidence | yes |
| `tools/ci_candidate_evidence.py` | changed guard/governance evidence | yes |
| `tools/ci_candidate_runner.py` | changed guard/governance evidence | yes |
| `tools/ci_execution_roots.py` | changed guard/governance evidence | yes |
| `tools/ci_guard_execution.py` | changed guard/governance evidence | yes |
| `tools/generate_hazard_slice.py` | manifest governance | yes |
| `tools/governance_contract.py` | changed guard/governance evidence | yes |
| `tools/guard_coverage.py` | changed guard/governance evidence | yes |
| `tools/montana_candidate_gate.py` | changed guard/governance evidence | yes |
| `tools/red_reproduction.py` | changed guard/governance evidence | yes |
| `tools/standing_lane_authority.py` | changed guard/governance evidence | yes |
| `tsp/cryodaq_wdog.lua` | launcher/shutdown/process-death path; dynamic/frozen-build path | yes |
