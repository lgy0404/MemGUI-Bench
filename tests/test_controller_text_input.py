from mobile_world.runtime import controller as controller_mod
from mobile_world.runtime.controller import AndroidController
from mobile_world.runtime.utils.helpers import AdbResponse


def _controller(device: str = "emulator-5554") -> AndroidController:
    controller = AndroidController.__new__(AndroidController)
    controller.device = device
    return controller


def test_text_input_activates_adb_keyboard_before_broadcast(monkeypatch):
    commands: list[str] = []
    state = {"ime": "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"}

    def fake_execute_adb(command, output=True, root_required=False, timeout=60):
        commands.append(command)
        if "settings get secure default_input_method" in command:
            return AdbResponse(success=True, output=state["ime"], command=command)
        if "pm list packages com.android.adbkeyboard" in command:
            return AdbResponse(
                success=True,
                output="package:com.android.adbkeyboard",
                command=command,
            )
        if "shell ime set com.android.adbkeyboard/.AdbIME" in command:
            state["ime"] = "com.android.adbkeyboard/.AdbIME"
        return AdbResponse(success=True, output="OK", command=command)

    monkeypatch.setattr(controller_mod, "execute_adb", fake_execute_adb)

    ret = _controller().text("Real Madrid")

    assert ret.success
    assert any("shell ime enable com.android.adbkeyboard/.AdbIME" in cmd for cmd in commands)
    assert any("shell ime set com.android.adbkeyboard/.AdbIME" in cmd for cmd in commands)
    assert any("ADB_INPUT_B64" in cmd and "UmVhbCBNYWRyaWQ=" in cmd for cmd in commands)
    assert not any("shell input text" in cmd for cmd in commands)


def test_text_input_falls_back_to_shell_input_when_adb_keyboard_missing(monkeypatch):
    commands: list[str] = []

    def fake_execute_adb(command, output=True, root_required=False, timeout=60):
        commands.append(command)
        if "settings get secure default_input_method" in command:
            return AdbResponse(
                success=True,
                output="com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME",
                command=command,
            )
        if "pm list packages com.android.adbkeyboard" in command:
            return AdbResponse(success=True, output="", command=command)
        return AdbResponse(success=True, output="OK", command=command)

    monkeypatch.setattr(controller_mod, "execute_adb", fake_execute_adb)

    ret = _controller().text("Real Madrid")

    assert ret.success
    assert any("shell input text Real%sMadrid" in cmd for cmd in commands)
    assert not any("ADB_INPUT_B64" in cmd for cmd in commands)
