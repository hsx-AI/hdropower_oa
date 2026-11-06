"""Credential-free diagnostics and observable stdlib HTTP transport for the X5 probe."""
from contextlib import contextmanager
import datetime as dt
import gzip
import hashlib
import html
import http.client
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib


class ProbeError(Exception):
    """Only application-generated, credential-free messages may use this type."""


SECRET_KEYS = {"password", "passwd", "username", "cookie", "cookies", "set-cookie",
               "authorization", "bsessionid", "jsessionid", "access_token", "token"}
SAFE_HEADERS = ("Content-Type", "Content-Length", "Content-Encoding", "Transfer-Encoding", "Retry-After")
LABELS = {"prepare": "读取请求资料", "preflight": "初始化登录", "login": "登录",
          "parse_login": "检查登录结果",
          "query": "查询技术通知单", "parse_query": "解析查询响应", "offline": "读取离线样本",
          "config": "读取登录配置", "save_response": "保存脱敏响应", "compare": "核对网页条数",
          "validate": "校验数据范围", "export": "保存结果"}


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {key: "<REDACTED>" if str(key).lower() in SECRET_KEYS else redact(item, secrets)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in sorted({str(s) for s in secrets if s}, key=len, reverse=True):
            value = value.replace(secret, "<REDACTED>")
        value = re.sub(r"(?i)\b(bsessionid|jsessionid|access_token|token|password)=([^&\s\"'<>#;]+)",
                       r"\1=<REDACTED>", value)
    return value


def exception_details(exc):
    reason = getattr(exc, "reason", None)
    cause = reason if isinstance(reason, BaseException) else exc
    # No exception messages, source lines, locals, full URLs or request bodies.
    return {"type": type(exc).__name__, "cause_type": type(cause).__name__,
            "errno": getattr(cause, "errno", None), "winerror": getattr(cause, "winerror", None),
            "frames": [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                       for frame in traceback.extract_tb(exc.__traceback__)[-12:]]}


def safe_headers(headers):
    return {key: str(headers[key])[:256] for key in SAFE_HEADERS if headers.get(key) is not None}


def decode_text(body, headers):
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset\s*=\s*[\"']?([\w-]+)", content_type, re.I)
    charsets = []
    if body.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        charsets.append("utf-32")
    elif body.startswith((b"\xff\xfe", b"\xfe\xff")):
        charsets.append("utf-16")
    if match and match.group(1).lower() in {"utf-8", "utf-8-sig", "utf-16", "utf-32", "gbk", "gb2312", "gb18030"}:
        charsets.append(match.group(1))
    charsets.extend(["utf-8-sig", "gb18030"])
    for charset in dict.fromkeys(charsets):
        try:
            return body.decode(charset), charset
        except UnicodeError:
            pass
    return body.decode("utf-8", errors="replace"), "utf-8-replacement"


class DebugLog:
    def __init__(self, directory=None, heartbeat=15, console=True):
        self.directory = Path(directory) if directory is not None else None
        self.heartbeat = heartbeat
        self.console = console
        self.started = time.monotonic()
        self.stage_started = self.started
        self.stage_name = None
        self.last_failed_stage = None
        self.received_bytes = 0
        self.secrets = set()
        self.lock = threading.RLock()
        self.events = []
        self.attempts = 0
        self.settings = {}

    def add_secrets(self, values):
        with self.lock:
            for value in values:
                if value:
                    value = str(value)
                    self.secrets.update((value, urllib.parse.quote(value, safe=""),
                                         urllib.parse.quote_plus(value), html.escape(value),
                                         json.dumps(value, ensure_ascii=False)[1:-1],
                                         json.dumps(value, ensure_ascii=True)[1:-1]))

    def emit(self, event, **fields):
        with self.lock:
            entry = {"time": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
                     "elapsed_seconds": round(time.monotonic() - self.started, 3),
                     "stage": self.stage_name, "event": event, **fields}
            entry = redact(entry, self.secrets)
            self.events.append(entry)
            if self.directory:
                with (self.directory / "debug.jsonl").open("a", encoding="utf-8") as file:
                    file.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    file.flush()
                temporary = self.directory / "progress.json.tmp"
                temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(temporary, self.directory / "progress.json")

    def say(self, message):
        if self.console:
            print(redact(message, self.secrets), flush=True)

    @contextmanager
    def stage(self, name, **fields):
        self.stage_name = name
        self.stage_started = time.monotonic()
        self.received_bytes = 0
        stop = threading.Event()
        self.emit("stage_started", **fields)
        self.say(f"[{LABELS.get(name, name)}] 开始。")

        def heartbeat():
            while not stop.wait(self.heartbeat):
                elapsed = round(time.monotonic() - self.stage_started, 1)
                self.emit("waiting", stage_elapsed_seconds=elapsed, received_bytes=self.received_bytes)
                self.say(f"[{LABELS.get(name, name)}] 仍在等待/处理，已用时 {elapsed} 秒，已接收 {self.received_bytes:,} 字节。")

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            yield
        except BaseException as exc:
            self.last_failed_stage = name
            self.emit("stage_cancelled" if isinstance(exc, KeyboardInterrupt) else "stage_failed",
                      stage_elapsed_seconds=round(time.monotonic() - self.stage_started, 3),
                      received_bytes=self.received_bytes, exception=exception_details(exc))
            raise
        else:
            elapsed = round(time.monotonic() - self.stage_started, 3)
            self.emit("stage_completed", stage_elapsed_seconds=elapsed, received_bytes=self.received_bytes)
            self.say(f"[{LABELS.get(name, name)}] 完成，用时 {elapsed} 秒。")
        finally:
            stop.set()
            thread.join(timeout=2)

    def save_query_failure(self, packet, parsed=None):
        if self.directory is None:
            return
        stem = f"query_attempt_{packet.get('attempt', 1):02d}_failure"
        if parsed is not None:
            text = json.dumps(redact(parsed, self.secrets), ensure_ascii=False, indent=2)
            suffix = ".redacted.json"
        else:
            text, charset = decode_text(packet["body"], packet.get("headers", {}))
            original_length = len(text)
            # Redact BEFORE truncating, to avoid leaving a sliced credential in the excerpt.
            text = redact(text, self.secrets)
            text = text[:65536]
            suffix = ".redacted.txt"
            self.emit("non_json_response", encoding=charset, excerpt_characters=len(text),
                      excerpt_truncated=original_length > 65536)
        path = self.directory / (stem + suffix)
        path.write_text(text, encoding="utf-8")
        self.emit("private_failure_response_saved", file=path.name)

    def finish(self, summary):
        summary.update({"elapsed_seconds": round(time.monotonic() - self.started, 3),
                        "last_stage": self.stage_name,
                        "failed_stage": self.last_failed_stage if summary["status"] in ("failed", "cancelled") else None,
                        "query_attempts": self.attempts, "network_settings": self.settings,
                        "diagnostics_archive": "diagnostics.zip"})
        self.emit("run_finished", status=summary["status"])
        if self.directory:
            (self.directory / "summary.json").write_text(json.dumps(redact(summary, self.secrets),
                                                                     ensure_ascii=False, indent=2), encoding="utf-8")
            # The shareable archive deliberately excludes all business responses, excerpts and data exports.
            with zipfile.ZipFile(self.directory / "diagnostics.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
                for name in ("summary.json", "query_plan.json", "debug.jsonl", "progress.json"):
                    path = self.directory / name
                    if path.is_file():
                        archive.write(path, name)


def network_settings(config, overrides=None):
    overrides = overrides or {}
    try:
        settings = {
            "login_timeout_seconds": float(config.get("login_timeout_seconds", max(60, float(config.get("timeout_seconds", 20))))),
            "query_timeout_seconds": float(config.get("query_timeout_seconds", 900)),
            "query_retries": int(config.get("query_retries", 0)),
            "heartbeat_seconds": float(config.get("heartbeat_seconds", 15)),
        }
        for key, value in overrides.items():
            if value is not None:
                settings[key] = value
        for key in ("login_timeout_seconds", "query_timeout_seconds"):
            if not 0 < settings[key] <= 86400:
                raise ValueError()
        if not 0 <= settings["query_retries"] <= 3 or not 0 < settings["heartbeat_seconds"] <= 300:
            raise ValueError()
    except (ValueError, TypeError, OverflowError):
        raise ProbeError("网络设置无效：超时应为0至86400秒之间的正数，重试0至3次，进度间隔0至300秒之间。") from None
    return settings


def request(opener, url, timeout, headers, diagnostics, stage, form=None, body=None, attempt=1):
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    endpoint = Path(urllib.parse.urlsplit(url).path).name
    with diagnostics.stage(stage, endpoint=endpoint, method=req.method, timeout_seconds=timeout,
                           request_bytes=len(body) if body is not None else 0, attempt=attempt):
        start = time.monotonic()
        try:
            response = opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            response = exc  # Preserve the error response for safe parsing and local debugging.
        with response:
            packet = {"ok": 200 <= response.code < 300, "status": response.code,
                      "url": response.geturl(), "headers": dict(response.info()), "attempt": attempt}
            diagnostics.emit("response_headers", http_status=response.code,
                             wait_for_headers_seconds=round(time.monotonic() - start, 3),
                             headers=safe_headers(response.info()))
            chunks = []
            digest = hashlib.sha256()
            first_byte = None
            try:
                while True:
                    try:
                        chunk = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                    except http.client.IncompleteRead as exc:
                        if exc.partial:
                            diagnostics.received_bytes += len(exc.partial)
                            digest.update(exc.partial)
                        raise
                    if not chunk:
                        break
                    if first_byte is None:
                        first_byte = round(time.monotonic() - start, 3)
                        diagnostics.emit("first_body_bytes", wait_seconds=first_byte)
                    chunks.append(chunk)
                    digest.update(chunk)
                    diagnostics.received_bytes += len(chunk)
                expected = response.info().get("Content-Length")
                if expected and expected.isdigit() and int(expected) != diagnostics.received_bytes:
                    raise http.client.IncompleteRead(b"", int(expected) - diagnostics.received_bytes)
            except BaseException:
                # Partial bodies may end inside a credential: retain counts/hash only, never partial raw bytes.
                diagnostics.emit("transfer_incomplete", received_bytes=diagnostics.received_bytes,
                                 body_sha256=digest.hexdigest(), expected_content_length=response.info().get("Content-Length"))
                raise
            raw = b"".join(chunks)
            diagnostics.emit("body_received", wire_bytes=len(raw), body_sha256=digest.hexdigest(),
                             first_body_bytes_seconds=first_byte)
            encoding = response.info().get("Content-Encoding", "identity").lower().strip()
            if encoding in ("gzip", "x-gzip"):
                raw = gzip.decompress(raw)
            elif encoding == "deflate":
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            elif encoding not in ("identity", ""):
                raise ProbeError("响应使用了暂不支持的压缩格式，请保留调试包供核对。")
            packet["body"] = raw
            diagnostics.emit("body_ready", decoded_bytes=len(raw), content_encoding=encoding)
            return packet


def is_transient(exc):
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (TimeoutError, ConnectionError, http.client.IncompleteRead, socket.timeout))
