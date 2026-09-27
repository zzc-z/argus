import pytest

pytestmark = pytest.mark.smoke


def test_imports() -> None:
    """确保 app 包可被 import（即使后续模块还没写，import 自身不应崩）。"""
    # 这条测试在 W1 时仅验证 app package 存在；W2 起会替换为真实健康检查。
    try:
        import app  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("app package not yet created (W2 will create)")


def test_python_version() -> None:
    import sys

    assert sys.version_info >= (3, 12), "Argus API requires Python 3.12+"
