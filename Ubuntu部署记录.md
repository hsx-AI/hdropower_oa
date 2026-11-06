# Ubuntu 部署记录（2026-11-06）

- 主机：hsx@10.150.86.2，SSH 别名 ubuntu-dev。
- 访问地址：https://10.150.86.2/#/notices。
- 平台登录信息保存在本机 C:/Users/hsx/.ssh/hydro-deploy-20261106/平台登录信息.txt，不提交版本库。
- 使用服务器专用自签名 HTTPS 证书，客户端须信任该证书后访问；证书副本位于上述私密目录的 server.crt。未自动修改客户端证书信任设置。
- 服务目录：/home/hsx/projects/hydro-oa，当前版本位于 releases/20261106，current 为当前版本链接。
- MySQL 数据库：hydro_oa。数据库密码与平台密码保存在服务器 shared/service.env（600 权限），没有写入源码。
- MySQL 和 API 仅监听回环地址，Nginx 提供 443 端口，80 跳转到 HTTPS。
- mysql、nginx、hydro-oa-api 和 hydro-oa-worker 已启用开机自启。
- X5采集、登录与诊断代码现集成在 backend/x5/；不再依赖旁边的 X5_get 目录。X5私密配置、请求模板和日志在 shared/x5-private/ 与 shared/x5-sync-logs/。
- 旧 X5_get 目录保留在 /home/hsx/projects/hydro-oa/backups/X5_get-pre-integration-20261106，不参与运行。

## 验证结果

前端生产构建通过；18 项采集离线测试通过。已导入用户验证过的 2026 年 10 月 921 条通知单。HTTPS 页面及详情返回 200，健康检查通过，无认证请求被拒绝。集成版worker已启动；X5服务器端口连接超时，登录未成功，历史月份尚未补采。

技术通知单模块已接入真实后台，其他前端模块仍是演示。

## 管理命令

```bash
ssh ubuntu-dev
systemctl status hydro-oa-api
systemctl status hydro-oa-worker
# 查看同步安全摘要：
journalctl -u hydro-oa-worker -n 30
```

数据库保存在系统 MySQL 数据目录；shared/X5 私密配置及原始请求勿推送到版本库。升级前备份数据库，保留 releases 历史版本和 shared 私密配置。

## 系统地区与语言

系统默认 LANG=zh_CN.UTF-8，LANGUAGE=zh_CN:zh，hsx 桌面语言为简体中文，地区格式为 zh_CN.UTF-8，时区 Asia/Shanghai，网络校时已启用。当前桌面需注销后重新登录才能完整应用；未强制注销或重启服务器。
