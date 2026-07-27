import pytest

from keiltool.gui.state import BusySessionError, SessionState, TaskGate


def test_rtt_blocks_flash_until_stopped():
    gate = TaskGate()
    gate.begin(SessionState.RTT)

    with pytest.raises(BusySessionError):
        gate.begin(SessionState.FLASH)

    gate.finish()
    gate.begin(SessionState.FLASH)

    assert gate.state is SessionState.FLASH


def test_failed_session_can_start_new_work():
    gate = TaskGate()
    gate.begin(SessionState.CONNECT)
    gate.fail()

    gate.begin(SessionState.RTT_SCAN)

    assert gate.state is SessionState.RTT_SCAN


def test_begin_rejects_non_work_state():
    with pytest.raises(ValueError, match="work state"):
        TaskGate().begin(SessionState.IDLE)


def test_flash_read_is_an_exclusive_work_state():
    gate = TaskGate()
    gate.begin(SessionState.FLASH_READ)

    with pytest.raises(BusySessionError):
        gate.begin(SessionState.CONNECT)

    assert gate.state is SessionState.FLASH_READ
