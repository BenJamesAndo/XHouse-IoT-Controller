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
    def test_parse_egb1900_status(self) -> None:
        cases = [
            ("321177078200", "closed", 0),
            ("321177078201", "open", 100),
            ("411177078200AABBCCDDEEFF", "closed", 0),
            ("411177078201AABBCCDDEEFF", "open", 100),
        ]

        for frame, state, position in cases:
            with self.subTest(frame=frame):
                self.assertEqual(
                    protocol.parse_egb_status(frame),
                    {"state": state, "position": position},
                )

    def test_parse_egb1900_status_rejects_invalid_frames(self) -> None:
        for frame in (None, "", "3211770782", "3211770782GG", "321177078202"):
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
