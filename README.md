# GitHub 通知机器人

把 GitHub 仓库动态（**star / fork / issues / 新粉丝**）推送到 **飞书 / pushplus / Server酱 / Telegram**。

- 🪶 零依赖：纯 Python 标准库，只有一个脚本
- ☁️ 零服务器：GitHub Actions 免费跑，不用部署、没有公网端点
- 🔌 即插即用：配了哪个平台就推哪个，没配的不打扰

## 使用

1. **Use this template**（或把 `.github/` 整个复制到目标仓库）
2. 仓库 **Settings → Secrets and variables → Actions**，按需添加：

| Secret | 说明 | 获取方式 |
|---|---|---|
| `FEISHU_WEBHOOK` | 飞书自定义机器人 webhook 完整 URL | 飞书群 → 设置 → 群机器人 → 添加自定义机器人 |
| `PUSHPLUS_TOKEN` | pushplus token | pushplus.plus → 一对一消息 |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey | sct.ftqq.com |
| `TG_BOT_TOKEN` | Telegram 机器人 token | @BotFather 创建机器人 |
| `TG_CHAT_ID` | 接收通知的 chat id | @userinfobot 查询 |

   可选变量 `FOLLOW_OWNER`（Settings → Variables）：要追踪谁的粉丝，默认仓库 owner。

3. 仓库 **Actions → GitHub 通知 → Run workflow**，收到测试消息即配置成功。

## 通知内容

| 事件 | 时效 | 说明 |
|---|---|---|
| ⭐ star | 实时 | 有人 star 仓库 |
| 🍴 fork | 实时 | 有人 fork 仓库 |
| 📝 issues | 实时 | issue 打开 / 关闭 / 重开 |
| 📥 pull_request | 实时 | PR 打开 / 关闭 / 合并 |
| 👥 新粉丝 | 每 10 分钟 | GitHub 没有粉丝事件的 webhook，只能轮询 API 做差集 |

## 本地验证

```bash
python .github/scripts/notify.py --selftest   # 逻辑自测
python .github/scripts/notify.py --dry-run    # 查看已配置平台和示例消息
```

## 自定义

- 推送频率：改 `notify.yml` 里的 `schedule` cron
- 消息文案：改 `notify.py` 里的 `event_text()`
- 新增事件（如 release、watch）：`notify.yml` 加 trigger，`notify.py` 加分支

## 原理

```
star / fork / issues ──触发──▶ GitHub Actions ──┐
                                                ├──▶ notify.py ──▶ 飞书 / pushplus / Server酱 / Telegram
新粉丝 ── cron 10min ──▶ 轮询 API + 差集 ────────┘
```

## License

MIT
