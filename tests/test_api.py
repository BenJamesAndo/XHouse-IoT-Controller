from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).parents[1]
PKG = REPO / "custom_components" / "xhouse"


def _load_api():
    # api.py uses relative imports, but the package __init__ needs
    # homeassistant. Register the package by hand so const/api load alone.
    root = types.ModuleType("custom_components")
    root.__path__ = [str(REPO / "custom_components")]
    pkg = types.ModuleType("custom_components.xhouse")
    pkg.__path__ = [str(PKG)]
    sys.modules["custom_components"] = root
    sys.modules["custom_components.xhouse"] = pkg
    for name, path in (("const", PKG / "const.py"), ("api", PKG / "api.py")):
        spec = importlib.util.spec_from_file_location(
            f"custom_components.xhouse.{name}", path
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    return sys.modules["custom_components.xhouse.api"]


api = _load_api()


class _TimeoutRequest:
    async def __aenter__(self):
        raise TimeoutError

    async def __aexit__(self, *exc):
        return False


class _TimeoutSession:
    def post(self, *args, **kwargs):
        return _TimeoutRequest()


class ApiTest(unittest.TestCase):
    def test_api_post_wraps_timeout(self) -> None:
        # aiohttp's total deadline raises a bare TimeoutError, which is not a
        # ClientError. It must surface as XHouseApiError so callers can
        # distinguish "cloud unreachable" from an unexpected crash.
        client = api.XHouseApi(_TimeoutSession())
        with self.assertRaises(api.XHouseApiError) as ctx:
            asyncio.run(client._api_post("clientUser/login", {}, authenticated=False))
        # A bare TimeoutError has an empty str(); the message must still say what failed.
        self.assertIn("TimeoutError", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
