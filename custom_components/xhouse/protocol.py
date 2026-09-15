from __future__ import annotations

from typing import Any

# menuCode item id holding the wing count: 0x00 = double, 0x01 = single.
GATE_MODE_MENU_ITEM = 0x3E
GATE_MODE_SINGLE = "single"
GATE_MODE_DOUBLE = "double"


def parse_battery_reply(status_hex: str | None) -> dict[str, Any] | None:
    """Extract backup-battery voltage/presence from an EGA ``status`` frame.

    These bytes are already present in the regular ``status`` property
    returned by ``wifi/getWifiProperties`` (the passive poll ``cover.py``
    already uses for door state) — no extra command needed. Confirmed
    empirically against a real EGA1800 board (firmware 2.0.5), wired per
    its spec sheet with 2x12V lead-acid in series (24V pack):

    - No battery wired: ``...00000000000000010000000B0D`` -> 0 V, byte 0.
    - Battery installed (mains on):    voltage byte -> 24.87 V, byte 1.
    - Same battery, mains removed:     voltage byte -> 24.79 V, byte 1.

    The presence byte did not change between mains on/off, only between no
    battery and battery installed, so it reflects wiring, not a live
    charging state — no live "charging" bit has been identified in this
    frame. This board's manual only documents a 2x12V-in-series backup
    (never a single 12V cell), so ``battery_present`` doesn't distinguish
    pack size — that's assumed fixed at 24V (see :func:`estimate_battery_soc`).
    """
    if not status_hex or len(status_hex) < 34:
        return None
    try:
        voltage = int(status_hex[20:24], 16) / 1000.0
        battery_present = int(status_hex[32:34], 16) != 0
    except ValueError:
        return None
    return {"voltage": voltage, "battery_present": battery_present}


# Open-circuit voltage -> state of charge for a resting 12V lead-acid
# battery (widely used approximation). Real SoC also depends on
# temperature, age, and whether the pack is resting or under charge/load,
# so this is only a rough estimate.
_SOC_CURVE_12V: list[tuple[float, int]] = [
    (10.50, 0), (11.31, 10), (11.58, 20), (11.75, 30), (11.90, 40),
    (12.06, 50), (12.20, 60), (12.32, 70), (12.42, 80), (12.50, 90),
    (12.70, 100),
]


def estimate_battery_soc(voltage: float | None, battery_present: bool) -> int | None:
    """Roughly estimate backup-battery state of charge (%) from voltage.

    Always assumes a 24V pack (two 12V lead-acid batteries in series), per
    this board's documented backup-battery spec — there's no confirmed
    single-12V configuration for this model to branch on.
    """
    if not battery_present or voltage is None or voltage < 5.0:
        return None
    per_cell = voltage / 2

    if per_cell <= _SOC_CURVE_12V[0][0]:
        return 0
    if per_cell >= _SOC_CURVE_12V[-1][0]:
        return 100
    for (v_lo, pct_lo), (v_hi, pct_hi) in zip(_SOC_CURVE_12V, _SOC_CURVE_12V[1:]):
        if v_lo <= per_cell <= v_hi:
            ratio = (per_cell - v_lo) / (v_hi - v_lo)
            return round(pct_lo + ratio * (pct_hi - pct_lo))
    return None


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


def is_gate_in_motion(
    status_hex: str | None, is_egb: bool, gate_mode: str = GATE_MODE_DOUBLE
) -> bool:
    """Return True if the gate status frame indicates active movement.

    Used to skip sampling backup-battery voltage while the motor is
    drawing current: load sag would produce a misleadingly low
    state-of-charge estimate unrelated to the pack's actual charge.

    ``gate_mode`` must match what's passed to ``cover.py``'s status parsing
    (see ``XHouseDeviceData.gate_mode``): the single-wing branch of
    ``parse_ega_status`` checks ``dir_b`` before falling back to position,
    so passing the wrong mode can miss motion that position-only logic
    would misread as "closed".
    """
    status = (
        parse_egb_status(status_hex)
        if is_egb
        else parse_ega_status(status_hex, gate_mode)
    )
    return status is not None and status["state"] in ("opening", "closing")
