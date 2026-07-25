# Device Source Mode Design

## Goal

Prevent Keil project facts and a manually selected catalog device from being
mixed. The GUI must make the active source explicit and must never flash or
start RTT with stale facts from the inactive source.

## Modes

The workbench has two mutually exclusive device-source modes:

1. **Keil project**: Device, Target, flash/RAM facts, OpenOCD target, firmware,
   and derived configuration come from the selected Keil project and Target.
2. **Independent Device**: Device, flash/RAM facts, and OpenOCD target come from
   the device catalog. Project Target and project-derived firmware are empty.
   The user may then select a standalone firmware file for the chosen device.

Importing or selecting a Keil project activates Keil project mode. Selecting a
different Device explicitly activates Independent Device mode. Returning to
Keil project mode restores the previously selected project and Target and
re-resolves their facts.

## UI

A compact source selector next to the Device field exposes `Keil 工程` and
`独立 Device`. Device is disabled in Keil project mode and editable in
Independent Device mode. Source/status text states which source is active.

When a user attempts to choose a Device while a project is active, the UI
switches to Independent Device mode rather than displaying a value that the
backend ignores.

## State Transitions

- Keil project to Independent Device:
  - retain the project path only so the user can return to it;
  - clear the active Target;
  - clear project-derived firmware;
  - clear stale resolved facts before resolving the catalog Device.
- Independent Device to Keil project:
  - restore the project's Target selection;
  - reload project facts and project-derived firmware;
  - discard catalog-device facts from active runtime state.
- Loading a new project always activates Keil project mode.

All flash, connection-check, and RTT actions consume only the facts belonging
to the active mode.

## Safety And Errors

Independent Device mode cannot become ready until the catalog entry resolves
to sufficient OpenOCD/RAM facts. Switching modes stops neither an active flash
operation nor an RTT session silently: controls remain locked while an
operation is active. No confirmation dialog is required because the
project-derived firmware is cleared automatically and no destructive action is
started by switching modes.

## Verification

Automated GUI tests cover:

- project mode disables Device and uses project facts;
- switching to Independent Device clears Target, firmware, and stale facts;
- catalog facts become the only inputs to readiness and commands;
- switching back restores and re-resolves the project Target;
- a stale project firmware path cannot survive the switch;
- the existing projectless Device workflow remains functional.

The desktop shortcut must point at the worktree containing this implementation,
and the launched process must be restarted before manual verification.
