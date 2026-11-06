"""Credential-safe X5 login helpers shared by the OA collector."""
import hashlib
import urllib.parse


def encode_password(password: str) -> str:
    digest = hashlib.md5(password.encode("utf-8")).hexdigest()
    return ":" + digest[::2] + digest[1::2]


def build_url(base_url: str, path_or_url: str) -> str:
    if str(path_or_url).startswith(("http://", "https://")):
        return str(path_or_url)
    return f"{base_url.rstrip('/')}/{str(path_or_url).lstrip('/')}"


def derive_login_action_from_index(index_url: str) -> str | None:
    parsed = urllib.parse.urlsplit(index_url)
    marker = "/portal/pc/index.w"
    if marker not in parsed.path:
        return None
    login_path = parsed.path.replace(marker, "/portal/base/login/login.j")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, login_path, "", ""))


def load_config(path=None) -> dict:
    import json
    import os
    from pathlib import Path

    config_value = path or os.environ.get("X5_CONFIG_PATH")
    if not config_value:
        raise FileNotFoundError("请配置 X5_CONFIG_PATH。")
    config_path = Path(config_value)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not config.get("username") or not config.get("password"):
        raise ValueError("X5 私密配置缺少账号或密码。")
    return config
