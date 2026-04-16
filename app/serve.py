from __future__ import annotations

import argparse
import atexit
import os
import re
import socket
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass

import uvicorn

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
WILDCARD_HOSTS = {"0.0.0.0", "::"}
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
URL_RE = re.compile(r"https://[A-Za-z0-9.-]+")


@dataclass
class TunnelState:
    process: subprocess.Popen[str]
    ready: threading.Event
    public_url: str | None = None
    error_message: str | None = None


def strip_ansi(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def extract_tunnel_url(line: str) -> str | None:
    cleaned = strip_ansi(line).strip()
    if "tunneled with tls termination" not in cleaned:
        return None
    match = URL_RE.search(cleaned)
    if match is None:
        return None
    return match.group(0)


def detect_lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        ip_address = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if ip_address.startswith("127."):
        return None
    return ip_address


def build_access_urls(host: str, port: int, lan_ip: str | None = None) -> list[tuple[str, str]]:
    if host in WILDCARD_HOSTS:
        urls = [("이 컴퓨터", f"http://127.0.0.1:{port}")]
        if lan_ip:
            urls.append(("다른 기기(같은 와이파이)", f"http://{lan_ip}:{port}"))
        return urls

    display_host = "127.0.0.1" if host == "localhost" else host
    return [("접속 주소", f"http://{display_host}:{port}")]


def format_startup_message(
    host: str,
    port: int,
    lan_ip: str | None = None,
    public_url: str | None = None,
    share_pending: bool = False,
) -> str:
    lines = ["PDF Quizlet server", ""]
    for label, url in build_access_urls(host, port, lan_ip):
        lines.append(f"- {label}: {url}")
    if public_url:
        lines.append(f"- 공개 링크(어디서든 접속): {public_url}")
    elif share_pending:
        lines.append("- 공개 링크: 생성 중...")
    if host in WILDCARD_HOSTS and lan_ip is None:
        lines.append("- 다른 기기 접속 주소: 로컬 IP를 찾지 못했습니다. `ipconfig getifaddr en0` 로 확인해 주세요.")
    return "\n".join(lines)


def build_tunnel_command(port: int) -> list[str]:
    return [
        "ssh",
        "-T",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-R",
        f"80:127.0.0.1:{port}",
        "nokey@localhost.run",
    ]


def _consume_tunnel_output(state: TunnelState) -> None:
    assert state.process.stdout is not None
    try:
        for raw_line in state.process.stdout:
            line = strip_ansi(raw_line).strip()
            if not line:
                continue
            if state.public_url is None:
                tunnel_url = extract_tunnel_url(line)
                if tunnel_url:
                    state.public_url = tunnel_url
                    print(f"- 공개 링크(어디서든 접속): {state.public_url}", flush=True)
                    state.ready.set()
                    continue
            if "permission denied" in line.lower():
                state.error_message = line
                state.ready.set()
                return
        if state.public_url is None and state.error_message is None:
            state.error_message = "공개 링크를 만들지 못했습니다."
    finally:
        state.ready.set()


def start_public_tunnel(port: int) -> TunnelState:
    process = subprocess.Popen(
        build_tunnel_command(port),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
    )
    state = TunnelState(process=process, ready=threading.Event())
    threading.Thread(target=_consume_tunnel_output, args=(state,), daemon=True).start()
    return state


def stop_public_tunnel(state: TunnelState | None) -> None:
    if state is None or state.process.poll() is not None:
        return
    state.process.terminate()
    try:
        state.process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        state.process.kill()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Quizlet app for local or LAN access.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port number (default: {DEFAULT_PORT})")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development.")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Bind to 127.0.0.1 instead of exposing the app to the local network.",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Create a public HTTPS link that works outside your local Wi-Fi.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    host = "127.0.0.1" if args.local_only or args.share else args.host
    reload_enabled = args.reload and not args.share
    lan_ip = detect_lan_ip() if host in WILDCARD_HOSTS else None
    tunnel_state: TunnelState | None = None
    try:
        print(format_startup_message(host, args.port, lan_ip, share_pending=args.share), flush=True)
        if args.share and args.reload:
            print("- 안내: 공유 모드에서는 공개 링크를 안정적으로 유지하려고 `--reload` 를 무시합니다.", flush=True)
        if args.share:
            tunnel_state = start_public_tunnel(args.port)
            atexit.register(stop_public_tunnel, tunnel_state)
        uvicorn.run("app.main:app", host=host, port=args.port, reload=reload_enabled)
    finally:
        stop_public_tunnel(tunnel_state)


if __name__ == "__main__":
    main()
