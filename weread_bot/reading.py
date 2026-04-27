import time
import random
import logging
from typing import List, Tuple, Optional
from .config import ReadingConfig, BookInfo
from .utils import RandomHelper


class SmartReadingManager:
    def __init__(self, reading_config: ReadingConfig):
        self.config = reading_config
        self.current_book_id = ""
        self.current_chapter_id = ""
        self.current_book_chapters = []
        self.current_chapter_index = 0
        self.current_chapter_ci: Optional[int] = None
        self.last_book_switch_time = 0
        self.book_chapters_map = {book.book_id: book.chapters for book in reading_config.books}
        self.book_names_map = {book.book_id: book.name for book in reading_config.books}
        # 章节信息映射
        self.book_chapter_infos_map = {book.book_id: book.chapter_infos for book in reading_config.books}
        self.chapter_index_map = {}
        for book in reading_config.books:
            for chapter_info in book.chapter_infos:
                if chapter_info.chapter_index is not None:
                    self.chapter_index_map[chapter_info.chapter_id] = chapter_info.chapter_index

    def get_chapter_index(self, chapter_id: str, curl_ci: Optional[int] = None) -> Optional[int]:
        """获取章节索引，优先级：配置的索引值 > CURL提供的ci > 自动计算的索引"""
        # 优先使用配置的索引
        if chapter_id in self.chapter_index_map:
            return self.chapter_index_map[chapter_id]

        # 然后使用CURL中的ci
        if curl_ci is not None:
            return curl_ci

        # 最后尝试根据当前书籍列表计算索引
        if self.current_book_chapters and chapter_id in self.current_book_chapters:
            return self.current_book_chapters.index(chapter_id)

        return None

    def set_curl_data(self, book_id: str, chapter_id: str, curl_ci: Optional[int] = None):
        """设置从CURL提取的数据作为起点，支持动态添加书籍/章节"""
        if not book_id or not chapter_id:
            return False

        book_name = self.book_names_map.get(book_id, f"动态书籍({book_id[:8]}...)")

        if book_id in self.book_chapters_map:
            chapters = self.book_chapters_map[book_id]
            if chapter_id in chapters:
                self.current_book_id = book_id
                self.current_book_name = book_name
                self.current_chapter_id = chapter_id
                self.current_book_chapters = chapters
                self.current_chapter_index = chapters.index(chapter_id)
                self.current_chapter_ci = self.get_chapter_index(chapter_id, curl_ci)
                return True
            else:
                # 添加章节到现有书籍
                self.book_chapters_map[book_id].append(chapter_id)
                self.current_book_id = book_id
                self.current_book_name = book_name
                self.current_chapter_id = chapter_id
                self.current_book_chapters = self.book_chapters_map[book_id]
                self.current_chapter_index = len(self.current_book_chapters) - 1
                self.current_chapter_ci = self.get_chapter_index(chapter_id, curl_ci)
                return True
        else:
            # 新书籍
            self.book_chapters_map[book_id] = [chapter_id]
            self.book_names_map[book_id] = book_name
            self.current_book_id = book_id
            self.current_book_name = book_name
            self.current_chapter_id = chapter_id
            self.current_book_chapters = [chapter_id]
            self.current_chapter_index = 0
            self.current_chapter_ci = self.get_chapter_index(chapter_id, curl_ci)
            return True

    def get_next_reading_position(self) -> Tuple[str, str]:
        # 在返回位置前确保已初始化（有可读的书籍/章节）
        if not self.ensure_initialized():
            raise RuntimeError("阅读管理器初始化失败：无可用书籍或章节，请检查 CURL 或配置文件")

        mode = self.config.mode
        if mode == "smart_random":
            return self._smart_random_position()
        elif mode == "sequential":
            return self._sequential_position()
        else:
            return self._pure_random_position()

    def _smart_random_position(self) -> Tuple[str, str]:
        logging.debug(
            f"🔍 智能随机模式 - 当前书籍: "
            f"《{getattr(self, 'current_book_name', '未知')}》({self.current_book_id[:10]}...), "
            f"当前章节: {self.current_chapter_id}"
        )

        if not self.current_book_id or not self.current_book_chapters:
            logging.warning("⚠️ 智能随机模式缺少有效状态，回退到配置数据")
            try:
                fallback_ok = self._fallback_to_config()
            except AttributeError:
                logging.error("❌ 回退方法不存在，无法回退到配置数据")
                # 尝试使用纯随机回退
                try:
                    return self._pure_random_position()
                except Exception as e:
                    logging.error(f"❌ 无可用书籍: {e}")
                    raise RuntimeError("阅读管理器初始化失败：无可用书籍") from e

            if not fallback_ok:
                # 回退失败，尝试使用纯随机
                try:
                    return self._pure_random_position()
                except Exception as e:
                    logging.error(f"❌ 无可用书籍: {e}")
                    raise RuntimeError("阅读管理器初始化失败：无可用书籍") from e

        current_time = time.time()

        should_switch_book = (
            current_time - self.last_book_switch_time > self.config.smart_random.book_switch_cooldown
            and random.random() > self.config.smart_random.book_continuity
        )

        if should_switch_book and len(self.book_chapters_map) > 1:
            other_books = [bid for bid in self.book_chapters_map.keys() if bid != self.current_book_id]
            new_book_id = random.choice(other_books)
            self._switch_to_book(new_book_id)
            self.last_book_switch_time = current_time
            logging.info(f"📚 智能换书: 《{self.book_names_map.get(new_book_id, '未知')}》")

        should_skip_chapter = random.random() > self.config.smart_random.chapter_continuity

        if should_skip_chapter and len(self.current_book_chapters) > 1:
            self.current_chapter_index = random.randint(0, len(self.current_book_chapters) - 1)
            self.current_chapter_id = self.current_book_chapters[self.current_chapter_index]
            self.current_chapter_ci = self.get_chapter_index(self.current_chapter_id)
            logging.info(f"📄 智能跳章节: {self.current_chapter_id}, 索引 {self.current_chapter_ci}")
        else:
            self._next_chapter()

        return self.current_book_id, self.current_chapter_id

    def _switch_to_book(self, book_id: str):
        if book_id in self.book_chapters_map:
            self.current_book_id = book_id
            self.current_book_name = self.book_names_map.get(book_id, "未知书籍")
            self.current_book_chapters = self.book_chapters_map[book_id]
            self.current_chapter_index = 0
            self.current_chapter_id = self.current_book_chapters[0]
            self.current_chapter_ci = self.get_chapter_index(self.current_chapter_id)

    def _sequential_position(self):
        self._next_chapter()
        return self.current_book_id, self.current_chapter_id

    def _pure_random_position(self):
        if not self.book_chapters_map:
            raise RuntimeError("没有配置任何书籍，无法进行纯随机选择")

        bid = random.choice(list(self.book_chapters_map.keys()))
        cid = random.choice(self.book_chapters_map[bid])
        self.current_book_id = bid
        self.current_chapter_id = cid
        self.current_book_chapters = self.book_chapters_map[bid]
        return bid, cid

    def _next_chapter(self):
        if not self.current_book_chapters:
            return
        self.current_chapter_index += 1
        if self.current_chapter_index >= len(self.current_book_chapters):
            book_ids = list(self.book_chapters_map.keys())
            if self.current_book_id in book_ids:
                current_book_index = book_ids.index(self.current_book_id)
                next_book_index = (current_book_index + 1) % len(book_ids)
                next_book_id = book_ids[next_book_index]
                self._switch_to_book(next_book_id)
            else:
                # 回退至第一本书
                first_book = list(self.book_chapters_map.keys())[0]
                self._switch_to_book(first_book)
        else:
            self.current_chapter_id = self.current_book_chapters[self.current_chapter_index]
            self.current_chapter_ci = self.get_chapter_index(self.current_chapter_id)

    def _fallback_to_config(self) -> bool:
        """回退到配置数据（如果可用）"""
        if self.config.fallback_to_config and self.book_chapters_map:
            first_book = list(self.book_chapters_map.keys())[0]
            first_book_name = self.book_names_map.get(first_book, "未知书籍")
            self._switch_to_book(first_book)
            logging.info(f"✅ 回退到配置数据: 书籍《{first_book_name}》")
            return True

        logging.error("❌ 无法初始化阅读数据：既没有有效的CURL数据，也没有配置数据")
        return False

    def ensure_initialized(self) -> bool:
        """确保阅读管理器已初始化（有可读的书籍/章节），否则尝试回退到配置"""
        if self.current_book_id and self.current_book_chapters:
            return True
        return self._fallback_to_config()
