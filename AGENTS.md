# 水电OA通知单开发

- 当前正式实现范围为backend通知单API、MySQL同步、src/views/Notices.vue和NoticeDetail.vue，其余业务仍是演示。
- X5源查询实现在 backend/x5/，不依赖旁边的 X5_get 目录；真实源请求只能由小时worker或用户在内网显式运行，测试不得调用源系统。
- 凭据和请求模板只从 X5_CONFIG_PATH、X5_REQUEST_PATH 指向的私密文件读取，不提交、不打印。只用随机临时数据库做自动测试，不清空现有数据库。
- 同步必须保留源权限/派发部门条件，按月、唯一主键、事务批量更新，不能用一次缺失删除已有记录。平台跟踪数据不可被源同步覆盖。
- X5时间样本带Z但表示网页墙上时间，禁止擅自加8小时；系统操作日志使用UTC。
- 用户已确认测试阶段结束，授权正式爬虫、FastAPI、MySQL、小时同步、搜索与基础跟踪。旧X5测试阶段限制不阻止本次正式开发。
- 验证：npm run build；独立MySQL上设置TEST_MYSQL_URL，python -m pytest backend/tests -q。实际三年数据数量完整性仍需内网验收。
