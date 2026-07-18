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


if __name__ == "__main__":
    unittest.main()
