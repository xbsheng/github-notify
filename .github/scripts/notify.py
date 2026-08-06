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
    if os.environ.get("FEISHU_WEBHOOK"):
        post(
            os.environ["FEISHU_WEBHOOK"],
            {"msg_type": "text", "content": {"text": text}},
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
            {"chat_id": os.environ["TG_CHAT_ID"], "text": text},
        )
    if not configured_platforms():
        print("未配置任何推送平台，跳过", file=sys.stderr)


def event_text(name, ev):
    sender = ev.get("sender", {}).get("login", "?")
    repo = ev.get("repository", {})
    full = repo.get("full_name", "?")
    url = repo.get("html_url", "")
    if name in ("star", "watch"):  # watch(started) 即有人 star，见 notify.yml 注释
        return f"⭐ {sender} star 了 {full}\n{url}"
    if name == "fork":
        fk = ev.get("forkee", {})
        return f"🍴 {sender} fork 了 {full} → {fk.get('full_name', '?')}\n{fk.get('html_url') or url}"
    if name == "issues":
        i = ev.get("issue", {})
        return (
            f"📝 Issue #{i.get('number')} {ev.get('action')}: "
            f"{i.get('title')}（by {i.get('user', {}).get('login')}）\n{i.get('html_url', '')}"
        )
    if name == "pull_request":
        pr = ev.get("pull_request", {})
        action = (
            "🔀 merged"
            if ev.get("action") == "closed" and pr.get("merged")
            else f"📥 PR {ev.get('action')}"
        )
        return (
            f"{action} #{pr.get('number')}: {pr.get('title')}"
            f"（by {pr.get('user', {}).get('login')}）\n{pr.get('html_url', '')}"
        )
    return f"[{name}] {sender} → {full}"


def event_notify():
    ev = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    name = os.environ["EVENT_NAME"]
    if name == "workflow_dispatch":
        platforms = "、".join(configured_platforms()) or "无"
        notify("GitHub 通知配置测试", f"✅ 配置正确，已启用平台：{platforms}")
        return
    text = event_text(name, ev)
    notify(text.split("\n")[0], text)


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
        title = f"👥 新粉丝: {u}"
        notify(title, f"{title}（{owner}）\nhttps://github.com/{u}")


def dry_run():
    print("已配置平台：", "、".join(configured_platforms()) or "无")
    print("示例消息：")
    print(
        event_text(
            "star",
            {
                "sender": {"login": "alice"},
                "repository": {
                    "full_name": "me/r",
                    "html_url": "https://github.com/me/r",
                },
            },
        )
    )


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "f.json"
            assert diff_followers(None, ["a"], st) == []  # 首次只记录
            assert diff_followers(["a", "b"], ["b", "c"], st) == ["c"]
            assert json.loads(st.read_text()) == ["b", "c"]
        assert (
            event_text(
                "star",
                {
                    "sender": {"login": "alice"},
                    "repository": {
                        "full_name": "me/r",
                        "html_url": "https://github.com/me/r",
                    },
                },
            )
            == "⭐ alice star 了 me/r\nhttps://github.com/me/r"
        )
        assert "Issue #3 opened: bug" in event_text(
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
        assert "🔀 merged #7: add pr" in event_text(
            "pull_request",
            {
                "action": "closed",
                "pull_request": {
                    "number": 7,
                    "title": "add pr",
                    "merged": True,
                    "user": {"login": "bob"},
                    "html_url": "https://github.com/me/r/p/7",
                },
            },
        )
        assert "⭐ eve star 了 me/r" in event_text(
            "watch",
            {
                "action": "started",
                "sender": {"login": "eve"},
                "repository": {"full_name": "me/r", "html_url": "https://github.com/me/r"},
            },
        )
        print("selftest ok")
    elif "--dry-run" in sys.argv:
        dry_run()
    elif os.environ.get("EVENT_NAME") == "schedule":
        followers_notify()
    else:
        event_notify()
