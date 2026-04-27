import os
import re
import json
import random
import hashlib
import logging
import urllib.parse
from typing import Tuple, Dict, Any


class RandomHelper:
    @staticmethod
    def parse_range(range_str: str) -> Tuple[float, float]:
        if "-" in range_str:
            parts = range_str.split("-", 1)
            return float(parts[0]), float(parts[1])
        else:
            value = float(range_str)
            return value, value

    @staticmethod
    def get_random_from_range(range_str: str) -> float:
        min_val, max_val = RandomHelper.parse_range(range_str)
        return random.uniform(min_val, max_val)

    @staticmethod
    def get_random_int_from_range(range_str: str) -> int:
        return int(RandomHelper.get_random_from_range(range_str))


class CurlParser:
    @staticmethod
    def parse_curl_command(curl_command: str) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
        headers_temp = {}

        # 支持单引号和双引号
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

        # 寻找数据参数（支持 --data-raw, --data, -d）
        # 匹配参数后跟单引号或双引号的内容
        # 使用非贪婪匹配 *? 来确保只匹配到第一个匹配的引号
        data_match = re.search(r"(?:--data-raw|--data|-d)\s+(['\"])(.*?)\1", curl_command, re.DOTALL)

        if data_match:
            quote_char = data_match.group(1)
            data_str = data_match.group(2)

            # 如果是双引号，处理转义的引号
            if quote_char == '"':
                data_str = data_str.replace(r'\"', '"')

            # 去除结尾可能的空白和换行
            data_str = data_str.strip()

            try:
                request_data = json.loads(data_str)
            except json.JSONDecodeError as e:
                logging.warning(f"解析请求数据失败: {e}, 数据内容: {data_str[:100]}...")
                request_data = {}

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
