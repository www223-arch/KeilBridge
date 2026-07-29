# GUI Operation Feedback Design

## Goal

Make every GUI hardware operation visibly accountable from start to finish without
interruptive success dialogs or Windows console flashes. Progress must communicate
real lifecycle stages and must never invent a percentage that OpenOCD did not report.

## Scope

This change covers GUI connection checks, complete Flash readback, firmware flash,
RTT startup/capture/stop, operation setup failures, result presentation, and the
Windows launch behavior of GUI-owned OpenOCD processes. CLI output contracts and
hardware semantics remain unchanged.

## Current Task Panel

A fixed-height current-task panel sits above the right-side output notebook. It is
always present so starting or completing a task never shifts the surrounding layout.
The panel contains:

- task name and explicit state text;
- current lifecycle stage;
- a progress bar;
- elapsed time;
- a concise result or error summary;
- `复制错误` and `打开日志` actions when relevant.

The panel shows only the latest task. Persistent task history remains in the existing
per-session log directories.

## States And Progress

The presentation model has these states:

- `idle`: waiting for an operation;
- `running`: active hardware work;
- `succeeded`: completed and verified;
- `failed`: operation or validation failure;
- `stopping`: resource cleanup is in progress;
- `incomplete`: cleanup could not be confirmed.

One-shot operations use these stages:

1. preparing and validating configuration;
2. running OpenOCD;
3. analyzing or verifying the result;
4. cleaning up resources;
5. complete.

Stages controlled by KeilTool use determinate milestone values. Time spent inside an
external OpenOCD command uses an indeterminate progress bar unless OpenOCD provides a
reliable byte count. Completion alone sets the bar to 100 percent. The UI must not
advance a fake time-based percentage.

RTT uses `准备配置`, `扫描 RTT 控制块`, `正在采集`, and `正在停止`. During continuous
capture the bar remains an activity indicator; elapsed time, received bytes, and line
count provide concrete live progress.

## Result And Error Behavior

Normal success does not open a dialog. The task panel becomes green and shows the
verified result, elapsed time, and artifact or log location.

Failure does not rely on a dialog. The task panel becomes red, shows the failed stage,
summary, and OpenOCD return code when available, enables error copying, and selects the
`OpenOCD 输出` tab. Full stdout, stderr, findings, and paths remain in the existing log
surface and session directory.

Failures before a worker starts, including invalid files, unresolved targets, invalid
memory ranges, and log creation failures, use the same task panel. They do not create
empty hardware sessions.

Dialogs remain only where an explicit decision is required:

- confirming a Flash write;
- accepting or rejecting externally changed firmware;
- confirming shutdown while hardware is busy;
- retrying or abandoning settings persistence.

Cleanup failures remain prominent in the task panel and continue to block conflicting
hardware work until ownership is safely released.

## Process Launch Behavior

GUI-owned OpenOCD processes for one-shot operations and RTT use a shared process-launch
policy. On Windows it supplies `CREATE_NO_WINDOW`; on other platforms it supplies no
Windows-specific flags. This prevents console windows from flashing while preserving
captured stdout and stderr.

CLI commands keep their current terminal behavior. Tests that inject fake process
factories remain supported: launch options are ordinary keyword arguments and test
factories may inspect them.

## Components

- `OperationFeedback` is a UI-independent latest-task model containing task, state,
  stage, summary, timing, progress mode/value, log path, and copyable error detail.
- `OperationStatusPane` renders that model with stable dimensions and semantic styles.
- `KeilToolGui` updates the model at existing lifecycle boundaries and owns the elapsed
  timer refresh.
- `OutputNotebook` exposes a method to select the OpenOCD tab on failure.
- A core process-launch helper owns cross-platform background-process keyword options.

The existing `TaskGate`, one-shot lifecycle controller, RTT lifecycle controller, and
session logs remain the authorities for resource ownership and cleanup. The feedback
model observes them; it does not create a second lifecycle state machine.

## Accessibility And Layout

Color is accompanied by explicit state text. The task panel has a stable minimum
height, constrained controls, and no nested cards. Long paths and errors are summarized
in the panel and remain fully copyable through actions and logs. The existing palette
is extended with restrained running, success, and failure treatments.

## Verification

Tests cover:

- feedback model transitions and elapsed timing;
- determinate versus indeterminate progress semantics;
- one-shot and RTT lifecycle integration;
- success without informational dialogs;
- setup and worker failures shown in the panel;
- automatic OpenOCD-tab selection and copyable error details;
- Windows `CREATE_NO_WINDOW` behavior and non-Windows compatibility;
- unchanged CLI output behavior;
- GUI layout smoke coverage at the existing supported window size.

Runtime verification launches the GUI, exercises non-hardware validation failures, and
visually checks stable layout and task states. Hardware writes are not performed as part
of UI verification.
