#!/usr/bin/env python3
"""
微信读书自动阅读机器人 - 简化版
核心功能：从CURL命令中提取请求数据，循环发送阅读请求积累时长
"""
import re
import json
import time
import random
import hashlib
import urllib.parse
import argparse
import logging
import requests
from pathlib import Path
from typing import Dict, Tuple, Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

KEY = "3c5c8717f3daf09iop3423zafeqoi"
READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"


def parse_curl_command(curl_command: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
    """从CURL命令中解析headers、cookies和请求数据"""
    headers_temp = {}

    for match in re.findall(r"-H ['\"]([^:]+): ([^'\"]+)['\"]", curl_command):
        headers_temp[match[0]] = match[1]

    cookies = {}
    cookie_header = next((v for k, v in headers_temp.items() if k.lower() == "cookie"), "")
    cookie_b = re.search(r"-b ['\"]([^'\"]+)['\"]", curl_command)
    cookie_string = cookie_b.group(1) if cookie_b else cookie_header

    if cookie_string:
        for cookie in cookie_string.split("; "):
            if "=" in cookie:
                key, value = cookie.split("=", 1)
                cookies[key.strip()] = value.strip()

    headers = {k: v for k, v in headers_temp.items() if k.lower() != "cookie"}

    request_data = {}
    data_match = re.search(r"(?:--data-raw|--data|-d)\s+(['\"])(.*?)\1", curl_command, re.DOTALL)
    if data_match:
        data_str = data_match.group(2).strip()
        try:
            request_data = json.loads(data_str)
        except json.JSONDecodeError as e:
            logger.warning(f"解析请求数据失败: {e}")

    return headers, cookies, request_data


def encode_data(data: dict) -> str:
    encoded_pairs = [f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys())]
    return "&".join(encoded_pairs)


def calculate_hash(input_string: str) -> str:
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        char_code = ord(input_string[_19094e])
        shift_amount = (length - _19094e) % 30
        _7032f5 = 0x7FFFFFFF & (_7032f5 ^ char_code << shift_amount)

        prev_char_code = ord(input_string[_19094e - 1])
        prev_shift_amount = _19094e % 30
        _cc1055 = 0x7FFFFFFF & (_cc1055 ^ prev_char_code << prev_shift_amount)
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()


def load_curl_file(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"CURL文件不存在: {file_path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def refresh_cookie(headers: Dict, cookies: Dict, cookie_data: Dict) -> bool:
    if cookies.get("wr_skey"):
        logger.info("使用现有cookie")
        return True

    logger.info("刷新cookie...")
    try:
        response = requests.post(RENEW_URL, headers=headers, cookies=cookies, json=cookie_data, timeout=30)
        new_skey = response.cookies.get("wr_skey")
        if not new_skey:
            set_cookie = response.headers.get("set-cookie", "")
            for cookie in set_cookie.split(","):
                if "wr_skey" in cookie:
                    parts = cookie.split(";")[0]
                    if "=" in parts:
                        new_skey = parts.split("=", 1)[1].strip()
                        break
        if not new_skey:
            logger.error("Cookie刷新失败")
            return False
        cookies["wr_skey"] = new_skey
        logger.info("Cookie刷新成功")
        return True
    except Exception as e:
        logger.error(f"Cookie刷新失败: {e}")
        return False


def send_reading_request(
    session: requests.Session,
    url: str,
    headers: Dict,
    cookies: Dict,
    data: Dict,
    initial_s: Optional[str] = None
) -> Tuple[bool, int]:
    """发送阅读请求，优先使用CURL中的s值"""
    # 先尝试使用初始s值（来自CURL）
    if initial_s:
        test_data = data.copy()
        test_data["s"] = initial_s
        try:
            response = session.post(url, headers=headers, cookies=cookies, json=test_data, timeout=30)
            resp_data = response.json()
            logger.debug(f"CURL-s响应: {resp_data}")
            if resp_data.get("succ") or resp_data.get("success"):
                credited = 0
                for key in ["addTime", "add_time", "readTime", "read_time", "time", "duration", "inc"]:
                    if key in resp_data and isinstance(resp_data[key], (int, float)):
                        credited = int(resp_data[key])
                        break
                if credited == 0:
                    credited = int(data.get("rt", 0)) if isinstance(data.get("rt", 0), (int, float)) else 0
                logger.info(f"使用CURL中的s成功，记入 {credited}秒")
                return True, credited
        except Exception as e:
            logger.debug(f"尝试CURL中的s异常: {e}")

    # 使用计算的s
    data["s"] = calculate_hash(encode_data(data))
    try:
        response = session.post(url, headers=headers, cookies=cookies, json=data, timeout=30)
        response.raise_for_status()
        resp_data = response.json()
        logger.debug(f"响应: {resp_data}")
        succ = resp_data.get("succ") or resp_data.get("success")
        if succ:
            credited = 0
            for key in ["addTime", "add_time", "readTime", "read_time", "time", "duration", "inc"]:
                if key in resp_data and isinstance(resp_data[key], (int, float)):
                    credited = int(resp_data[key])
                    break
            if credited == 0:
                credited = int(data.get("rt", 0)) if isinstance(data.get("rt", 0), (int, float)) else 0
            return True, credited
        # 检查是否是登录超时错误
        if resp_data.get("errCode") == -2012:
            logger.warning("Cookie已过期，需要重新抓取CURL")
        else:
            logger.warning(f"请求未接受: {resp_data}")
        return False, 0
    except Exception as e:
        logger.error(f"请求失败: {e}")
        return False, 0


def main():
    parser = argparse.ArgumentParser(description="微信读书自动阅读机器人")
    parser.add_argument("-c", "--curl", default="curl_command.txt", help="CURL命令文件")
    parser.add_argument("-t", "--target", default="60", help="目标时长(分钟)")
    parser.add_argument("-i", "--interval", default="30", help="请求间隔(秒)")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"加载CURL: {args.curl}")
    curl_content = load_curl_file(args.curl)
    headers, cookies, curl_data = parse_curl_command(curl_content)

    if "user-agent" not in {k.lower() for k in headers.keys()}:
        headers["user-agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    headers.setdefault("Content-Type", "application/json; charset=utf-8")

    required_fields = ["appId", "b", "c", "ps", "pc"]
    missing = [f for f in required_fields if f not in curl_data]
    if missing:
        logger.error(f"缺少字段: {missing}")
        return

    # 保存初始s值（来自CURL）
    initial_s = curl_data.get("s")

    # 获取书籍ID用于设置referer
    book_id = curl_data.get("b", "")

    data = {
        "appId": curl_data.get("appId"),
        "b": curl_data.get("b"),
        "c": curl_data.get("c"),
        "ci": curl_data.get("ci"),
        "co": curl_data.get("co", 1),
        "pr": curl_data.get("pr", 1),
        "ps": curl_data.get("ps"),
        "pc": curl_data.get("pc"),
    }

    target_seconds = int(args.target) * 60
    interval = int(args.interval)

    logger.info(f"目标: {args.target}分钟, 间隔: {interval}秒")

    cookie_data = {"rq": "%2Fweb%2Fbook%2Fread", "ql": ""}
    if not refresh_cookie(headers, cookies, cookie_data):
        logger.error("Cookie刷新失败")
        return

    session = requests.Session()
    start_time = time.time()
    credited_seconds = 0
    successful_reads = 0
    failed_reads = 0
    last_time = int(time.time()) - 30

    while credited_seconds < target_seconds:
        current_time = int(time.time())
        data["rt"] = current_time - last_time
        data["ts"] = int(current_time * 1000) + random.randint(0, 1000)
        data["rn"] = random.randint(0, 1000)
        data["ct"] = current_time
        last_time = current_time

        # 动态设置referer
        if book_id:
            headers["Referer"] = f"https://weread.qq.com/web/reader/{book_id}"

        success, credited = send_reading_request(session, READ_URL, headers, cookies, data, initial_s)

        if success:
            successful_reads += 1
            credited_seconds += credited
            last_time = int(time.time())
            logger.info(f"记入 {credited}秒 (累计 {credited_seconds}/{target_seconds}秒)")
        else:
            failed_reads += 1

        elapsed = int(time.time() - start_time)
        progress = credited_seconds / target_seconds * 100
        logger.info(f"进度: {credited_seconds}s/{target_seconds}s ({progress:.1f}%), 运行: {elapsed//60}分{elapsed%60}秒")

        time.sleep(interval)

    total_time = int(time.time() - start_time)
    logger.info("完成!")
    logger.info(f"记入时长: {credited_seconds}秒 ({credited_seconds//60}分{credited_seconds%60}秒)")
    logger.info(f"运行时长: {total_time}秒 ({total_time//60}分{total_time%60}秒)")
    logger.info(f"成功: {successful_reads}, 失败: {failed_reads}")


if __name__ == "__main__":
    main()