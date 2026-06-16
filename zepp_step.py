#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
ZeppLife 步数刷取工具
=====================
通过 Zepp Life（原小米运动）API 提交步数数据，同步到微信运动、支付宝运动。

前置条件：
  1. 下载 Zepp Life App，注册账号（支持手机号/邮箱）
  2. 在 App 内绑定第三方平台：我的 → 第三方接入 → 微信/支付宝

用法：
  python zepp_step.py -u <账号> -p <密码> -s <步数>
  python zepp_step.py -u <账号> -p <密码> --random 20000 50000
  python zepp_step.py -c config.json
"""

import argparse
import json
import logging
import random
import sys
import time

from zepp_client import ZeppClient, ZeppError

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("zepp_step")

# 默认步数随机范围
DEFAULT_MIN_STEPS = 20000
DEFAULT_MAX_STEPS = 35000

# ---------------------------------------------------------------------------
# 高封装：一站式提交
# ---------------------------------------------------------------------------

def run_once(account: str, password: str, steps: int) -> bool:
    """执行一次完整的「登录 → 获取 token → 提交步数」流程。"""
    log.info("=" * 56)
    log.info("开始处理账号: %s", account)
    log.info("目标步数: %d", steps)

    try:
        client = ZeppClient(logger=log)
        _, app_token, user_id = client.authenticate(account, password)
        result = client.submit_steps(user_id, app_token, steps)
        log.info("步数提交成功！账号=%s，步数=%d", account, result["steps"])
        return True
    except ZeppError as exc:
        log.error("%s", exc)
        return False
    finally:
        log.info("=" * 56)


# ---------------------------------------------------------------------------
# 配置文件支持
# ---------------------------------------------------------------------------

def load_config(path: str) -> list[dict]:
    """从 JSON 配置文件加载账号列表。"""
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    accounts = cfg.get("accounts", [])
    if not accounts:
        raise ValueError("配置文件中没有账号信息（accounts 为空）")
    return accounts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ZeppLife 步数刷取工具 — 将步数同步到微信/支付宝运动",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python zepp_step.py -u 13800138000 -p mypassword -s 25000
  python zepp_step.py -u user@mail.com -p mypassword --random 18000 30000
  python zepp_step.py -c config.json
        """,
    )

    # 互斥的账号来源
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("-u", "--user", help="Zepp Life 账号（手机号或邮箱）")
    source.add_argument("-c", "--config", help="JSON 配置文件路径（支持多账号）")

    parser.add_argument("-p", "--password", help="Zepp Life 密码")
    parser.add_argument("-s", "--steps", type=int, default=None, help="目标步数")
    parser.add_argument(
        "--random",
        nargs=2,
        type=int,
        metavar=("MIN", "MAX"),
        help="随机步数范围，如 --random 20000 35000",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=0,
        help="多账号之间的延迟秒数（仅 --config 模式）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示 DEBUG 级别日志"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --- 确定步数 ---
    if args.random:
        if args.random[0] < 1 or args.random[1] > 98800:
            parser.error("随机步数需在 1~98800 之间")
        if args.random[0] > args.random[1]:
            parser.error("随机步数最小值不能大于最大值")
        step_value = random.randint(args.random[0], args.random[1])
        log.info("随机步数范围 [%d, %d] → 本次: %d", args.random[0], args.random[1], step_value)
    elif args.steps is not None:
        if not 1 <= args.steps <= 98800:
            parser.error("步数需在 1~98800 之间")
        step_value = args.steps
    else:
        step_value = random.randint(DEFAULT_MIN_STEPS, DEFAULT_MAX_STEPS)
        log.info("未指定步数，使用默认随机范围 [%d, %d] → %d",
                 DEFAULT_MIN_STEPS, DEFAULT_MAX_STEPS, step_value)

    # --- 单账号模式 ---
    if args.user:
        if not args.password:
            parser.error("单账号模式需要提供 -p/--password")
        success = run_once(args.user, args.password, step_value)
        sys.exit(0 if success else 1)

    # --- 配置文件模式 ---
    if args.config:
        accounts = load_config(args.config)
        results = []
        for i, acct in enumerate(accounts):
            user = acct.get("user") or acct.get("account")
            pwd = acct.get("password") or acct.get("pwd")

            if not user or not pwd:
                log.error("第 %d 个账号缺少 user/account 或 password，跳过", i + 1)
                continue

            # 每个账号可以单独配置步数
            acct_steps = acct.get("steps")
            if acct_steps is None:
                # 使用全局步数
                s = step_value
            elif isinstance(acct_steps, list) and len(acct_steps) == 2:
                try:
                    minimum, maximum = map(int, acct_steps)
                except (TypeError, ValueError):
                    log.error("账号 %s 的随机步数范围无效，跳过", user)
                    results.append(False)
                    continue
                if minimum < 1 or maximum > 98800 or minimum > maximum:
                    log.error("账号 %s 的随机步数范围需满足 1 <= MIN <= MAX <= 98800，跳过", user)
                    results.append(False)
                    continue
                s = random.randint(minimum, maximum)
                log.info("账号 %s 自定义随机 [%d, %d] → %d",
                         user, minimum, maximum, s)
            else:
                try:
                    s = int(acct_steps)
                except (TypeError, ValueError):
                    log.error("账号 %s 的步数无效，跳过", user)
                    results.append(False)
                    continue
                if not 1 <= s <= 98800:
                    log.error("账号 %s 的步数需在 1~98800 之间，跳过", user)
                    results.append(False)
                    continue

            results.append(run_once(user, pwd, s))

            if i < len(accounts) - 1 and args.delay > 0:
                time.sleep(args.delay)

        all_ok = bool(results) and all(results)
        log.info("全部账号处理完毕，成功: %d/%d", sum(results), len(results))
        sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
