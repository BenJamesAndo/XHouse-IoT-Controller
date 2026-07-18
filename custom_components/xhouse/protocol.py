from __future__ import annotations

from typing import Any

# menuCode item id holding the wing count: 0x00 = double, 0x01 = single.
GATE_MODE_MENU_ITEM = 0x3E
GATE_MODE_SINGLE = "single"
GATE_MODE_DOUBLE = "double"


def parse_gate_mode(menu_code_hex: str | None) -> str:
    """Return the gate wing mode from the EGA/EGB menuCode blob."""
    if menu_code_hex and len(menu_code_hex) >= 10:
        body = menu_code_hex[10:]
        try:
            for i in range(0, len(body) - 3, 4):
                if int(body[i:i + 2], 16) == GATE_MODE_MENU_ITEM:
                    value = int(body[i + 2:i + 4], 16)
                    return GATE_MODE_SINGLE if value == 0x01 else GATE_MODE_DOUBLE
        except ValueError:
            pass
    return GATE_MODE_DOUBLE


def parse_ega_status(
    status_hex: str | None, gate_mode: str = GATE_MODE_DOUBLE
) -> dict[str, Any] | None:
    """Parse an EGA swing-gate status frame."""
    if not status_hex or len(status_hex) < 38:
        return None

    try:
        header = int(status_hex[0:2], 16)
        door_enum = int(status_hex[10:12], 16)
        dir_a = int(status_hex[12:14], 16)
        dir_b = int(status_hex[14:16], 16)
        pos_left = int(status_hex[34:36], 16)
        pos_right = int(status_hex[36:38], 16)
    except (TypeError, ValueError):
        return None

    if gate_mode == GATE_MODE_SINGLE:
        position = max(pos_left, pos_right)
        if door_enum == 0x02:
            state = "opening"
        elif door_enum == 0x03:
            state = "closing"
        elif dir_b == 0x01:
            state = "opening"
        elif dir_b == 0x00:
            state = "closing"
        elif pos_left == 0 and pos_right == 0:
            state = "closed"
        elif pos_left > 0 or pos_right > 0:
            state = "open"
        else:
            state = "closed"
    else:
        position = (pos_left + pos_right) // 2
        if door_enum == 0x02:
            state = "opening"
        elif door_enum == 0x03:
            state = "closing"
        elif door_enum == 0x01 or (pos_left == 0 and pos_right == 0):
            state = "closed"
        elif header == 0x41 and 0x01 in (dir_a, dir_b):
            state = "opening"
        elif header == 0x41 and 0x00 in (dir_a, dir_b):
            state = "closing"
        else:
            state = "open"

    return {
        "state": state,
        "position": position,
        "pos_left": pos_left,
        "pos_right": pos_right,
    }


# EGB/PGB door-state enum at status offset [10:12].
_EGB_STATE_BY_CODE = {
    0x00: "closing",
    0x01: "opening",
    0x02: "open",
    0x03: "closed",
}


def parse_egb_status(status_hex: str | None) -> dict[str, Any] | None:
    """Parse an EGB/PGB barrier/sliding-gate status frame, including EGB1900.

    Door state is at offset [10:12] (see ``_EGB_STATE_BY_CODE``); position, when
    present, is at [18:20].
    """
    if not status_hex or len(status_hex) < 12:
        return None

    try:
        state_code = int(status_hex[10:12], 16)
    except (TypeError, ValueError):
        return None

    state = _EGB_STATE_BY_CODE.get(state_code)
    if state is None:
        return None

    position: int | None = None
    if len(status_hex) >= 20:
        try:
            position = max(0, min(100, int(status_hex[18:20], 16)))
        except ValueError:
            position = None
    if position is None:
        if state == "open":
            position = 100
        elif state == "closed":
            position = 0

    return {"state": state, "position": position}
