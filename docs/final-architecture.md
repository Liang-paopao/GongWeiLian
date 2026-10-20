# 工维联最终架构（本地可复核版）

## 分层

```text
网页/API
  -> Leader 编排（stage2_aip.py / stage3_leader_aip.py）
  -> 传输选择（local_rpc / platform_mq_inbox / platform_https_rpc）
  -> 资源 Partner、工单 Partner、可选声音 Partner
  -> 共享业务动作（stage2_business_actions.py）
  -> SQLite 领域与审计（stage2_domain.py / stage2_db.py）
```

三种传输只替换消息交付，不复制业务动作。声音检测是可插拔辅助工具，可以由 `GONGWEI_AUDIO_ENABLED=false` 停用，手动检查入口仍然可用。

## 传输边界

- `local_rpc`：默认模式，仅绑定本机回环，网页和回归测试使用。
- `platform_mq_inbox`：使用官方 ACPs GroupLeader/GroupPartnerMqClient/Inbox，等待平台 broker、认证服务、AIC 和证书参数；没有这些参数时不会伪造通过。
- `platform_https_rpc`：使用官方 AIP RPC 客户端、正式 HTTPS 和 mTLS 配置；缺 URL、AIC 或证书时启动检查为 pending。

三个模式共享 `stage2_business_actions.py`、`stage2_domain.py` 和 `stage2_db.py`，`platform_verified` 固定为 `false`，直到平台审核、证书、发现和外部调用全部有证据。

## 数据与安全

SQLite 使用事务和 `PRAGMA user_version` 迁移。审计事件只追加，幂等键、工单编号和任务关系保持唯一约束。日志写入六类分类文件并做字段脱敏与大小轮转；密钥、Token、私钥、原始录音和数据库不进入评审包。
