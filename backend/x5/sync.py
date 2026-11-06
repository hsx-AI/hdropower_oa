"""Production month reader shared by the OA sync worker and command-line exports."""
import argparse
import datetime as dt
import os
from pathlib import Path
from . import probe
from .auth import load_config
from .diagnostics import DebugLog


def months_since(years=3, today=None):
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
    first = (today.year - years) * 12 + today.month - 1
    last = today.year * 12 + today.month - 1
    return [f'{n // 12:04d}-{n % 12 + 1:02d}' for n in range(last, first - 1, -1)]


def fetch_month(month, config_path=None, request_path=None, log_root=None):
    config_path = Path(config_path or os.environ.get('X5_CONFIG_PATH', probe.ROOT / 'config.json'))
    request_path = Path(request_path or os.environ.get('X5_REQUEST_PATH', probe.SAMPLES / '请求1.txt'))
    config = load_config(config_path)
    output = probe.make_output_dir(
        Path(log_root or os.environ.get('X5_LOG_ROOT', probe.ROOT / 'sync_logs')), True
    )
    log = DebugLog(output)
    summary = {'mode': 'online', 'month': month, 'status': 'failed', 'completeness': 'not_verified'}
    try:
        template = probe.read_template(request_path)
        payload = probe.build_payload(template, month)
        result, _ = probe.query_online(template, payload, config, log)
        with log.stage('validate'):
            records, counts = probe.validate_records(probe.extract_records(result), month, True)
        summary.update(counts, status='query_checks_passed')
        return records
    except BaseException as exc:
        summary['error_type'] = type(exc).__name__
        raise
    finally:
        log.finish(summary)


def main():
    parser = argparse.ArgumentParser(description='正式X5采集：逐月查询，凭据仅从本机配置读取')
    parser.add_argument('--month', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Refuse to overwrite prior exports.
    if args.output.exists():
        parser.error('输出文件已存在，请使用新文件名')
    records = fetch_month(args.month)
    probe.save_json(args.output, records)
    print(f'已保存 {len(records)} 条记录')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'采集失败：{type(exc).__name__}，请检查sync_logs中的脱敏诊断。')
        raise SystemExit(1)
