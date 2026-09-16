from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

PROTOCOL_PATH = (
    Path(__file__).parents[1] / "custom_components" / "xhouse" / "protocol.py"
)
SPEC = importlib.util.spec_from_file_location("xhouse_protocol", PROTOCOL_PATH)
assert SPEC is not None and SPEC.loader is not None
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)


class ProtocolTest(unittest.TestCase):
    def test_parse_egb1900_status_short_idle_frames(self) -> None:
        cases = [
            ("321177078202", "open", 100),
            ("321177078203", "closed", 0),
        ]
        for frame, state, position in cases:
            with self.subTest(frame=frame):
                self.assertEqual(
                    protocol.parse_egb_status(frame),
                    {"state": state, "position": position},
                )

    def test_parse_egb1900_status_motion_states(self) -> None:
        self.assertEqual(
            protocol.parse_egb_status("321177078200"),
            {"state": "closing", "position": None},
        )
        self.assertEqual(
            protocol.parse_egb_status("321177078201"),
            {"state": "opening", "position": None},
        )

    def test_parse_egb1900_status_reads_position_offset(self) -> None:
        # Position at [18:20]: 0x2D = 45, 0x64 = 100, 0x50 = 80.
        self.assertEqual(
            protocol.parse_egb_status("4111770782010000002D"),
            {"state": "opening", "position": 45},
        )
        self.assertEqual(
            protocol.parse_egb_status("32117707820200000064"),
            {"state": "open", "position": 100},
        )
        self.assertEqual(
            protocol.parse_egb_status("32117707820200000050"),
            {"state": "open", "position": 80},
        )

    def test_parse_egb1900_status_rejects_invalid_frames(self) -> None:
        for frame in (None, "", "3211770782", "3211770782GG", "321177078204"):
            with self.subTest(frame=frame):
                self.assertIsNone(protocol.parse_egb_status(frame))

    def test_parse_ega_status_still_uses_swing_gate_semantics(self) -> None:
        status = protocol.parse_ega_status(
            "419012855200020200000000000101010064640A0A"
        )

        self.assertIsNotNone(status)
        self.assertEqual(status["state"], "open")
        self.assertEqual(status["position"], 100)

    def test_parse_ega_status_rejects_malformed_hex(self) -> None:
        self.assertIsNone(protocol.parse_ega_status("GG" * 19))

    def test_parse_battery_reply_real_ega1800_captures(self) -> None:
        # Captured live from an EGA1800 (firmware 2.0.5) via the regular
        # passive "status" property (wifi/getWifiProperties), in three
        # physical states.
        no_battery_mains_on = "325279331900030300000000000000010000000B0D"
        battery_mains_on = "325279331900030300006126000000010100000B0D"
        battery_mains_off = "3252793319000303000060D3000000010100000B0D"

        self.assertEqual(
            protocol.parse_battery_reply(no_battery_mains_on),
            {"voltage": 0.0, "battery_present": False},
        )
        self.assertEqual(
            protocol.parse_battery_reply(battery_mains_on),
            {"voltage": 24.87, "battery_present": True},
        )
        self.assertEqual(
            protocol.parse_battery_reply(battery_mains_off),
            {"voltage": 24.787, "battery_present": True},
        )

    def test_parse_battery_reply_rejects_short_or_missing_frames(self) -> None:
        for frame in (None, "", "3252793319000303", "32" + "GG" * 20):
            with self.subTest(frame=frame):
                self.assertIsNone(protocol.parse_battery_reply(frame))

    def test_estimate_battery_soc_no_battery_is_unknown(self) -> None:
        self.assertIsNone(protocol.estimate_battery_soc(0.0, False))
        self.assertIsNone(protocol.estimate_battery_soc(None, False))
        self.assertIsNone(protocol.estimate_battery_soc(0.0, True))

    def test_estimate_battery_soc_real_ega1800_captures(self) -> None:
        # Same two "battery installed" captures as above; voltage is
        # always halved (24V pack = two 12V cells in series) before
        # looking it up on the 12V open-circuit-voltage curve.
        self.assertEqual(protocol.estimate_battery_soc(24.87, True), 82)
        self.assertEqual(protocol.estimate_battery_soc(24.787, True), 77)

    def test_estimate_battery_soc_clamps_high_voltage(self) -> None:
        self.assertEqual(protocol.estimate_battery_soc(30.0, True), 100)
        self.assertEqual(protocol.estimate_battery_soc(21.0, True), 0)

    def test_estimate_battery_soc_below_curve_is_unknown(self) -> None:
        # Below the 24V curve floor we cannot interpret the pack (e.g. a
        # single 12V battery), so report unknown rather than a flat 0%.
        for voltage in (5.0, 12.0, 12.6, 20.9):
            with self.subTest(voltage=voltage):
                self.assertIsNone(protocol.estimate_battery_soc(voltage, True))

    def test_is_gate_in_motion_ega(self) -> None:
        idle_closed = "325279331900030300006126000000010100000B0D"
        # Same known-good frame as test_parse_ega_status_still_uses_swing_gate_semantics,
        # with door_enum (hex[10:12]) forced to 0x02 ("opening").
        opening = "419012855202020200000000000101010064640A0A"
        self.assertFalse(protocol.is_gate_in_motion(idle_closed, is_egb=False))
        self.assertTrue(protocol.is_gate_in_motion(opening, is_egb=False))

    def test_is_gate_in_motion_egb(self) -> None:
        self.assertFalse(protocol.is_gate_in_motion("321177078202", is_egb=True))
        self.assertFalse(protocol.is_gate_in_motion("321177078203", is_egb=True))
        self.assertTrue(protocol.is_gate_in_motion("321177078200", is_egb=True))
        self.assertTrue(protocol.is_gate_in_motion("321177078201", is_egb=True))

    def test_is_gate_in_motion_handles_missing_frame(self) -> None:
        self.assertFalse(protocol.is_gate_in_motion(None, is_egb=False))
        self.assertFalse(protocol.is_gate_in_motion(None, is_egb=True))

    def test_is_gate_in_motion_requires_correct_gate_mode(self) -> None:
        # door_enum=0x00 with dir_b=0x01 and zero position: the single-wing
        # branch reads this as "opening" via dir_b, but the double-wing
        # branch (the old hardcoded default) falls through to "closed"
        # since position is still zero. Passing the wrong gate_mode here
        # previously let motor-load voltage sag through as a real reading.
        frame = "41527933190000010000000000000000000000"
        self.assertFalse(
            protocol.is_gate_in_motion(frame, is_egb=False, gate_mode=protocol.GATE_MODE_DOUBLE)
        )
        self.assertTrue(
            protocol.is_gate_in_motion(frame, is_egb=False, gate_mode=protocol.GATE_MODE_SINGLE)
        )


if __name__ == "__main__":
    unittest.main()
