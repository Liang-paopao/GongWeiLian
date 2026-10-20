# 平台端点配置边界

当前批准 ACS 快照位于 `platform/approved_acs/`：HTTPS Leader 与两个
AMQPS Group/Inbox Partner，均保留独立真实AIC。`platform_verified=false`，
默认在线发现及叮当完整多轮验收尚未通过。

`reports/platform_mq_acs/` 是注册前模板和本机测试资产，其中空AIC与
`{AIC}`占位符不代表当前批准记录。不要重复提交这些模板。

生成基于当前批准身份的变更草稿（不会提交）使用：

```powershell
.venv\Scripts\python.exe -B scripts\build_agentic_acs_draft.py
.venv\Scripts\python.exe -B scripts\build_hybrid_leader_acs.py
```

不要把密码、Token、私钥、EAB 或证书内容写入 ACS。正式证书只放在
本机 `secrets/`，该目录被 Git 和评审包排除。历史本机 JSON-RPC ACS
已集中归档到 `archive/evidence-before-cleanup-20261007.zip`。

正式Broker为`amqps://wt.ioa.pub:5671`，Group ACL为已实测的
`https://wt.ioa.pub:9007`；443旧鉴权入口的403不能代替9007测试结果。
