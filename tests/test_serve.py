from __future__ import annotations

from app.serve import build_access_urls, format_startup_message


def test_build_access_urls_for_wildcard_host_includes_lan_url() -> None:
    urls = build_access_urls("0.0.0.0", 8000, "192.168.0.24")

    assert urls == [
        ("이 컴퓨터", "http://127.0.0.1:8000"),
        ("다른 기기(같은 와이파이)", "http://192.168.0.24:8000"),
    ]


def test_build_access_urls_for_specific_host_uses_requested_host() -> None:
    urls = build_access_urls("localhost", 9000)

    assert urls == [("접속 주소", "http://127.0.0.1:9000")]


def test_format_startup_message_reports_missing_lan_ip() -> None:
    message = format_startup_message("0.0.0.0", 8000, None)

    assert "로컬 IP를 찾지 못했습니다." in message
