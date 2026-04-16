from __future__ import annotations

from app.serve import build_tunnel_command, extract_tunnel_url, format_startup_message, strip_ansi


def test_strip_ansi_removes_terminal_escape_sequences() -> None:
    value = "\x1b[7mhttps://example.com\x1b[0m"

    assert strip_ansi(value) == "https://example.com"


def test_build_tunnel_command_targets_localhost_run() -> None:
    command = build_tunnel_command(8123)

    assert command[-1] == "nokey@localhost.run"
    assert "80:127.0.0.1:8123" in command


def test_extract_tunnel_url_ignores_banner_links_and_keeps_real_share_url() -> None:
    assert extract_tunnel_url("See https://openssh.com/pq.html") is None
    assert (
        extract_tunnel_url(
            "5abd7d7c4206f6.lhr.life tunneled with tls termination, https://5abd7d7c4206f6.lhr.life"
        )
        == "https://5abd7d7c4206f6.lhr.life"
    )


def test_format_startup_message_includes_public_link() -> None:
    message = format_startup_message("127.0.0.1", 8000, public_url="https://share.example")

    assert "https://share.example" in message
