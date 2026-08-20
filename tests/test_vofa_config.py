import json

import pytest

from keiltool.core.vofa_config import configure_vofa_1_3_connection


def _config() -> dict:
    return {
        "type": "config",
        "vnumber": 100,
        "ctx": {
            "wave_view": {
                "ctx": {
                    "left_panel": {
                        "ctx": {
                            "pal": {
                                "ctx": {
                                    "tcp_client": {
                                        "server_ip": "192.168.1.10",
                                        "server_port": "1346",
                                        "banner": "plot0",
                                    },
                                    "protocol_combo": "RawData",
                                    "link_type_combo": 0,
                                }
                            }
                        }
                    }
                }
            }
        },
    }


def test_configure_vofa_connection_updates_only_connection_fields_and_backs_up(tmp_path):
    path = tmp_path / "vofa+.config.json"
    original = _config()
    path.write_text(json.dumps(original), encoding="utf-8")

    result = configure_vofa_1_3_connection(path, "127.0.0.1", 1347)

    updated = json.loads(path.read_text(encoding="utf-8"))
    pal = updated["ctx"]["wave_view"]["ctx"]["left_panel"]["ctx"]["pal"]["ctx"]
    assert result.configured is True
    assert result.backup_path is not None
    assert json.loads(result.backup_path.read_text(encoding="utf-8")) == original
    assert pal["tcp_client"] == {
        "server_ip": "127.0.0.1",
        "server_port": "1347",
        "banner": "plot0",
    }
    assert pal["protocol_combo"] == "JustFloat"
    assert pal["link_type_combo"] == 2


def test_configure_vofa_connection_refuses_unknown_schema_without_rewriting(tmp_path):
    path = tmp_path / "vofa+.config.json"
    text = json.dumps({"type": "config", "vnumber": 140, "ctx": {}})
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="1.3"):
        configure_vofa_1_3_connection(path, "127.0.0.1", 1347)

    assert path.read_text(encoding="utf-8") == text
    assert not tuple(tmp_path.glob("*.keiltool-backup.json"))


def test_configure_vofa_connection_is_idempotent(tmp_path):
    path = tmp_path / "vofa+.config.json"
    path.write_text(json.dumps(_config()), encoding="utf-8")

    first = configure_vofa_1_3_connection(path, "127.0.0.1", 1347)
    second = configure_vofa_1_3_connection(path, "127.0.0.1", 1347)

    assert first.configured is True
    assert second.configured is True
    assert second.changed is False
    assert second.backup_path is None
