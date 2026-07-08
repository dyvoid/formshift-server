"""Smoke test: the package imports and reports a version."""

import formshift_server


def test_package_has_version() -> None:
    assert isinstance(formshift_server.__version__, str)
    assert formshift_server.__version__
