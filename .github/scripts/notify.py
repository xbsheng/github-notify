#!/usr/bin/env python3
"""GitHub 仓库动态 → 飞书 / pushplus / Server酱 / Telegram 推送。

仓库事件 (star/fork/issues/...) 由 GitHub Actions 触发，读事件 payload；
新粉丝由 cron 轮询 REST API，与 repo 内 followers.json 做差集。

配置了哪些 secret 就推送到哪些平台（都为空时静默跳过）：
  FEISHU_WEBHOOK       飞书自定义机器人 webhook 完整 URL
  PUSHPLUS_TOKEN       pushplus.plus 的 token
  SERVERCHAN_SENDKEY   Server酱 Turbo 的 SendKey
  TG_BOT_TOKEN + TG_CHAT_ID  Telegram 机器人 token 与接收者 chat id

可选：
  FOLLOW_OWNER         要追踪谁的粉丝（默认仓库 owner）

用法：
  python notify.py              （在 Actions 中运行）
  python notify.py --selftest   本地逻辑自测
  python notify.py --dry-run    查看已配置平台和示例消息，不发真消息
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def post(url, data, form=False):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
        if form
        else "application/json"
    }
    req = urllib.request.Request(url, body, headers)
    try:
        with urllib.request.urlopen(req) as r:
            r.read()
    except Exception as e:  # 推送失败不中断工作流，但打印 API 返回的具体原因
        detail = ""
        try:
            detail = f": {e.read().decode()}" if hasattr(e, "read") else ""
        except Exception:
            pass
        print(f"post {url} failed: {e}{detail}", file=sys.stderr)


def configured_platforms():
    ps = []
    if os.environ.get("FEISHU_WEBHOOK"):
        ps.append("飞书")
    if os.environ.get("PUSHPLUS_TOKEN"):
        ps.append("pushplus")
    if os.environ.get("SERVERCHAN_SENDKEY"):
        ps.append("Server酱")
    if os.environ.get("TG_BOT_TOKEN") and os.environ.get("TG_CHAT_ID"):
        ps.append("Telegram")
    return ps


def notify(title, text):
    combined = f"{title}\n{text}"  # 飞书/Telegram 只有单段文本，标题拼进内容
    if os.environ.get("FEISHU_WEBHOOK"):
        post(
            os.environ["FEISHU_WEBHOOK"],
            {"msg_type": "text", "content": {"text": combined}},
        )
    if os.environ.get("PUSHPLUS_TOKEN"):
        post(
            "https://www.pushplus.plus/send",
            {"token": os.environ["PUSHPLUS_TOKEN"], "title": title, "content": text},
        )
    if os.environ.get("SERVERCHAN_SENDKEY"):
        post(
            f"https://sctapi.ftqq.com/{os.environ['SERVERCHAN_SENDKEY']}.send",
            {"title": title, "desp": text},
            form=True,
        )
    if os.environ.get("TG_BOT_TOKEN") and os.environ.get("TG_CHAT_ID"):
        post(
            f"https://api.telegram.org/bot{os.environ['TG_BOT_TOKEN']}/sendMessage",
            {"chat_id": os.environ["TG_CHAT_ID"], "text": combined},
        )
    if not configured_platforms():
        print("未配置任何推送平台，跳过", file=sys.stderr)


def repo_stats(api, token, full_name):
    """仓库实时 star/fork 数；失败返回空串（通知不因统计失败中断）。"""
    try:
        req = urllib.request.Request(
            f"{api}/repos/{full_name}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as r:
            d = json.load(r)
        return f"⭐ {d.get('stargazers_count', 0)} · 🍴 {d.get('forks_count', 0)}"
    except Exception as e:
        print(f"repo_stats {full_name} failed: {e}", file=sys.stderr)
        return ""


def event_message(name, ev, stats=""):
    """返回 (标题, 内容)。标题精简为【动作 仓库名】，详情和统计放内容。"""
    repo = ev.get("repository", {})
    full = repo.get("full_name", "?")
    url = repo.get("html_url", "")
    sender = ev.get("sender", {}).get("login", "?")
    if name in ("star", "watch"):  # watch(started) 即有人 star，见 notify.yml 注释
        head, detail = "⭐ star", f"{sender} star 了 {full}"
    elif name == "fork":
        fk = ev.get("forkee", {})
        head, detail = "🍴 fork", f"{sender} fork 了 {full} → {fk.get('full_name', '?')}"
    elif name == "issues":
        i = ev.get("issue", {})
        head = f"📝 {ev.get('action')}"
        detail = f"Issue #{i.get('number')}: {i.get('title')}（by {i.get('user', {}).get('login')}）"
    elif name == "pull_request":
        pr = ev.get("pull_request", {})
        action = "merged" if ev.get("action") == "closed" and pr.get("merged") else ev.get("action")
        head = "🔀 merged" if action == "merged" else "📥 " + action
        detail = f"PR #{pr.get('number')}: {pr.get('title')}（by {pr.get('user', {}).get('login')}）"
    else:
        head, detail = name, f"{sender} → {full}"
    lines = [detail]
    if stats:
        lines.append(f"当前 {stats}")
    lines.append(url)
    return f"{head} {full}", "\n".join(lines)


def event_notify():
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    name = os.environ["EVENT_NAME"]
    if name == "workflow_dispatch":
        platforms = "、".join(configured_platforms()) or "无"
        notify("✅ 通知配置测试", f"已启用平台：{platforms}")
        return
    full = ev.get("repository", {}).get("full_name", "")
    stats = ""
    if full:
        stats = repo_stats(os.environ["GITHUB_API_URL"], os.environ["GITHUB_TOKEN"], full)
    title, text = event_message(name, ev, stats)
    notify(title, text)


def diff_followers(prev, current, state: Path):
    """prev: 上次的列表或 None（首次运行）。返回新增 followers 并落盘当前列表。"""
    state.write_text(json.dumps(current))
    if prev is None:
        return []
    return [u for u in current if u not in prev]


def new_followers(api, token, owner, state: Path):
    page, followers = 1, []
    while True:
        req = urllib.request.Request(
            f"{api}/users/{owner}/followers?per_page=100&page={page}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req) as r:
            batch = json.load(r)
        followers += [u["login"] for u in batch]
        if len(batch) < 100:
            break
        page += 1
    prev = json.loads(state.read_text()) if state.exists() else None
    return diff_followers(prev, followers, state)


def followers_notify():
    owner = os.environ.get("FOLLOW_OWNER") or os.environ["REPO_OWNER"]
    new = new_followers(
        os.environ["GITHUB_API_URL"],
        os.environ["GITHUB_TOKEN"],
        owner,
        Path(".github/followers.json"),
    )
    for u in new:
        notify(f"👥 新粉丝 {u}", f"你新增了粉丝 {u}\nhttps://github.com/{u}")


def dry_run():
    print("已配置平台：", "、".join(configured_platforms()) or "无")
    title, text = event_message(
        "watch",
        {
            "action": "started",
            "sender": {"login": "alice"},
            "repository": {
                "full_name": "me/r",
                "html_url": "https://github.com/me/r",
            },
        },
        "⭐ 123 · 🍴 4",
    )
    print("标题：", title)
    print("内容：")
    print(text)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "f.json"
            assert diff_followers(None, ["a"], st) == []  # 首次只记录
            assert diff_followers(["a", "b"], ["b", "c"], st) == ["c"]
            assert json.loads(st.read_text()) == ["b", "c"]
        assert event_message(
            "watch",
            {
                "action": "started",
                "sender": {"login": "alice"},
                "repository": {
                    "full_name": "me/r",
                    "html_url": "https://github.com/me/r",
                },
            },
            "⭐ 123 · 🍴 4",
        ) == ("⭐ star me/r", "alice star 了 me/r\n当前 ⭐ 123 · 🍴 4\nhttps://github.com/me/r")
        t, c = event_message(
            "issues",
            {
                "action": "opened",
                "repository": {"full_name": "me/r"},
                "issue": {
                    "number": 3,
                    "title": "bug",
                    "user": {"login": "bob"},
                    "html_url": "https://github.com/me/r/i/3",
                },
            },
        )
        assert t == "📝 opened me/r" and "Issue #3: bug" in c
        t, c = event_message(
            "pull_request",
            {
                "action": "closed",
                "repository": {"full_name": "me/r"},
                "pull_request": {
                    "number": 7,
                    "title": "add pr",
                    "merged": True,
                    "user": {"login": "bob"},
                    "html_url": "https://github.com/me/r/p/7",
                },
            },
        )
        assert t == "🔀 merged me/r" and "PR #7: add pr" in c
        t, c = event_message(
            "watch",
            {
                "action": "started",
                "sender": {"login": "eve"},
                "repository": {"full_name": "me/r", "html_url": "https://github.com/me/r"},
            },
        )
        assert t == "⭐ star me/r" and "eve star 了 me/r" in c
        print("selftest ok")
    elif "--dry-run" in sys.argv:
        dry_run()
    elif os.environ.get("EVENT_NAME") == "schedule":
        followers_notify()
    else:
        event_notify()
