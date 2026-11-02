import json
import time
import random
import hashlib
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .http_client import HttpClient
from .reading import SmartReadingManager
from .utils import encode_data, calculate_hash, RandomHelper, CurlParser
from .config import WeReadConfig, UserConfig


class FatalSessionError(Exception):
    """用于表示会话无法继续的致命错误"""
    pass


class ReadingSession:
    """阅读会话统计"""
    
    def __init__(self, user_name: str = "default"):
        self.user_name = user_name
        self.start_time = datetime.now()
        self.end_time = None
        self.target_duration_minutes = 0
        self.actual_duration_seconds = 0
        self.credited_seconds = 0  # 服务器可能记入的有效阅读时长
        self.successful_reads = 0
        self.failed_reads = 0
        self.books_read: List[str] = []
        self.books_read_names: List[str] = []
        self.chapters_read: List[str] = []
        self.breaks_taken = 0
        self.total_break_time = 0
        self.response_times: List[float] = []

    @property
    def average_response_time(self) -> float:
        if self.response_times:
            return sum(self.response_times) / len(self.response_times)
        return 0.0

    @property
    def success_rate(self) -> float:
        total = self.successful_reads + self.failed_reads
        return (self.successful_reads / total * 100) if total > 0 else 0.0

    @property
    def actual_duration_formatted(self) -> str:
        minutes = self.actual_duration_seconds // 60
        seconds = self.actual_duration_seconds % 60
        return f"{minutes}分{seconds}秒"

    def get_statistics_summary(self) -> str:
        """获取统计摘要"""
        books_info = ", ".join(set(self.books_read_names)) if self.books_read_names else "无书名信息"
        credited_minutes = self.credited_seconds // 60
        credited_seconds_rem = self.credited_seconds % 60
        return f"""📊 微信读书自动阅读统计报告
👤 用户名称: {self.user_name}
⏰ 开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}
⏱️ 实际阅读: {self.actual_duration_formatted}
🎯 目标时长: {self.target_duration_minutes}分钟
✅ 成功请求: {self.successful_reads}次
❌ 失败请求: {self.failed_reads}次
📈 成功率: {self.success_rate:.1f}%
📚 阅读书籍: {len(set(self.books_read))}本 ({books_info})
📄 阅读章节: {len(set(self.chapters_read))}个
☕ 休息次数: {self.breaks_taken}次 (共{self.total_break_time}秒)
🚀 平均响应: {self.average_response_time:.2f}秒
🧾 服务器记入时长: {credited_minutes}分{credited_seconds_rem}秒

🎉 本次阅读任务完成！"""


class WeReadSessionManager:
    """微信读书会话管理器"""
    
    KEY = "3c5c8717f3daf09iop3423zafeqoi"
    READ_URL = "https://weread.qq.com/web/book/read"
    RENEW_URL = "https://weread.qq.com/web/login/renewal"
    FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"

    DEFAULT_DATA = {
        "appId": "app_id",
        "b": "book_id",
        "c": "chapter_id",
        "ci": "chapter_index",
        "co": "page_number",
        "sm": "content",
        "pr": "page_number",
        "rt": "reading_time",
        "ts": time.time() * 1000,
        "rn": "random_number",
        "sg": "sha256_hash",
        "ct": time.time(),
        "ps": "user_id",
        "pc": "device_id",
        "s": "36cc0815",
    }

    def __init__(self, config: WeReadConfig, user_config: UserConfig = None):
        self.config = config
        self.user_config = user_config
        self.user_name = user_config.name if user_config else "default"
        self.reading_config = config.reading
        self.http_client = HttpClient(
            config.network.timeout, 
            config.network.retry_times, 
            config.network.rate_limit
        )
        self.reading_manager = SmartReadingManager(self.reading_config)
        self.session_stats = ReadingSession(self.user_name)
        
        self.cookie_data = {
            "rq": "%2Fweb%2Fbook%2Fread",
            "ql": config.hack.cookie_refresh_ql,
        }
        
        self.headers = {}
        self.cookies = {}
        self.data = self.DEFAULT_DATA.copy()
        self.user_ps = None
        self.user_pc = None
        self.user_app_id = None
        # 连续未被接受的请求计数器（用于避免无限刷新cookie）
        self._consecutive_failures = 0

        # curl 源文件指纹与 cookie 持久化路径（用于每天无人值守续期）
        self._curl_source_hash = None
        self._state_file = None

        self._load_curl_config()

    def _load_curl_config(self):
        """加载CURL配置"""
        curl_content = ""

        # 如果是多用户模式，优先使用用户特定的配置
        if self.user_config:
            if self.user_config.file_path and Path(self.user_config.file_path).exists():
                try:
                    with open(self.user_config.file_path, "r", encoding="utf-8") as f:
                        curl_content = f.read().strip()
                    print(f"✅ 用户 {self.user_name} 已从文件加载CURL配置: {self.user_config.file_path}")
                except Exception as e:
                    logging.error(f"❌ 用户 {self.user_name} CURL配置文件读取失败: {e}")
            elif self.user_config.content:
                curl_content = self.user_config.content
                print(f"✅ 用户 {self.user_name} 已从配置加载CURL内容")

        # 回退到全局配置
        if not curl_content:
            if self.config.curl_file_path and Path(self.config.curl_file_path).exists():
                try:
                    with open(self.config.curl_file_path, "r", encoding="utf-8") as f:
                        curl_content = f.read().strip()
                    print(f"✅ 已从全局文件加载CURL配置: {self.config.curl_file_path}")
                except Exception as e:
                    logging.error(f"❌ 全局CURL配置文件读取失败: {e}")
            elif self.config.curl_content:
                curl_content = self.config.curl_content
                print("✅ 已从环境变量加载CURL配置")

        if not curl_content:
            raise ValueError(f"用户 {self.user_name} 未找到有效的CURL配置")

        # 解析CURL配置
        try:
            self.headers, self.cookies, curl_data = CurlParser.parse_curl_command(curl_content)

            # 记录源文件指纹，并加载上次续期后保存的 cookie
            self._curl_source_hash = hashlib.sha256(curl_content.encode("utf-8")).hexdigest()
            self._state_file = self._cookie_state_path()
            self._apply_cookie_state()

            # 如果没有 User-Agent，设置一个默认的
            if not any(k.lower() == "user-agent" for k in self.headers.keys()):
                self.headers["user-agent"] = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )

            if "content-type" not in {k.lower() for k in self.headers.keys()}:
                self.headers["Content-Type"] = "application/json; charset=utf-8"

            if curl_data:
                required_fields = ["appId", "b", "c"]
                missing_fields = [field for field in required_fields if field not in curl_data]

                if not missing_fields:
                    self.data.update(curl_data)
                    self.user_ps = self.data.get("ps")
                    self.user_pc = self.data.get("pc")
                    self.user_app_id = self.data.get("appId")
                    # 如果CURL中包含静态的s字段，保存为初始s备用
                    self._initial_s_from_curl = curl_data.get("s") if isinstance(curl_data.get("s"), str) else None
                    
                    print(f"✅ 用户 {self.user_name} 已使用CURL中的请求数据")

                    if "b" in curl_data and "c" in curl_data:
                        self.reading_manager.set_curl_data(curl_data["b"], curl_data["c"])
                else:
                    logging.warning(f"⚠️ 用户 {self.user_name} CURL数据缺少必需字段: {missing_fields}")
                    # 不设置空的CURL数据，保留阅读管理器由配置回退或稍后初始化
                    pass
            else:
                print(f"ℹ️ 用户 {self.user_name} CURL命令中未找到请求数据")
                # 未找到请求数据，阅读管理器将尝试使用配置数据或保持未初始化
                pass

            print(f"✅ 用户 {self.user_name} CURL配置解析成功")
        except Exception as e:
            logging.error(f"❌ 用户 {self.user_name} CURL配置解析失败: {e}")
            raise

    def _cookie_state_path(self) -> Optional[Path]:
        """cookie 状态文件放在 curl 源文件同目录；仅文件模式可用"""
        path = ""
        if self.user_config and self.user_config.file_path:
            path = self.user_config.file_path
        elif self.config.curl_file_path:
            path = self.config.curl_file_path
        if not path:
            return None
        return Path(path).resolve().parent / "cookies_state.json"

    def _apply_cookie_state(self):
        """加载上次续期保存的 cookie（仅当 curl 源文件未变化时生效）"""
        if not self._state_file or not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
            if state.get("source_sha256") != self._curl_source_hash:
                logging.info("ℹ️ curl_command.txt 已更新，忽略旧的 cookie 状态")
                return
            cached = state.get("cookies") or {}
            applied = []
            for name in ("wr_skey", "wr_vid", "wr_rt", "wr_pf", "wr_ql"):
                value = cached.get(name)
                if value and value != "undefined":
                    self.cookies[name] = value
                    applied.append(name)
            if applied:
                logging.info(f"🔑 已加载持久化 cookie: {', '.join(applied)}")
        except Exception as e:
            logging.debug(f"⚠️ 读取 cookie 状态失败: {e}")

    def _save_cookie_state(self):
        """续期成功后把最新 cookie 落盘，供下一次运行复用"""
        if not self._state_file or not self._curl_source_hash:
            return
        try:
            cookies = {
                name: self.cookies.get(name)
                for name in ("wr_skey", "wr_vid", "wr_rt", "wr_pf", "wr_ql")
                if self.cookies.get(name) and self.cookies.get(name) != "undefined"
            }
            state = {
                "source_sha256": self._curl_source_hash,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "cookies": cookies,
            }
            tmp = self._state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.chmod(0o600)
            tmp.replace(self._state_file)
            logging.debug(f"💾 已持久化 cookie 状态: {self._state_file}")
        except Exception as e:
            logging.debug(f"⚠️ 保存 cookie 状态失败: {e}")

    async def start_reading_session(self) -> ReadingSession:
        """开始阅读会话"""
        user_info = f" (用户: {self.user_name})" if self.user_config else ""
        print(f"🚀 微信读书阅读机器人启动{user_info}")
        print(f"📋 配置信息: 阅读模式 {self.reading_config.mode}, 目标时长 {self.reading_config.target_duration} 分钟")

        # 启动延迟
        startup_delay = RandomHelper.get_random_int_from_range(self.config.startup_delay)
        print(f"⏳ 启动延迟 {startup_delay} 秒...")
        await asyncio.sleep(startup_delay)

        # 设置会话统计
        target_minutes = RandomHelper.get_random_int_from_range(self.reading_config.target_duration)
        self.session_stats.start_time = datetime.now()
        self.session_stats.target_duration_minutes = target_minutes

        print(f"🎯 本次目标阅读时长: {target_minutes} 分钟")

        # 刷新cookie
        if not await self._refresh_cookie():
            raise Exception("Cookie刷新失败，程序终止")

        # 确保阅读管理器已初始化（存在可读书籍/章节）
        if not self.reading_manager.ensure_initialized():
            error_msg = (
                "❌ 无可用书籍或章节（既没有有效的CURL请求数据，也没有在配置中找到书籍），"
                "请检查 config.yaml 或 WEREAD_CURL_STRING"
            )
            logging.error(error_msg)
            # 抛出异常以便上层能够发送通知并停止会话
            raise FatalSessionError(error_msg)

        # 验证关键身份字段是否存在（ps, pc, appId）
        if not (self.user_ps and self.user_pc and self.user_app_id):
            error_msg = (
                "❌ 缺少用户身份标识（ps/pc/appId），无法进行有效的阅读请求。\n"
                "请提供包含 appId、ps、pc 的 CURL 字符串或在配置文件中添加用户信息。"
            )
            logging.error(error_msg)
            raise FatalSessionError(error_msg)
        
         # 开始阅读循环
        target_seconds = target_minutes * 60
        last_time = int(time.time()) - 30
        credited_seconds = 0
         # 安全限制，避免因持续失败导致无限循环（最多允许达到目标时长的3倍）
        max_wall_seconds = max(target_seconds * 3, target_seconds + 600)

        try:
            while credited_seconds < target_seconds and self.session_stats.actual_duration_seconds < max_wall_seconds:
                try:
                    # 模拟阅读请求，返回是否被服务器认可和响应时间，以及本次可记入的时长（秒）
                    success, response_time, credited = await self._simulate_reading_request(last_time)

                    if success:
                        self.session_stats.successful_reads += 1
                        credited_seconds += credited
                        # 立即将last_time设为现在，下一次rt基于当前时间计算
                        last_time = int(time.time())
                        print(f"✅ 阅读成功，已记入 {credited} 秒（累计 {credited_seconds} 秒 / 目标 {target_seconds} 秒）")
                    else:
                        self.session_stats.failed_reads += 1

                    # 记录响应时间
                    self.session_stats.response_times.append(response_time)

                    # 更新实际运行时长（wall-clock），无论成功或失败都更新
                    current_time = datetime.now()
                    duration_delta = current_time - self.session_stats.start_time
                    self.session_stats.actual_duration_seconds = int(duration_delta.total_seconds())

                    progress_minutes = self.session_stats.actual_duration_seconds // 60
                    credited_minutes = credited_seconds // 60
                    print(f"📊 进度(服务器记入/目标): {credited_minutes}分 / {target_minutes}分，实际运行: {progress_minutes}分")

                    # 获取下次阅读间隔
                    interval = RandomHelper.get_random_from_range(self.reading_config.reading_interval)
                    await asyncio.sleep(interval)

                except FatalSessionError as e:
                    # 致命错误，终止会话并向上抛出
                    logging.error(f"💀 致命错误，终止会话: {e}")
                    raise
                except Exception as e:
                    logging.error(f"❌ 阅读请求异常: {e}")
                    self.session_stats.failed_reads += 1
                    await asyncio.sleep(30)

            # 完成会话
            self.session_stats.end_time = datetime.now()
            # 最终同步记入的时长
            self.session_stats.credited_seconds = credited_seconds
            # 最终更新实际运行时长
            final_delta = self.session_stats.end_time - self.session_stats.start_time
            self.session_stats.actual_duration_seconds = int(final_delta.total_seconds())
            print("🎉 阅读任务完成！")

            if credited_seconds < target_seconds:
                logging.warning(f"⚠️ 未能达到目标的记入时长: 目标 {target_seconds}s, 实际记入 {credited_seconds}s")

            return self.session_stats
        finally:
            await self.http_client.close()

    async def _simulate_reading_request(self, last_time: int) -> Tuple[bool, float]:
        """模拟阅读请求"""
        self.data.pop("s", None)

        # 使用智能阅读管理器获取下一个阅读位置
        book_id, chapter_id = self.reading_manager.get_next_reading_position()
        self.data["b"] = book_id
        self.data["c"] = chapter_id

        # 设置章节索引（ci），如果有的话
        chapter_ci = getattr(self.reading_manager, "current_chapter_ci", None)
        if chapter_ci is not None:
            self.data["ci"] = chapter_ci
            logging.debug(f"🔢 设置章节索引: ci={chapter_ci} (章节: {chapter_id})")
        else:
            self.data.pop("ci", None)

        # 记录阅读内容
        if book_id not in self.session_stats.books_read:
            self.session_stats.books_read.append(book_id)
            book_name = self.reading_manager.book_names_map.get(
                book_id, f"未知书籍({book_id[:10]}...)"
            )
            if book_name not in self.session_stats.books_read_names:
                self.session_stats.books_read_names.append(book_name)
        
        if chapter_id not in self.session_stats.chapters_read:
            self.session_stats.chapters_read.append(chapter_id)

        # 确保用户身份标识符的正确性
        if self.user_ps:
            self.data["ps"] = self.user_ps
        if self.user_pc:
            self.data["pc"] = self.user_pc
        if self.user_app_id:
            self.data["appId"] = self.user_app_id

        # 更新时间戳
        current_time = int(time.time())
        self.data["ct"] = current_time
        self.data["rt"] = current_time - last_time
        self.data["ts"] = int(current_time * 1000) + random.randint(0, 1000)
        self.data["rn"] = random.randint(0, 1000)
        
        signature_string = f"{self.data['ts']}{self.data['rn']}{self.KEY}"
        self.data["sg"] = hashlib.sha256(signature_string.encode()).hexdigest()
        # 先计算一个默认的s
        calculated_s = calculate_hash(encode_data(self.data))
        
        # 如果CURL提供了初始s，先尝试使用该s（有时CURL中的s是正确的）
        initial_s = getattr(self, "_initial_s_from_curl", None)
        if initial_s:
            # 尝试一次使用初始s
            self.data["s"] = initial_s
            try:
                resp_try, rt_try = await self.http_client.post_raw(
                    self.READ_URL, headers=self.headers, cookies=self.cookies, json_data=self.data
                )
                try:
                    raw_try = resp_try.text
                except Exception:
                    raw_try = ""
                try:
                    json_try = resp_try.json()
                except Exception:
                    json_try = {}

                if bool(json_try.get("succ") or json_try.get("success")):
                    # 提取记入时长
                    def _extr(obj):
                        if not isinstance(obj, dict):
                            return None
                        keys = ["addTime", "add_time", "readTime", "read_time", "time", "duration", "inc", "increase", "added", "addedTime"]
                        for k in keys:
                            if k in obj and isinstance(obj[k], (int, float)):
                                return int(obj[k])
                        for v in obj.values():
                            if isinstance(v, dict):
                                f = _extr(v)
                                if f is not None:
                                    return f
                        return None

                    extv = _extr(json_try)
                    credited_try = extv if extv is not None else int(self.data.get("rt", 0)) if isinstance(self.data.get("rt", 0), (int, float)) else 0
                    logging.info(f"✅ 使用CURL中的s字段首次尝试被接受，记入: {credited_try} 秒")
                    self._consecutive_failures = 0
                    return True, rt_try, credited_try
                else:
                    logging.debug(f"❌ 使用CURL中的s字段尝试失败，继续使用计算的s进行请求 (尝试响应: {json_try} raw: {raw_try})")
            except Exception as e:
                logging.debug(f"⚠️ 使用CURL s 字段尝试请求异常: {e}")

        # 默认使用计算得到的s继续之后的请求流程
        self.data["s"] = calculated_s

        try:
            # 发送请求（使用 post_raw 以便获取原始响应文本）
            # DEBUG：打印将要发送的请求（脱敏）
            try:
                masked_cookies = {
                    k: (v[:4] + "***" if isinstance(v, str) and len(v) > 4 else "***")
                    for k, v in self.cookies.items()
                }
            except Exception:
                masked_cookies = {k: "***" for k in self.cookies.keys()}

            # 掩码敏感字段并打印请求要点
            sanitized = {k: ("***" if k in ("ps", "pc") else self.data.get(k)) for k in ("b", "c", "ci", "rt", "ps", "pc")}
            logging.debug(f"➡️ 发送阅读请求(摘要): {sanitized}, headers={list(self.headers.keys())}, cookies_keys={list(self.cookies.keys())}")
            logging.debug(f"🔐 Cookies(脱敏): {masked_cookies}")

            response, response_time = await self.http_client.post_raw(
                self.READ_URL, headers=self.headers, cookies=self.cookies, json_data=self.data
            )

            # 读取原始文本并尝试解析为JSON
            try:
                raw_text = response.text
            except Exception:
                raw_text = ""

            try:
                response_data = response.json()
            except Exception:
                logging.debug(f"⚠️ 响应无法解析为JSON，原始响应: {raw_text}")
                response_data = {}

            logging.debug(f"📕 响应数据: {response_data} (raw: {raw_text})")

            # 服务器返回成功标记（succ）通常意味着本次阅读被接受
            succ_flag = bool(response_data.get("succ") or response_data.get("success"))
            if succ_flag:
                # 尝试从响应中提取服务器返回的时长增量（若存在）
                def _extract_credited(obj):
                    if not isinstance(obj, dict):
                        return None
                    keys = [
                        "addTime",
                        "add_time",
                        "readTime",
                        "read_time",
                        "time",
                        "duration",
                        "inc",
                        "increase",
                        "added",
                        "addedTime",
                    ]
                    for k in keys:
                        if k in obj and isinstance(obj[k], (int, float)):
                            return int(obj[k])
                    for v in obj.values():
                        if isinstance(v, dict):
                            found = _extract_credited(v)
                            if found is not None:
                                return found
                    return None

                extracted = _extract_credited(response_data)
                credited = extracted if extracted is not None else int(self.data.get("rt", 0)) if isinstance(self.data.get("rt", 0), (int, float)) else 0

                # 如果缺少 synckey，记录并尝试异步修复，但仍然认为本次可能已被记入
                if "synckey" not in response_data:
                    logging.warning(f"⚠️ 返回缺少 synckey，尝试异步修复，但仍计为已接受（响应: {response_data}）")
                    try:
                        asyncio.create_task(self._fix_no_synckey())
                    except Exception:
                        await self._fix_no_synckey()

                logging.debug(f"✅ 请求被接受，计入时长: {credited} 秒")
                # 成功后重置失败计数
                self._consecutive_failures = 0
                return True, response_time, credited

            # 非succ - 视为失败
            logging.warning(f"❌ 请求失败或未被接受: {response_data} (raw: {raw_text})")
            self._consecutive_failures += 1

            # On first failure, attempt a fallback using URL-encoded form data (some endpoints expect form-encoded body)
            if self._consecutive_failures == 1:
                try:
                    encoded_body = encode_data(self.data)
                    headers_form = self.headers.copy()
                    headers_form["Content-Type"] = "application/x-www-form-urlencoded"

                    logging.debug("🔁 尝试使用表单编码的回退请求 (application/x-www-form-urlencoded)")
                    form_resp, form_rt = await self.http_client.post_raw(
                        self.READ_URL, headers=headers_form, cookies=self.cookies, data=encoded_body
                    )

                    try:
                        form_raw = form_resp.text
                    except Exception:
                        form_raw = ""

                    try:
                        form_data = form_resp.json()
                    except Exception:
                        logging.debug(f"⚠️ 回退响应无法解析为JSON，原始响应: {form_raw}")
                        form_data = {}

                    logging.debug(f"📕 回退响应数据: {form_data} (raw: {form_raw})")

                    form_succ = bool(form_data.get("succ") or form_data.get("success"))
                    if form_succ:
                        extracted2 = None

                        def _extract_credited2(obj):
                            if not isinstance(obj, dict):
                                return None
                            keys2 = ["addTime", "add_time", "readTime", "read_time", "time", "duration", "inc", "increase", "added", "addedTime"]
                            for k in keys2:
                                if k in obj and isinstance(obj[k], (int, float)):
                                    return int(obj[k])
                            for v in obj.values():
                                if isinstance(v, dict):
                                    found2 = _extract_credited2(v)
                                    if found2 is not None:
                                        return found2
                            return None

                        extracted2 = _extract_credited2(form_data)
                        credited2 = extracted2 if extracted2 is not None else (int(self.data.get("rt", 0)) if isinstance(self.data.get("rt", 0), (int, float)) else 0)
                        logging.debug(f"✅ 表单回退请求被接受，计入时长: {credited2} 秒")
                        self._consecutive_failures = 0
                        return True, form_rt, credited2
                    else:
                        logging.debug("🔁 表单回退请求未被接受，继续常规处理")
                except Exception as e:
                    logging.debug(f"⚠️ 表单回退请求异常: {e}")

            # 如果第一次回退也不成功，则继续按原逻辑：在限制内尝试刷新cookie或在多次失败后终止
            if self._consecutive_failures == 2:
                try:
                    logging.debug("🔬 连续失败，尝试不同的 s 变体以寻求可被接受的签名")
                    ok, ok_rt, ok_credited = await self._try_s_variants()
                    if ok:
                        logging.info("✅ s 变体尝试成功，继续会话")
                        return True, ok_rt, ok_credited
                except Exception as e:
                    logging.debug(f"⚠️ s 变体尝试异常: {e}")

            if self._consecutive_failures >= 3:
                error_msg = (
                    f"连续{self._consecutive_failures}次阅读请求未被接受，最后响应: {response_data} (raw: {raw_text}). "
                    "请检查CURL请求中是否包含必要的请求数据(appId, ps, pc)或确认Cookie/Headers是否完整。"
                )
                logging.error(error_msg)
                raise FatalSessionError(error_msg)

            # 否则尝试刷新cookie一次
            try:
                await self._refresh_cookie()
            except Exception:
                logging.debug("刷新cookie失败或未能修复问题")

            return False, response_time, 0
        except FatalSessionError:
            raise
        except Exception as e:
            logging.error(f"❌ 请求异常: {e}")
            return False, 0.0, 0

    async def _try_s_variants(self) -> Tuple[bool, float, int]:
        """尝试不同的s字段变体，看是否能让请求被接受。返回 (success, response_time, credited)"""
        # 防止重复尝试
        if getattr(self, "_s_variants_tried", False):
            return False, 0.0, 0

        self._s_variants_tried = True

        # 生成候选s值
        base = calculate_hash(encode_data(self.data))
        candidates = []
        candidates.append(base)
        # 最后8位
        if len(base) > 8:
            candidates.append(base[-8:])
            candidates.append(base[:8])
            # 32位截断
            try:
                val = int(base, 16) & 0xFFFFFFFF
                candidates.append(hex(val)[2:].lower())
            except Exception:
                pass

        logging.debug(f"🔬 尝试 s 变体: {candidates}")

        for s_variant in candidates:
            # 备份原始s
            old_s = self.data.get("s")
            self.data["s"] = s_variant
            logging.debug(f"➡️ 尝试 s={s_variant} 并发送请求")

            try:
                resp, rt = await self.http_client.post_raw(
                    self.READ_URL, headers=self.headers, cookies=self.cookies, json_data=self.data
                )
                try:
                    raw = resp.text
                except Exception:
                    raw = ""
                try:
                    resp_json = resp.json()
                except Exception:
                    logging.debug(f"⚠️ s 变体响应非JSON: {raw}")
                    resp_json = {}

                succ = bool(resp_json.get("succ") or resp_json.get("success"))
                if succ:
                    # 提取记入时长
                    credited = 0
                    def _ext(obj):
                        if not isinstance(obj, dict):
                            return None
                        keys = ["addTime", "add_time", "readTime", "read_time", "time", "duration", "inc", "increase", "added", "addedTime"]
                        for k in keys:
                            if k in obj and isinstance(obj[k], (int, float)):
                                return int(obj[k])
                        for v in obj.values():
                            if isinstance(v, dict):
                                found = _ext(v)
                                if found is not None:
                                    return found
                        return None
                    extv = _ext(resp_json)
                    if extv is not None:
                        credited = extv
                    else:
                        credited = int(self.data.get("rt", 0)) if isinstance(self.data.get("rt", 0), (int, float)) else 0

                    logging.info(f"✅ s 变体 {s_variant} 被接受，计入时长: {credited} 秒")
                    self._consecutive_failures = 0
                    return True, rt, credited

            except Exception as e:
                logging.debug(f"⚠️ s 变体请求异常: {e}")
            finally:
                # 恢复旧的s
                if old_s is None:
                    self.data.pop("s", None)
                else:
                    self.data["s"] = old_s

        return False, 0.0, 0

    async def _refresh_cookie(self) -> bool:
        """刷新cookie"""
        print("🍪 刷新cookie...")

        try:
            response, _ = await self.http_client.post_raw(
                self.RENEW_URL,
                headers=self.headers,
                cookies=self.cookies,
                json_data=self.cookie_data,
            )

            new_skey = response.cookies.get("wr_skey")

            if not new_skey:
                # 备用：从Set-Cookie解析
                set_cookie = response.headers.get("set-cookie", "")
                for cookie in set_cookie.split(","):
                    if "wr_skey" in cookie:
                        parts = cookie.split(";")[0]
                        if "=" in parts:
                            new_skey = parts.split("=", 1)[1].strip()
                            break

            if not new_skey:
                logging.error("❌ Cookie刷新失败，未找到wr_skey")
                return False

            self.cookies["wr_skey"] = new_skey
            # 同步续期返回的其它 cookie（wr_rt 是长期刷新令牌，务必保留）
            for name in ("wr_vid", "wr_rt", "wr_pf"):
                value = response.cookies.get(name)
                if value and value != "undefined":
                    self.cookies[name] = value
            self._save_cookie_state()
            print(f"✅ Cookie刷新成功，新密钥: {new_skey[:8]}***")
            return True

        except Exception as e:
            logging.error(f"❌ Cookie刷新失败: {e}")

        return False

    async def _fix_no_synckey(self):
        """修复synckey问题"""
        try:
            await self.http_client.post_raw(
                self.FIX_SYNCKEY_URL,
                headers=self.headers,
                cookies=self.cookies,
                json_data={"bookIds": ["3300060341"]},
            )
        except Exception as e:
            logging.error(f"❌ 修复synckey失败: {e}")
