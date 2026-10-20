# 最新部署与恢复验收（2026-10-09）

在原3个release上增量部署13个目标文件并补Leader取消重投守卫，未迁移数据库/身份或修改其他项目配置。网页cache为precision-20261009-closeout；普通网页local_rpc，正式HTTPS Leader和两个Inbox Partner仍platform_mq_inbox。

新增受限制的gongwei-amp-metadata.service，官方broker wt.ioa.pub:19092的PLAINTEXT仅传输经用户批准的协议元数据。只读挂载3个日志目录，限制CAP_DAC_READ_SEARCH，隐藏secret/env/数据库路径，私有StateDirectory700/cursors600；只有Kafka确认后写入游标，不创建主题。at-least-once的ACK/fsync故障窗口可能重复相同log_id，未承诺exactly-once。

已执行sudo systemctl reboot；boot ID从6b8a5804-6a61-40e8-8fb8-60326c71974c变为6d3e165f-9b6a-445d-9d0b-f10b0e242564。9个本项目服务和7个其他既有服务active/enabled，5既有站点HTTPS200。备份：011144-closeout、012543-amp-metadata、013124-reboot、015437-cancel-guard（均在/opt/gongwei/backups/20261009-*，秘密/数据库备份不进评审包）。

最新证据：reports/platform-closeout-20261009/README.md。Message统计已出现，DingDang HTTPS Access配对待平台；platform_verified=false。

## 历史部署脚本边界

# 部署脚本边界

这里保留已实施部署、取证和回滚辅助脚本。多个staging/upload/preflight脚本固定引用历史release或秘密目录，不能直接用于当前版本升级；运行前必须核对目标、备份、身份代次与systemd实际配置。

2026-10-08 最终全流程复核的修复已部署到现有服务器：网页仍使用 `20261006-211426-maintenance`，正式 Leader 使用 `20261007-120338-maintenance`，两个 MQ Inbox Partner 使用 `20261007-095036-maintenance`。部署记录见 `reports/final-flow-check-20261008/final-audit-deployment.json`。没有数据库迁移、AIC或证书变更；其他项目未修改。

本机网页及三个 local_rpc 服务的环境须设置 `GONGWEI_LOG_DIR=/opt/gongwei/shared/logs/aip`，目录由运行账户拥有，避免 root 调试命令在 release 默认 logs 中创建不可写文件。正式 Leader/Inbox 使用各自 systemd 指定的 `/var/log/gongwei-*`。秘密环境文件留在服务器，评审包不包含。

网页 Nginx 的 HTTPS server 已配置 `client_max_body_size 15M`，用于现有 10 MiB 录音的 base64 JSON 上传；后端录音限制未扩大。服务器共享 SNI 配置仍让网站进入 127.0.0.1:1443，正式 Leader TLS 透传进入 18443；本目录旧站点模板不是共享入口配置的直接替换文件。

本轮只重启本项目服务、重载 Nginx 并核对其他配置哈希。最新代码及 SQLite 备份在 `/opt/gongwei/backups/20261008-234234-final-audit`；日志权限和上传上限的独立备份见本次报告。8 个服务 active/enabled，MQ Partner 实际重启后重新入群查询通过。未执行共享服务器整机重启。

后续更新必须包含新增的 `mq_partner_runtime.py`；对服务器先备份，再逐服务验证并保留回滚路径。不能以本地离线MQ测试代替正式多群组、Discovery和叮当验收。

只读取证命令：

```powershell
.venv\Scripts\python.exe -B deploy/collect_platform_state.py --output-dir reports/final-maintenance-audit/server-current
```
