"""
Unit tests for scraper.py.

All Selenium-dependent functions are tested with mocks so no browser is needed.
Pure I/O functions (checkpoint, CSV) use tmp_path fixtures.
"""

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import scraper
from scraper import (
    PHONE_RE,
    collect_visible_numbers,
    load_checkpoint,
    save_checkpoint,
    save_csv,
    scroll_and_extract,
)


# ---------------------------------------------------------------------------
# PHONE_RE regex
# ---------------------------------------------------------------------------
class TestPhoneRegex:
    valid = [
        "+61 414 621 930",
        "+61414621930",
        "0414621930",
        "+1 (555) 123-4567",
        "+447911123456",
        "044-1234567",
    ]
    invalid = [
        "",
        "Hey there!",
        "Abu Ali",
        "12345",  # too short (only 5 digits)
        "not a number",
        "title",
    ]

    @pytest.mark.parametrize("number", valid)
    def test_valid_matches(self, number: str) -> None:
        assert PHONE_RE.match(number), f"Expected match for: {number!r}"

    @pytest.mark.parametrize("text", invalid)
    def test_invalid_no_match(self, text: str) -> None:
        assert not PHONE_RE.match(text), f"Expected no match for: {text!r}"


# ---------------------------------------------------------------------------
# load_checkpoint / save_checkpoint
# ---------------------------------------------------------------------------
class TestCheckpoint:
    def test_load_missing_file_returns_empty_set(self, tmp_path: Path) -> None:
        result = load_checkpoint(str(tmp_path / "nonexistent.json"))
        assert result == set()

    def test_roundtrip(self, tmp_path: Path) -> None:
        path = str(tmp_path / "checkpoint.json")
        numbers = {"+61 414 000 000", "+61 415 111 111"}
        save_checkpoint(numbers, path)
        loaded = load_checkpoint(path)
        assert loaded == numbers

    def test_save_is_atomic(self, tmp_path: Path) -> None:
        """Verify .tmp file is replaced (no leftover tmp file)."""
        path = str(tmp_path / "checkpoint.json")
        save_checkpoint({"+61 400 000 000"}, path)
        assert Path(path).exists()
        assert not Path(path + ".tmp").exists()

    def test_save_content_is_sorted(self, tmp_path: Path) -> None:
        path = str(tmp_path / "checkpoint.json")
        numbers = {"+61 420 000 000", "+61 400 000 000", "+61 410 000 000"}
        save_checkpoint(numbers, path)
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["numbers"] == sorted(numbers)

    def test_load_ignores_non_list_value(self, tmp_path: Path) -> None:
        path = str(tmp_path / "bad.json")
        with open(path, "w") as fh:
            json.dump({"numbers": []}, fh)
        assert load_checkpoint(path) == set()


# ---------------------------------------------------------------------------
# save_csv
# ---------------------------------------------------------------------------
class TestSaveCsv:
    def test_header_and_rows(self, tmp_path: Path) -> None:
        path = str(tmp_path / "out.csv")
        numbers = {"+61 400 000 001", "+61 400 000 002"}
        save_csv(numbers, path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows[0] == ["phone_number"]
        assert set(rows[1]) | set(rows[2]) == numbers  # type: ignore[operator]

    def test_output_is_sorted(self, tmp_path: Path) -> None:
        path = str(tmp_path / "out.csv")
        numbers = {"+61 420 000 000", "+61 400 000 000"}
        save_csv(numbers, path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        data_rows = [r[0] for r in rows[1:]]
        assert data_rows == sorted(numbers)

    def test_empty_set_writes_header_only(self, tmp_path: Path) -> None:
        path = str(tmp_path / "out.csv")
        save_csv(set(), path)
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        assert rows == [["phone_number"]]


# ---------------------------------------------------------------------------
# collect_visible_numbers  (mocked driver)
# ---------------------------------------------------------------------------
class TestCollectVisibleNumbers:
    def _make_driver(self, js_return: Any) -> MagicMock:
        driver = MagicMock()
        driver.execute_script.return_value = js_return
        return driver

    def test_filters_valid_numbers(self) -> None:
        driver = self._make_driver(
            ["+61 414 621 930", "Hey there!", "+61 400 000 000", "Abu Ali"]
        )
        result = collect_visible_numbers(driver)
        assert result == {"+61 414 621 930", "+61 400 000 000"}

    def test_empty_page_returns_empty_set(self) -> None:
        driver = self._make_driver([])
        assert collect_visible_numbers(driver) == set()

    def test_all_invalid_returns_empty_set(self) -> None:
        driver = self._make_driver(["Hey there!", "Abu Ali", "title"])
        assert collect_visible_numbers(driver) == set()

    def test_deduplicates(self) -> None:
        driver = self._make_driver(
            ["+61 414 621 930", "+61 414 621 930", "+61 414 621 930"]
        )
        assert collect_visible_numbers(driver) == {"+61 414 621 930"}


# ---------------------------------------------------------------------------
# scroll_and_extract  (mocked driver + patched helpers)
# ---------------------------------------------------------------------------
class TestScrollAndExtract:
    def _make_driver(self) -> MagicMock:
        return MagicMock()

    def test_returns_empty_when_container_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", str(tmp_path / "cp.json"))
        monkeypatch.setattr(scraper, "find_scroll_container", lambda _d: None)
        result = scroll_and_extract(self._make_driver(), 10)
        assert result == set()

    def test_stops_when_total_reached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", str(tmp_path / "cp.json"))
        monkeypatch.setattr(scraper, "SCROLL_PAUSE_S", 0.0)
        monkeypatch.setattr(scraper, "find_scroll_container", lambda _d: MagicMock())

        numbers = [f"+61 400 00{i:04d}" for i in range(5)]
        call_count = 0

        def fake_collect(_d: Any) -> set[str]:
            nonlocal call_count
            result = {numbers[min(call_count, len(numbers) - 1)]}
            call_count += 1
            return result

        monkeypatch.setattr(scraper, "collect_visible_numbers", fake_collect)
        result = scroll_and_extract(self._make_driver(), 5)
        assert len(result) == 5

    def test_stops_after_max_no_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", str(tmp_path / "cp.json"))
        monkeypatch.setattr(scraper, "SCROLL_PAUSE_S", 0.0)
        monkeypatch.setattr(scraper, "MAX_NO_CHANGE", 3)
        monkeypatch.setattr(scraper, "find_scroll_container", lambda _d: MagicMock())
        monkeypatch.setattr(
            scraper, "collect_visible_numbers", lambda _d: {"+61 400 000 000"}
        )
        result = scroll_and_extract(self._make_driver(), 999)
        # Should stop after MAX_NO_CHANGE consecutive no-gain scrolls
        assert result == {"+61 400 000 000"}

    def test_resumes_from_checkpoint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cp_path = str(tmp_path / "cp.json")
        save_checkpoint({"+61 400 000 001"}, cp_path)

        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", cp_path)
        monkeypatch.setattr(scraper, "SCROLL_PAUSE_S", 0.0)
        monkeypatch.setattr(scraper, "find_scroll_container", lambda _d: MagicMock())
        monkeypatch.setattr(
            scraper, "collect_visible_numbers", lambda _d: {"+61 400 000 002"}
        )
        result = scroll_and_extract(self._make_driver(), 2)
        assert "+61 400 000 001" in result
        assert "+61 400 000 002" in result

    def test_dom_error_retries_then_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WebDriverException on collect is caught; script retries and finishes."""
        from selenium.common.exceptions import WebDriverException

        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", str(tmp_path / "cp.json"))
        monkeypatch.setattr(scraper, "SCROLL_PAUSE_S", 0.0)
        monkeypatch.setattr(scraper, "find_scroll_container", lambda _d: MagicMock())

        call_count = 0

        def flaky_collect(_d: Any) -> set[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise WebDriverException("stale")
            return {"+61 400 000 001", "+61 400 000 002"}

        monkeypatch.setattr(scraper, "collect_visible_numbers", flaky_collect)
        result = scroll_and_extract(self._make_driver(), 2)
        assert len(result) == 2

    def test_dom_error_stops_when_container_lost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Container disappearing after a DOM error causes a clean exit."""
        from selenium.common.exceptions import WebDriverException

        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", str(tmp_path / "cp.json"))
        monkeypatch.setattr(scraper, "SCROLL_PAUSE_S", 0.0)

        container_calls = 0

        def container_gone_after_first(_d: Any) -> Any:
            nonlocal container_calls
            container_calls += 1
            return MagicMock() if container_calls == 1 else None

        monkeypatch.setattr(
            scraper, "find_scroll_container", container_gone_after_first
        )
        monkeypatch.setattr(
            scraper,
            "collect_visible_numbers",
            MagicMock(side_effect=WebDriverException("gone")),
        )
        result = scroll_and_extract(self._make_driver(), 999)
        assert result == set()

    def test_scroll_exception_stops_when_container_lost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WebDriverException during the scroll call exits cleanly."""
        from selenium.common.exceptions import WebDriverException

        monkeypatch.setattr(scraper, "CHECKPOINT_FILE", str(tmp_path / "cp.json"))
        monkeypatch.setattr(scraper, "SCROLL_PAUSE_S", 0.0)

        container_calls = 0

        def container_gone_on_reacquire(_d: Any) -> Any:
            nonlocal container_calls
            container_calls += 1
            return MagicMock() if container_calls == 1 else None

        monkeypatch.setattr(
            scraper, "find_scroll_container", container_gone_on_reacquire
        )
        monkeypatch.setattr(
            scraper, "collect_visible_numbers", lambda _d: {"+61 400 000 001"}
        )

        driver = self._make_driver()
        driver.execute_script.side_effect = WebDriverException("scroll failed")
        result = scroll_and_extract(driver, 999)
        assert "+61 400 000 001" in result


# ---------------------------------------------------------------------------
# connect_to_chrome  (mocked webdriver)
# ---------------------------------------------------------------------------
class TestConnectToChrome:
    def test_success_returns_driver(self) -> None:
        mock_driver = MagicMock()
        mock_driver.current_url = "https://web.whatsapp.com"
        with (
            patch("scraper.ChromeDriverManager") as mock_mgr,
            patch("scraper.Service"),
            patch("scraper.webdriver.Chrome", return_value=mock_driver),
        ):
            mock_mgr.return_value.install.return_value = "/fake/chromedriver"
            result = scraper.connect_to_chrome(9222)
        assert result is mock_driver

    def test_failure_exits(self) -> None:
        from selenium.common.exceptions import WebDriverException

        with (
            patch("scraper.ChromeDriverManager") as mock_mgr,
            patch("scraper.Service"),
            patch(
                "scraper.webdriver.Chrome",
                side_effect=WebDriverException("no chrome"),
            ),
            pytest.raises(SystemExit),
        ):
            mock_mgr.return_value.install.return_value = "/fake/chromedriver"
            scraper.connect_to_chrome(9222)
