"""验证码弹窗检测与冷却策略（无 GUI）。"""

from unittest.mock import MagicMock, patch

from app.utils import easytrader_copy_patch as patch_mod
from app.utils.grid_clipboard_context import GRID_PAGE_FUNDS_STOCK, set_grid_copy_context


def test_should_skip_foreground_when_not_in_cooldown():
    with patch.object(patch_mod, "is_captcha_cooldown_active", return_value=False):
        assert patch_mod.should_skip_foreground_captcha() is False
        assert patch_mod.should_skip_foreground_captcha(MagicMock()) is False


def test_should_skip_foreground_during_cooldown_without_dialog():
    with patch.object(patch_mod, "is_captcha_cooldown_active", return_value=True):
        with patch.object(patch_mod, "_quick_check_captcha", return_value=None):
            assert patch_mod.should_skip_foreground_captcha(MagicMock()) is True


def test_should_not_skip_foreground_when_captcha_visible_in_cooldown():
    trader = MagicMock()
    with patch.object(patch_mod, "is_captcha_cooldown_active", return_value=True):
        with patch.object(patch_mod, "_quick_check_captcha", return_value=object()):
            assert patch_mod.should_skip_foreground_captcha(trader) is False


def test_locate_captcha_dialog_uses_find_when_quick_miss_and_need_reg():
    trader = MagicMock()
    sentinel = object()
    with patch.object(patch_mod, "_quick_check_captcha", return_value=None):
        with patch.object(patch_mod, "_find_captcha_dialog", return_value=sentinel) as find:
            assert patch_mod._locate_captcha_dialog(trader, need_reg=True) is sentinel
            find.assert_called_once_with(trader, timeout=1.0)


def test_locate_captcha_dialog_short_wait_when_not_need_reg():
    trader = MagicMock()
    with patch.object(patch_mod, "_quick_check_captcha", return_value=None):
        with patch.object(patch_mod, "_find_captcha_dialog", return_value=None) as find:
            assert patch_mod._locate_captcha_dialog(trader, need_reg=False) is None
            find.assert_called_once_with(trader, timeout=0.5)


def test_clipboard_matches_requested_page_for_position_grid():
    set_grid_copy_context(GRID_PAGE_FUNDS_STOCK)
    copy_self = MagicMock()
    rows = [{"证券代码": "600000", "股票余额": 100, "成本价": 10.0}]
    copy_self._format_grid_data.return_value = rows
    with patch.object(patch_mod, "_read_clipboard_safe", return_value="tab data"):
        assert patch_mod._clipboard_matches_requested_page(copy_self) is True


def test_recopy_skips_when_clipboard_already_valid():
    trader = MagicMock()
    copy_self = MagicMock()
    copy_self._current_grid = MagicMock()
    with patch.object(patch_mod, "_clipboard_matches_requested_page", return_value=True):
        with patch.object(patch_mod, "mark_clipboard_page") as mark:
            patch_mod._recopy_grid_after_captcha(copy_self, trader)
    copy_self._current_grid.type_keys.assert_not_called()
    mark.assert_called_once()
