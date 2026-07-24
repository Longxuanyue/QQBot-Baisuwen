"""
nonebot_plugin_gamenews —— 多游戏活动进度 + 图片渲染插件

数据来源：tools/game-event-progress（不自行爬取）
渲染引擎：nonebot_plugin_htmlrender (Playwright)
"""

__version__ = "0.3.0"

import asyncio
import subprocess
import sys
from pathlib import Path

from nonebot import get_driver, logger, on_command, get_bot
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, Message, MessageSegment
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from .config import plugin_config, PluginConfig
from .storage import GameStorage
from .games import GAME_KEYS, GAME_NAMES, GAME_EMOJIS, resolve_game_key
from .data_reader import (
    load_all_events, load_game_events, filter_by_category,
    get_urgent_events, format_updated_time, group_events_by_game,
)
from .renderer import render_events_image, render_urgent_image

# ── 插件元数据 ──

__plugin_meta__ = PluginMetadata(
    name="游戏新闻",
    description="多游戏活动进度+卡池+公告聚合（原神/星铁/绝区零/方舟/终末地/1999/碧蓝/BA/鸣潮/三角洲）",
    usage="发送 /游戏新闻 查看全部活动；/卡池、/活动、/紧急活动 分类查询；/订阅新闻 开启每日推送",
    type="application",
    homepage="https://github.com/baisuwen",
    config=PluginConfig,
    supported_adapters={"~onebot.v11"},
    extra={
        "author": "baisuwen",
        "version": __version__,
    },
)

# ── 全局存储（订阅） ──
storage = GameStorage(plugin_config.db_path)

# ── 命令定义 ──
game_news_cmd = on_command("游戏新闻", aliases={"gamenews", "新闻"}, priority=5, block=True)
banner_cmd = on_command("卡池", aliases={"banner"}, priority=5, block=True)
event_cmd = on_command("活动", aliases={"event"}, priority=5, block=True)
urgent_cmd = on_command("紧急活动", aliases={"紧迫", "即将截止"}, priority=5, block=True)
subscribe_cmd = on_command("订阅新闻", priority=5, block=True)
unsubscribe_cmd = on_command("取消新闻", aliases={"取消订阅新闻"}, priority=5, block=True)
status_cmd = on_command("游戏新闻状态", aliases={"新闻状态"}, priority=5, block=True)
force_update_cmd = on_command(
    "强制更新新闻", aliases={"强制爬取新闻"},
    permission=SUPERUSER, priority=3, block=True,
)

# ── 生命周期 ──
driver = get_driver()


@driver.on_startup
async def startup() -> None:
    if not plugin_config.enabled:
        logger.info("[GameNews] 插件已禁用")
        return
    import os
    os.makedirs(plugin_config.db_dir_path, exist_ok=True)
    logger.info(
        f"[GameNews] 已启动 v3.0 | 数据源: {plugin_config.game_event_data_dir} | "
        f"推送 {plugin_config.push_hour:02d}:{plugin_config.push_minute:02d} | "
        f"紧迫检测: {plugin_config.urgency_cron_hours}时 | "
        f"游戏: {', '.join(GAME_NAMES[k] for k in GAME_KEYS)}"
    )


@driver.on_shutdown
async def shutdown() -> None:
    logger.info("[GameNews] 已关闭")


# ═══════════════ 辅助函数 ═══════════════

async def _send_image(bot: Bot, event: MessageEvent, image_bytes: bytes, text: str = "") -> None:
    """发送图片消息（带可选文本前缀）。"""
    msg = Message()
    if text:
        msg.append(MessageSegment.text(text))
    msg.append(MessageSegment.image(image_bytes))
    await bot.send(event, msg)


async def _reply_with_image(cmd, bot: Bot, event: MessageEvent, image_bytes: bytes) -> None:
    """通过命令回复图片。"""
    await cmd.send(MessageSegment.image(image_bytes))


# ═══════════════ 命令处理 ═══════════════

# ── /游戏新闻 ──
@game_news_cmd.handle()
async def handle_news(bot: Bot, event: MessageEvent, arg: Message = CommandArg()) -> None:
    txt = arg.extract_plain_text().strip()
    updated = format_updated_time()

    if txt:
        key = resolve_game_key(txt)
        if key is None:
            supported = " | ".join(f"{GAME_EMOJIS.get(k, '')} {v}" for k, v in GAME_NAMES.items())
            await game_news_cmd.finish(
                f"❌ 未识别的游戏: {txt}\n支持: {supported}"
            )
            return
        data = load_game_events(key)
        if not data:
            await game_news_cmd.finish(f"❌ {GAME_NAMES.get(key, key)} 暂无数据")
            return
        events = data.get("events", [])
        meta = GAME_EMOJIS.get(key, ""), GAME_NAMES.get(key, key)
        title = f"{meta[0]} {meta[1]} · 活动一览"
        subtitle = f"共 {len(events)} 项活动"
    else:
        events = load_all_events()
        title = "活动进度 · 全部游戏"
        subtitle = "作战 · 卡池 · 活动 · 网页"

    try:
        img = await render_events_image(events, title=title, subtitle=subtitle, updated=updated, mark_urgent=True)
        await _reply_with_image(game_news_cmd, bot, event, img)
    except Exception as exc:
        logger.error(f"[GameNews] 渲染失败: {exc}")
        await game_news_cmd.finish(f"❌ 渲染图片失败: {exc}")


# ── /卡池 ──
@banner_cmd.handle()
async def handle_banner(bot: Bot, event: MessageEvent, arg: Message = CommandArg()) -> None:
    txt = arg.extract_plain_text().strip()
    updated = format_updated_time()

    if txt:
        key = resolve_game_key(txt)
        if key is None:
            await banner_cmd.finish(f"❌ 未识别的游戏: {txt}")
            return
        all_ev = load_game_events(key)
        events = [e for e in (all_ev.get("events", []) if all_ev else []) if e.get("category") == "gacha"]
        title = f"{GAME_EMOJIS.get(key,'')} {GAME_NAMES.get(key, key)} · 卡池"
        subtitle = f"共 {len(events)} 个卡池"
    else:
        all_ev = load_all_events()
        events = filter_by_category(all_ev, "gacha")
        title = "当期卡池 · 全部游戏"
        subtitle = f"共 {len(events)} 个卡池"

    try:
        img = await render_events_image(events, title=title, subtitle=subtitle, updated=updated, mark_urgent=True)
        await _reply_with_image(banner_cmd, bot, event, img)
    except Exception as exc:
        await banner_cmd.finish(f"❌ 渲染失败: {exc}")


# ── /活动 ──
@event_cmd.handle()
async def handle_event(bot: Bot, event: MessageEvent, arg: Message = CommandArg()) -> None:
    txt = arg.extract_plain_text().strip()
    updated = format_updated_time()

    if txt:
        key = resolve_game_key(txt)
        if key is None:
            await event_cmd.finish(f"❌ 未识别的游戏: {txt}")
            return
        all_ev = load_game_events(key)
        events = [e for e in (all_ev.get("events", []) if all_ev else []) if e.get("category") != "gacha"]
        title = f"{GAME_EMOJIS.get(key,'')} {GAME_NAMES.get(key, key)} · 活动"
        subtitle = f"共 {len(events)} 项活动"
    else:
        all_ev = load_all_events()
        events = [e for e in all_ev if e.get("category") != "gacha"]
        title = "进行中活动 · 全部游戏"
        subtitle = "作战 · 活动 · 网页"

    try:
        img = await render_events_image(events, title=title, subtitle=subtitle, updated=updated, mark_urgent=True)
        await _reply_with_image(event_cmd, bot, event, img)
    except Exception as exc:
        await event_cmd.finish(f"❌ 渲染失败: {exc}")


# ── /紧急活动 ──
@urgent_cmd.handle()
async def handle_urgent(bot: Bot, event: MessageEvent) -> None:
    urgent = get_urgent_events()
    updated = format_updated_time()

    if not urgent:
        await urgent_cmd.finish("✅ 暂无即将截止的活动或卡池，放心~")
        return

    try:
        img = await render_urgent_image(urgent, updated=updated)
        await _send_image(bot, event, img,
                          f"⚠ 即将截止提醒！以下 {len(urgent)} 项活动/卡池将在 {plugin_config.urgency_hours} 小时内结束：\n")
    except Exception as exc:
        await urgent_cmd.finish(f"❌ 渲染失败: {exc}")


# ── /订阅新闻 /取消新闻 ──
@subscribe_cmd.handle()
async def handle_subscribe(bot: Bot, event: MessageEvent) -> None:
    tid = str(event.group_id) if hasattr(event, "group_id") else str(event.user_id)
    ttype = "group" if hasattr(event, "group_id") else "user"
    ok = storage.add_subscription(ttype, tid)
    if ok:
        await subscribe_cmd.finish(
            f"✅ 已订阅游戏活动每日推送！\n"
            f"推送时间: 每日 {plugin_config.push_hour:02d}:{plugin_config.push_minute:02d}\n"
            f"紧迫提醒: 每日 {','.join(str(h) for h in plugin_config.urgency_cron_hours)}时\n"
            f"/取消新闻 可取消"
        )
    else:
        await subscribe_cmd.finish("ℹ 已订阅过~ /取消新闻 取消")


@unsubscribe_cmd.handle()
async def handle_unsubscribe(bot: Bot, event: MessageEvent) -> None:
    tid = str(event.group_id) if hasattr(event, "group_id") else str(event.user_id)
    ttype = "group" if hasattr(event, "group_id") else "user"
    ok = storage.remove_subscription(ttype, tid)
    if ok:
        await unsubscribe_cmd.finish("✅ 已取消。/订阅新闻 重新订阅")
    else:
        await unsubscribe_cmd.finish("ℹ 尚未订阅。")


# ── /游戏新闻状态 ──
@status_cmd.handle()
async def handle_status(bot: Bot, event: MessageEvent) -> None:
    updated = format_updated_time()
    from .data_reader import load_status
    st = load_status()
    fetch_ok = "✅" if st.get("fetchOk") else "⚠"

    lines = [
        "📊 游戏活动插件状态",
        "=" * 25,
        f"数据更新: {updated}",
        f"抓取状态: {fetch_ok}",
        f"数据源: {plugin_config.game_event_data_dir}",
        f"紧迫阈值: {plugin_config.urgency_hours}h",
        "",
        "游戏覆盖:",
    ]
    for key in GAME_KEYS:
        data = load_game_events(key)
        cnt = len(data.get("events", [])) if data else 0
        active = sum(1 for e in (data.get("events", []) if data else []) if e.get("status") == "进行中")
        lines.append(f"  {GAME_EMOJIS.get(key,'')} {GAME_NAMES.get(key, key)}: {active}进行中 / {cnt}总计")

    lines.append(f"\n{'─' * 25}")
    lines.append("💡 /活动 /卡池 /游戏新闻 /紧急活动")
    await status_cmd.finish("\n".join(lines))


# ── /强制更新新闻 (SUPERUSER) ──
@force_update_cmd.handle()
async def handle_force_update(bot: Bot, event: MessageEvent) -> None:
    await force_update_cmd.send("🔄 正在触发数据更新，请稍候...")

    scripts_dir = Path(plugin_config.game_event_scripts_dir)
    update_script = scripts_dir / "update.py"

    if not update_script.exists():
        await force_update_cmd.finish(f"❌ 更新脚本不存在: {update_script}")
        return

    result_msg: str = ""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(update_script),
            "--jobs", "2", "--timeout", "300",
            cwd=str(scripts_dir.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=360)
    except asyncio.TimeoutError:
        result_msg = "⚠ 更新超时（>360s），请检查脚本状态"
    except Exception as exc:
        logger.error(f"[GameNews] 强制更新异常: {exc}")
        result_msg = f"❌ 执行异常: {exc}"

    # 在 try/except 外部调用 finish()，避免捕获 FinishedException
    if result_msg:
        await force_update_cmd.finish(result_msg)
        return

    out_tail = (stdout.decode("utf-8", errors="replace") or "")[-600:]
    err_tail = (stderr.decode("utf-8", errors="replace") or "")[-300:]

    if proc.returncode == 0:
        updated = format_updated_time()
        await force_update_cmd.finish(
            f"✅ 数据更新完成！\n"
            f"更新时间: {updated}\n\n"
            f"--- 输出尾部 ---\n{out_tail}"
        )
    else:
        await force_update_cmd.finish(
            f"⚠ 更新脚本退出码 {proc.returncode}\n\n"
            f"--- stdout ---\n{out_tail}\n\n"
            f"--- stderr ---\n{err_tail}"
        )


# ═══════════════ 定时任务 ═══════════════

try:
    from nonebot_plugin_apscheduler import scheduler

    # ── 每日数据刷新 ──
    @scheduler.scheduled_job(
        "cron", hour=plugin_config.cron_hour, minute=plugin_config.cron_minute,
        id="gamenews_refresh", misfire_grace_time=300,
    )
    async def scheduled_refresh() -> None:
        """触发 game-event-progress 的数据更新流水线。"""
        if not plugin_config.enabled:
            return
        scripts_dir = Path(plugin_config.game_event_scripts_dir)
        update_script = scripts_dir / "update.py"
        if not update_script.exists():
            logger.warning(f"[GameNews] 更新脚本不存在: {update_script}")
            return

        logger.info("[GameNews] 触发数据更新...")
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(update_script),
                "--jobs", "2", "--timeout", "300",
                cwd=str(scripts_dir.parent),
            )
            await asyncio.wait_for(proc.communicate(), timeout=360)
            if proc.returncode == 0:
                logger.info("[GameNews] 数据更新完成")
            else:
                logger.warning(f"[GameNews] 更新脚本退出码 {proc.returncode}")
        except Exception as exc:
            logger.error(f"[GameNews] 数据更新异常: {exc}")


    # ── 每日推送 ──
    @scheduler.scheduled_job(
        "cron", hour=plugin_config.push_hour, minute=plugin_config.push_minute,
        id="gamenews_daily_push", misfire_grace_time=600,
    )
    async def scheduled_daily_push() -> None:
        """每日综合推送（图片）。"""
        if not plugin_config.enabled:
            return

        events = load_all_events()
        updated = format_updated_time()

        try:
            img = await render_events_image(
                events,
                title="活动进度 · 每日速报",
                subtitle="作战 · 卡池 · 活动 · 网页",
                updated=updated,
                mark_urgent=True,
            )
        except Exception as exc:
            logger.error(f"[GameNews] 每日推送渲染失败: {exc}")
            return

        # 合并推送目标
        targets: list[dict[str, str]] = []
        for gid in plugin_config.target_groups:
            targets.append({"target_type": "group", "target_id": str(gid)})
        for uid in plugin_config.target_users:
            targets.append({"target_type": "user", "target_id": str(uid)})
        for sub in storage.get_subscriptions():
            key = (sub["target_type"], sub["target_id"])
            if key not in {(t["target_type"], t["target_id"]) for t in targets}:
                targets.append(dict(sub))

        if not targets:
            return

        try:
            bot = get_bot()
        except ValueError:
            logger.warning("[GameNews] 无可用 Bot，跳过每日推送")
            return

        msg = Message()
        msg.append(MessageSegment.text(
            f"📋 游戏活动速报 · {updated}\n"
            f"共 {len(events)} 项进行中活动\n"
        ))
        msg.append(MessageSegment.image(img))
        msg.append(MessageSegment.text(
            "\n💡 /活动 /卡池 /游戏新闻 /紧急活动"
        ))

        for t in targets:
            try:
                if t["target_type"] == "group":
                    await bot.send_group_msg(group_id=int(t["target_id"]), message=msg)
                else:
                    await bot.send_private_msg(user_id=int(t["target_id"]), message=msg)
                await asyncio.sleep(1)
            except Exception as exc:
                logger.error(f"[GameNews] 推送失败 {t}: {exc}")


    # ── 紧迫提醒（多时间点） ──
    for _urgency_hour in plugin_config.urgency_cron_hours:
        @scheduler.scheduled_job(
            "cron", hour=_urgency_hour, minute=0,
            id=f"gamenews_urgency_{_urgency_hour}", misfire_grace_time=300,
        )
        async def scheduled_urgency_check(h: int = _urgency_hour) -> None:
            """紧迫事件检查（每小时整点）。"""
            from .urgency import check_and_push_urgent
            count = await check_and_push_urgent()
            if count > 0:
                logger.info(f"[GameNews] {h}:00 紧迫提醒: {count} 条已推送")

except ImportError:
    logger.warning("[GameNews] apscheduler 未安装，定时任务不可用")
