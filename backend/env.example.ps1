# 复制为 backend/env.local.ps1 后填写；真实配置已被.gitignore排除。
$env:DATABASE_URL='mysql+pymysql://hydro_user:URL编码后的数据库密码@127.0.0.1:3306/hydro_oa?charset=utf8mb4'
$env:X5_CONFIG_PATH='E:\path\to\private\x5\config.json'
$env:X5_REQUEST_PATH='E:\path\to\private\x5\request1.txt'
$env:X5_LOG_ROOT='E:\path\to\private\x5\sync_logs'
