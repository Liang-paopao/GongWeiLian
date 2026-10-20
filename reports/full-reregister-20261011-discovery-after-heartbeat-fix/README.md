# 默认在线发现恢复记录（2026-10-11）

## 结论

新 Leader 重新注册后获得了新的 AIC。目录 ACS 已同步，但服务器两个 AMP 转发器仍引用已退役的旧 Leader AIC：旧心跳继续被发送，新 Leader 的心跳没有进入默认在线索引。因此目录精确查询可以看到新 Leader，而默认在线精确查询为空。

旧 Leader AIC：`1.2.156.3088.1.BUPT.JSQB3Y.RN5ERG.1KIZGN.0M45`

新 Leader AIC：`1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9`

## 已执行修复

- 备份服务器 `/etc/gongwei/amp-heartbeat.json`、`/etc/gongwei/amp-metadata.json` 和元数据游标。
- 将 heartbeat 与 metadata 转发配置更新为新 Leader AIC 和新 Leader heartbeat 文件。
- 迁移元数据游标，移除旧 Leader 的确认记录，保留资源与工单 Partner 的游标。
- 更新项目中的 `amp_metadata_forwarder.py` 与 heartbeat sidecar 安装清单，避免后续部署再次写回旧 AIC。
- 重启 `gongwei-amp-heartbeat` 与 `gongwei-amp-metadata`；两者均 `active/running`。

服务器备份目录：`/opt/gongwei/backups/discovery-aic-fix-20261010T164115Z`

## 复核

发现探针输出目录：`reports/full-reregister-20261011-discovery-after-heartbeat-fix/`

- Leader：默认精确查询 `target_found=true`、`default_discoverable=true`、`active=true`。
- 资源 Partner：默认精确查询 `default_discoverable=true`。
- 工单 Partner：默认精确查询 `default_discoverable=true`。
- Leader `aliveLastSeenAt`：`2026-10-10T16:47:30.980Z`。

`platform_verified` 仍为 `false`；发现索引恢复不等同于叮当三轮真实调用验收完成。
