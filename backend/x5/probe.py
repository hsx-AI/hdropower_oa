"""Independent X5 query probe. Default mode is offline; Python 3.10+, stdlib only."""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
from html.parser import HTMLParser
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import auth as login
from .diagnostics import (DebugLog, ProbeError, decode_text, exception_details, is_transient,
                          network_settings, redact, request as observed_request)

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "按照条件全部导出EXCEL请求"
DEPARTMENT = "水电分厂"
DATE_RE = re.compile(r"DateToString\(fExecutionTime\)\s*>=\s*'\d{4}-\d{2}-\d{2}'")
EXPORT_COLUMNS = [
    ("表单编号", "fOrderCodeStr"), ("类别代码", "fOrderTypeCode"),
    ("类别描述", "fOrderType"), ("分类", "fClassification"),
    ("创建部门", "fCreateDeptName"), ("创建人员", "fCreatePerson"),
    ("校核人", "fCheckPerson"), ("审查人", "fReviewer"),
    ("审定人", "fAuthorizedPerson"), ("批准人", "fApprovalName"),
    ("生效时间", "fExecutionTimeStr"), ("包含工作号/部套号", "fWorkPartNumStr"),
    ("通知原因", "fOrderCause"), ("通知内容", "fOrderContent"),
    ("提出部门", "fProposedDept"),
]
def read_template(path: Path) -> dict:
    # The supplied capture is Chrome's Copy as cURL (cmd), not a shell command to execute.
    text = path.read_text(encoding="utf-8-sig")
    if '^"' in text:
        text = text.replace("^", "")
    match = re.search(r'https?://[^\s"\']+', text)
    if not match or "--data-raw" not in text:
        raise ProbeError("请求1不是已支持的 cURL 请求格式，请重新复制为 cURL (cmd)。")
    endpoint = urllib.parse.urlsplit(match.group())
    if not endpoint.path.endswith("/bizAction.j"):
        raise ProbeError("请求1的接口不是 bizAction.j。")
    body = text.split("--data-raw", 1)[1].strip()
    if body.startswith('"'):
        body = body[1:].replace('\\"', '"')
    elif body.startswith("'"):
        body = body[1:]
    try:
        payload, _ = json.JSONDecoder().raw_decode(body)
    except (ValueError, TypeError):
        raise ProbeError("不能解析请求1的 JSON 载荷。") from None
    if payload.get("action") != "orderReportDataAction":
        raise ProbeError("只允许测试 orderReportDataAction 查询动作。")
    if not isinstance(payload.get("parameters"), dict):
        raise ProbeError("请求1缺少 parameters。")
    if payload.get("translateParameter", {}).get("rowsConfig", {}).get("concept") != "HEC_TechnologyOrder":
        raise ProbeError("请求1的数据对象不是 HEC_TechnologyOrder。")
    # Deliberately discard the captured host, query string, headers and all captured cookies.
    return {"path": endpoint.path, "payload": payload}


def month_bounds(month: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ProbeError("月份格式应为 YYYY-MM，例如 2026-10。")
    try:
        first = dt.date.fromisoformat(month + "-01")
        end = dt.date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    except ValueError:
        raise ProbeError("月份无效。") from None
    return first.isoformat(), end.isoformat()


def build_payload(template: dict, month: str) -> dict:
    start, end = month_bounds(month)
    payload = copy.deepcopy(template["payload"])
    params = payload["parameters"]
    original = params.get("filter", "")
    required = ("fIsExecution", "fCreatePerson", "HEC_TechnologyDispatch",
                "d.fMasterID", "d.fSelectDeptFname", "%水电分厂%")
    if (not all(part in original for part in required) or len(DATE_RE.findall(original)) != 1
            or len(re.findall(r"DateToString\(fExecutionTime\)", original)) != 1):
        raise ProbeError("请求1的日期、可见范围或水电分厂条件与样本不一致，已停止。")
    # Replace just the captured date predicate, without rewriting any authorization/dispatch logic.
    date_filter = (f"DateToString(fExecutionTime) >= '{start}' AND "
                   f"DateToString(fExecutionTime) < '{end}'")
    params["filter"] = DATE_RE.sub(date_filter, original)
    params["offset"] = 0
    params["limit"] = -1
    return payload


class SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        parsed = urllib.parse.urlsplit(target)
        if (parsed.scheme, parsed.netloc) != self.origin:
            raise ProbeError("请求被重定向到其他站点，已停止。请核对内网登录地址。")
        return super().redirect_request(req, fp, code, msg, headers, target)


def parse_json_response(response: dict, stage: str, diagnostics=None) -> dict:
    is_query = stage == "业务查询"
    if not response.get("ok") or response.get("status") != 200:
        if diagnostics and is_query:
            diagnostics.save_query_failure(response)
        raise ProbeError(f"{stage}失败：HTTP {response.get('status', '未知')}。")
    try:
        text, encoding = decode_text(response["body"], response.get("headers", {}))
        result = json.loads(text)
    except (UnicodeError, ValueError, KeyError) as exc:
        if diagnostics:
            diagnostics.emit("json_decode_failed", error_type=type(exc).__name__,
                             line=getattr(exc, "lineno", None), column=getattr(exc, "colno", None),
                             position=getattr(exc, "pos", None))
        if diagnostics and is_query:
            diagnostics.save_query_failure(response)
        raise ProbeError(f"{stage}未返回 JSON，可能返回了登录页或错误页。") from None
    if diagnostics:
        diagnostics.emit("json_parsed", encoding=encoding, flag_is_true=isinstance(result, dict) and result.get("flag") is True)
    if not isinstance(result, dict) or result.get("flag") is not True:
        if diagnostics and is_query:
            diagnostics.save_query_failure(response, result)
        raise ProbeError(f"{stage}返回业务失败标志，请在网页确认账号权限和查询状态。")
    return result


def query_online(template: dict, payload: dict, config: dict, diagnostics=None, overrides=None) -> tuple[dict, list[str]]:
    # Reuse the existing login primitives without calling main(): no credential files are written.
    base_url = str(config.get("base_url", "")).rstrip("/")
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ProbeError("config.json 中的 base_url 无效。")
    origin = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    settings = network_settings(config, overrides)
    diagnostics = diagnostics or DebugLog(console=False)
    diagnostics.settings = settings
    diagnostics.heartbeat = settings["heartbeat_seconds"]
    diagnostics.emit("network_settings", **settings)
    diagnostics.add_secrets([config.get("username"), config.get("password"), login.encode_password(config["password"])])
    timeout = settings["login_timeout_seconds"]
    cookies = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies),
                                        SameOriginRedirect((parsed.scheme, parsed.netloc)))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) X5-Query-Probe/1.0",
               "Accept-Language": "zh-CN,zh;q=0.9"}
    seed = login.build_url(base_url, config["referer_path"])
    seed_parsed = urllib.parse.urlsplit(seed)
    if (seed_parsed.scheme, seed_parsed.netloc) != (parsed.scheme, parsed.netloc):
        raise ProbeError("登录引用页与 base_url 不在同一站点。")
    preflight = observed_request(opener, seed, timeout, headers, diagnostics, "preflight")
    diagnostics.add_secrets([c.value for c in cookies])
    if not preflight.get("ok"):
        raise ProbeError(f"登录初始化失败：HTTP {preflight.get('status', '未知')}。")
    referer = preflight.get("url") or seed
    action = (login.derive_login_action_from_index(referer)
              or login.build_url(base_url, config["login_action_path"]))
    action_parsed = urllib.parse.urlsplit(action)
    if (action_parsed.scheme, action_parsed.netloc) != (parsed.scheme, parsed.netloc):
        raise ProbeError("登录接口与 base_url 不在同一站点。")
    form = {"syscode": "true" if config.get("syscode", True) else "false",
            "username": config["username"], "password": login.encode_password(config["password"]),
            "loginDate": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat(),
            "language": config.get("language", "zh_CN")}
    if config.get("client"):
        form["client"] = str(config["client"])
    login_headers = {**headers, "Accept": "application/json, text/javascript, */*; q=0.01",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "Origin": origin, "Referer": referer, "X-Requested-With": "XMLHttpRequest"}
    login_packet = observed_request(opener, action, timeout, login_headers, diagnostics, "login", form=form)
    diagnostics.add_secrets([c.value for c in cookies])
    with diagnostics.stage("parse_login"):
        result = parse_json_response(login_packet, "登录", diagnostics)
    data = result.get("data")
    session_id = data.get("bsessionid") if isinstance(data, dict) else None
    if not session_id:
        session_id = next((c.value for c in cookies if c.name.lower() == "bsessionid"), None)
    if not isinstance(session_id, str) or not session_id:
        raise ProbeError("登录成功但缺少 bsessionid，需要补充业务会话初始化请求。")
    secrets = [str(config["username"]), str(config["password"]), form["password"], session_id,
               *(c.value for c in cookies)]
    diagnostics.add_secrets(secrets)
    diagnostics.emit("session_ready", cookie_names=sorted({c.name for c in cookies}), bsessionid_present=True)
    # Fresh login only: never reuse bsessionid/JSESSIONID from the captured request.
    query = urllib.parse.urlencode({"bsessionid": session_id, "process": payload["process"],
                                    "activity": payload["activity"]})
    url = origin + template["path"] + "?" + query
    query_headers = {**headers, "Accept": "application/json, text/javascript, */*; q=0.01",
                     "Content-Type": "application/json", "Origin": origin, "Referer": referer,
                     "X-Requested-By": "X5", "X-Requested-With": "XMLHttpRequest",
                     "X-UIserver-Host": parsed.netloc, "Accept-Encoding": "gzip, deflate"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(1, settings["query_retries"] + 2):
        diagnostics.attempts = attempt
        try:
            packet = observed_request(opener, url, settings["query_timeout_seconds"], query_headers,
                                      diagnostics, "query", body=body, attempt=attempt)
        except Exception as exc:
            if attempt > settings["query_retries"] or not is_transient(exc):
                raise
            diagnostics.emit("query_retry_scheduled", attempt=attempt, reason=type(exc).__name__, delay_seconds=5 * attempt)
        else:
            diagnostics.add_secrets([c.value for c in cookies])
            if packet["status"] not in (502, 503, 504) or attempt > settings["query_retries"]:
                with diagnostics.stage("parse_query"):
                    result = parse_json_response(packet, "业务查询", diagnostics)
                return redact(result, diagnostics.secrets), list(diagnostics.secrets)
            diagnostics.save_query_failure(packet)
            diagnostics.emit("query_retry_scheduled", attempt=attempt, http_status=packet["status"], delay_seconds=5 * attempt)
        diagnostics.say(f"查询暂未成功，将在 {5 * attempt} 秒后重试。")
        time.sleep(5 * attempt)
    raise ProbeError("查询未完成，请查看调试记录。")


def extract_records(response: dict) -> list[dict]:
    if not isinstance(response, dict) or response.get("flag") is not True:
        raise ProbeError("响应的 flag 不是 true，不能作为成功数据处理。")
    try:
        rows = response["data"]["value"]["rows"]
    except (KeyError, TypeError):
        raise ProbeError("响应结构缺少 data.value.rows。") from None
    if not isinstance(rows, list):
        raise ProbeError("data.value.rows 不是数组。")
    records = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProbeError("响应包含格式不正确的行。")
        record = {}
        for key, cell in row.items():
            if key == "userdata":
                continue
            if not isinstance(cell, dict):
                raise ProbeError("响应单元格不是 X5 的 value 包装格式。")
            record[key] = cell.get("value")
        records.append(record)
    return records


def validate_records(records: list[dict], month: str, online: bool) -> tuple[list[dict], dict]:
    start, end = month_bounds(month)
    selected, dates, ids = [], [], []
    excluded = 0
    for record in records:
        raw = record.get("fExecutionTime")
        if not isinstance(raw, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", raw):
            raise ProbeError("存在缺失或无法识别的 fExecutionTime，已停止，不能静默丢弃。")
        try:
            date = dt.date.fromisoformat(raw[:10]).isoformat()
        except ValueError:
            raise ProbeError("存在无效生效日期，已停止。") from None
        row_id = record.get("HEC_TechnologyOrder")
        if not isinstance(row_id, str) or not row_id.strip():
            raise ProbeError("存在缺失的技术通知单主键，无法核对完整性。")
        ids.append(row_id)
        if start <= date < end:
            selected.append(record)
            dates.append(date)
        else:
            excluded += 1
    if len(set(ids)) != len(ids):
        raise ProbeError("接口返回重复主键，已停止，未自动去重。")
    if online and excluded:
        raise ProbeError("内网查询返回了目标月份以外的数据，日期条件可能未生效，已停止。")
    return selected, {"response_count": len(records), "selected_count": len(selected),
                      "outside_month_count": excluded, "duplicate_id_count": 0,
                      "min_execution_date": min(dates) if dates else None,
                      "max_execution_date": max(dates) if dates else None}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        elif tag in ("br", "p", "div", "tr", "li") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif tag in ("p", "div", "tr", "li") and not self.hidden:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    if not isinstance(value, str) or not re.search(r"</?[A-Za-z][^>]*>", value):
        return value
    parser = PlainText()
    parser.feed(value)
    return "".join(parser.parts).strip()


def csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def save_json(path: Path, value):
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def export_csv(path: Path, records: list[dict], columns, rich_text=False):
    with path.open("x", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([label for label, _ in columns])
        for record in records:
            values = []
            for _, field in columns:
                value = record.get(field)
                if rich_text and field in ("fOrderCause", "fOrderContent"):
                    value = plain_text(value)
                values.append(csv_value(value))
            writer.writerow(values)


def make_output_dir(base: Path, online: bool) -> Path:
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y%m%d_%H%M%S")
    path = base / f"{stamp}_{'online' if online else 'offline'}_{uuid.uuid4().hex[:6]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="X5 水电分厂技术通知单测试，默认离线，不访问内网。")
    parser.add_argument("--online", action="store_true", help="在内网自动登录并重新查询")
    parser.add_argument("--month", default="2026-10", help="生效时间月份，默认 2026-10")
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("X5_CONFIG_PATH", ROOT / "config.json")))
    parser.add_argument("--request", type=Path, default=Path(os.environ.get("X5_REQUEST_PATH", SAMPLES / "请求1.txt")))
    parser.add_argument("--response", type=Path, default=SAMPLES / "请求响应json.txt", help="仅用于离线模式")
    parser.add_argument("--output-dir", type=Path, default=Path(os.environ.get("X5_PROBE_RESULTS", ROOT / "probe_results")))
    parser.add_argument("--expected-count", type=int, help="网页相同条件下的记录总数，用于内网完整性核对")
    parser.add_argument("--login-timeout", type=float, help="登录网络阻塞超时秒数，默认至少60秒")
    parser.add_argument("--query-timeout", type=float, help="查询网络阻塞超时秒数，默认900秒（15分钟），并非整次运行总时长")
    parser.add_argument("--query-retries", type=int, help="查询网络故障/502/503/504额外重试次数，默认0，最多3次")
    parser.add_argument("--heartbeat-interval", type=float, help="等待中的进度提示间隔秒数，默认15秒")
    args = parser.parse_args(argv)
    if args.expected_count is not None and args.expected_count < 0:
        parser.error("--expected-count 不能为负数")
    output = make_output_dir(args.output_dir, args.online)
    diagnostics = DebugLog(output)
    diagnostics.say(f"调试目录已建立：{output}")
    diagnostics.emit("run_started", mode="online" if args.online else "offline", month=args.month)
    start, end = None, None
    summary = {"mode": "online" if args.online else "offline", "month": args.month,
               "department": DEPARTMENT, "status": "failed", "completeness": "not_verified"}
    try:
        overrides = {"login_timeout_seconds": args.login_timeout, "query_timeout_seconds": args.query_timeout,
                     "query_retries": args.query_retries, "heartbeat_seconds": args.heartbeat_interval}
        validated_settings = network_settings({}, overrides)
        diagnostics.heartbeat = validated_settings["heartbeat_seconds"]
        with diagnostics.stage("prepare"):
            start, end = month_bounds(args.month)
            template = read_template(args.request)
            payload = build_payload(template, args.month)
        summary.update({"date_field": "fExecutionTime", "start_inclusive": start,
                        "end_exclusive": end, "action": payload["action"],
                        "offset": 0, "limit": -1, "original_scope_preserved": True,
                        "department_filter": "dispatch_path_contains_水电分厂"})
        # This is a safe plan, not a replayable request containing personal scope predicates or tokens.
        save_json(output / "query_plan.json", {key: value for key, value in summary.items()
                                               if key not in ("status", "completeness")})
        if args.online:
            with diagnostics.stage("config"):
                config = login.load_config(args.config)
            response, secrets = query_online(template, payload, config, diagnostics, overrides)
        else:
            secrets = ()
            with diagnostics.stage("offline"):
                response = json.loads(args.response.read_text(encoding="utf-8-sig"))
                diagnostics.emit("sample_loaded", response_bytes=args.response.stat().st_size)
        response = redact(response, secrets)
        with diagnostics.stage("save_response"):
            save_json(output / "response.redacted.json", response)
        with diagnostics.stage("validate"):
            records, counts = validate_records(extract_records(response), args.month, args.online)
            summary.update(counts)
            diagnostics.emit("records_checked", **counts)
        with diagnostics.stage("export"):
            save_json(output / "records.json", records)
            fields = list(dict.fromkeys([*payload["parameters"]["columns"].split(","),
                                        *(field for record in records for field in record)]))
            export_csv(output / "原始字段.csv", records, [(field, field) for field in fields])
            export_csv(output / "表格.csv", records, EXPORT_COLUMNS, rich_text=True)
            diagnostics.emit("files_exported", record_count=len(records), raw_column_count=len(fields))
        summary["expected_count"] = args.expected_count
        matched = args.expected_count is not None and args.expected_count == len(records)
        with diagnostics.stage("compare"):
            diagnostics.emit("web_count_check", expected_count=args.expected_count, actual_count=len(records),
                             count_matches=matched if args.expected_count is not None else None)
            if args.expected_count is not None and not matched:
                raise ProbeError("抓取条数与指定的网页总条数不一致，请勿作为完整数据使用。")
        summary["status"] = "query_checks_passed" if args.online else "offline_checks_passed"
        if args.online and matched:
            summary["completeness"] = "count_matches_user_provided_web_total"
        elif not args.online:
            summary["completeness"] = "sample_only_not_full_month_proof"
        print(f"{'内网查询检查' if args.online else '离线样本检查'}通过：响应 {counts['response_count']} 条，目标月份 {len(records)} 条。")
        if not args.online:
            print("离线仅验证已有样本，不能证明目标月份数据完整，也不代表内网请求已成功。")
        elif not matched:
            print("尚未核对网页总条数；limit=-1 的完整性仍待内网比对。")
        elif not records:
            print("网页与接口均为 0 条，请确认网页日期、部门和账号条件一致。")
        print(f"结果目录：{output}")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # Never print raw exceptions: urllib errors can contain URLs with live bsessionid.
        if isinstance(exc, KeyboardInterrupt):
            message = "用户中止测试，已保留中止前的进度和调试信息。"
        elif isinstance(exc, ProbeError):
            message = str(exc)
        elif isinstance(exc, FileNotFoundError):
            message = "缺少请求样本或 X5 私密配置，请对照环境变量和部署说明检查文件。"
        elif isinstance(getattr(exc, "reason", exc), TimeoutError):
            message = "网络等待超时，阶段、已接收字节和超时设置已保留；若查询较慢，可用 --query-timeout 1800 再测试。"
        elif is_transient(exc):
            message = "连接中断或响应未接收完整，已保留接收大小和异常位置，不将部分响应作为成功结果。"
        elif isinstance(exc, urllib.error.URLError):
            message = "无法连接内网服务或连接超时，请在内网运行并核对 config.json 地址。"
        elif isinstance(exc, (UnicodeError, json.JSONDecodeError)):
            message = "文件编码或 JSON 格式错误，请使用 UTF-8 并核对文件内容。"
        else:
            message = f"测试未完成（{type(exc).__name__}）。请提供 summary.json 中的脱敏诊断。"
        summary["status"] = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        summary["error"] = message
        summary["exception"] = exception_details(exc)
        diagnostics.emit("run_cancelled" if isinstance(exc, KeyboardInterrupt) else "run_error",
                         message=message, exception=exception_details(exc))
        print(f"测试失败：{message}")
        print(f"诊断目录：{output}")
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    finally:
        diagnostics.finish(summary)


if __name__ == "__main__":
    sys.exit(main())
