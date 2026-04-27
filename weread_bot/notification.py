import requests
import urllib.parse
import asyncio
import json
import logging
from typing import Dict, Any
from .config import NotificationChannel


class NotificationService:
    """通知服务 - 支持多种通知渠道"""
    
    def __init__(self, config):
        self.config = config

    async def send_notification_async(self, message: str) -> bool:
        """异步发送通知（在线程池中执行）"""
        return await asyncio.to_thread(self.send_notification, message)

    def send_notification(self, message: str) -> bool:
        """同步发送通知"""
        if not self.config.enabled:
            return True

        success_count = 0
        total_channels = len([c for c in self.config.channels if c.enabled])
        if total_channels == 0:
            logging.warning("⚠️ 没有启用的通知通道")
            return True

        for channel in self.config.channels:
            if channel.enabled:
                try:
                    ok = self._send_notification_to_channel(message, channel)
                    if ok:
                        success_count += 1
                        print(f"✅ 通道 {channel.name} 通知发送成功")
                    else:
                        logging.warning(f"⚠️ 通道 {channel.name} 通知发送失败")
                except Exception as e:
                    logging.error(f"❌ 通道 {channel.name} 通知发送异常: {e}")

        print(f"📊 通知发送完成: {success_count}/{total_channels} 个通道成功")
        return success_count > 0

    def _send_notification_to_channel(self, message: str, channel: NotificationChannel) -> bool:
        """发送通知到特定通道"""
        name = channel.name
        cfg = channel.config or {}
        
        if name == "pushplus":
            return self._send_pushplus(message, cfg)
        elif name == "telegram":
            return self._send_telegram(message, cfg)
        elif name == "wxpusher":
            return self._send_wxpusher(message, cfg)
        elif name == "bark":
            return self._send_bark(message, cfg)
        elif name == "ntfy":
            return self._send_ntfy(message, cfg)
        elif name == "feishu":
            return self._send_feishu(message, cfg)
        elif name == "wework":
            return self._send_wework(message, cfg)
        elif name == "dingtalk":
            return self._send_dingtalk(message, cfg)
        else:
            logging.warning(f"⚠️ 未知的通知通道: {name}")
            return False

    def _send_pushplus(self, message: str, config: dict) -> bool:
        """发送PushPlus通知"""
        token = config.get("token")
        if not token:
            logging.error("❌ PushPlus token未配置")
            return False

        url = "https://www.pushplus.plus/send"
        data = {"token": token, "title": "微信读书自动阅读报告", "content": message}
        return self._http_post(url, data)

    def _send_telegram(self, message: str, config: dict) -> bool:
        """发送Telegram通知"""
        bot_token = config.get("bot_token")
        chat_id = config.get("chat_id")
        if not bot_token or not chat_id:
            logging.error("❌ Telegram配置不完整")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": message}
        proxies = config.get("proxy", {})
        return self._http_post(url, data, proxies=proxies, use_json=True, timeout=30)

    def _send_wxpusher(self, message: str, config: dict) -> bool:
        """发送WxPusher通知"""
        spt = config.get("spt")
        if not spt:
            logging.error("❌ WxPusher SPT未配置")
            return False

        url = f"https://wxpusher.zjiecode.com/api/send/message/{spt}/{urllib.parse.quote(message)}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logging.error(f"❌ WxPusher通知发送失败: {e}")
            return False

    def _send_bark(self, message: str, config: dict) -> bool:
        """发送Bark通知"""
        server = config.get("server")
        device_key = config.get("device_key")
        if not server or not device_key:
            logging.error("❌ Bark配置不完整")
            return False

        url = f"{server.rstrip('/')}/{device_key}"
        data = {"title": "微信读书自动阅读报告", "body": message}
        if config.get("sound"):
            data["sound"] = config["sound"]
        return self._http_post(url, data)

    def _send_ntfy(self, message: str, config: dict) -> bool:
        """发送Ntfy通知"""
        server = config.get("server")
        topic = config.get("topic")
        if not server or not topic:
            logging.error("❌ Ntfy配置不完整")
            return False

        url = f"{server.rstrip('/')}/{topic}"
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": "微信读书自动阅读报告",
        }
        if config.get("token"):
            headers["Authorization"] = f"Bearer {config['token']}"

        try:
            response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logging.error(f"❌ Ntfy通知发送失败: {e}")
            return False

    def _send_feishu(self, message: str, config: dict) -> bool:
        """发送飞书通知"""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            logging.error("❌ 飞书Webhook URL未配置")
            return False

        msg_type = config.get("msg_type", "text")
        if msg_type == "rich_text":
            data = {
                "msg_type": "post",
                "content": {
                    "post": {
                        "zh_cn": {
                            "title": "微信读书自动阅读报告",
                            "content": [[{"tag": "text", "text": message}]],
                        }
                    }
                },
            }
        else:
            data = {"msg_type": "text", "content": {"text": f"微信读书自动阅读报告\n\n{message}"}}

        return self._http_post(webhook_url, data)

    def _send_wework(self, message: str, config: dict) -> bool:
        """发送企业微信通知"""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            logging.error("❌ 企业微信Webhook URL未配置")
            return False

        msg_type = config.get("msg_type", "text")
        if msg_type == "markdown":
            data = {"msgtype": "markdown", "markdown": {"content": f"## 微信读书自动阅读报告\n\n{message}"}}
        else:
            data = {"msgtype": "text", "text": {"content": f"微信读书自动阅读报告\n\n{message}"}}

        return self._http_post(webhook_url, data)

    def _send_dingtalk(self, message: str, config: dict) -> bool:
        """发送钉钉通知"""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            logging.error("❌ 钉钉Webhook URL未配置")
            return False

        msg_type = config.get("msg_type", "text")
        if msg_type == "markdown":
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "微信读书自动阅读报告",
                    "text": f"## 微信读书自动阅读报告\n\n{message}",
                },
            }
        else:
            data = {"msgtype": "text", "text": {"content": f"微信读书自动阅读报告\n\n{message}"}}

        return self._http_post(webhook_url, data)

    def _http_post(
        self,
        url: str,
        data: Dict[str, Any],
        proxies: dict = None,
        use_json: bool = False,
        timeout: int = 10,
        max_retries: int = 3,
    ) -> bool:
        """通用HTTP POST请求"""
        for attempt in range(max_retries):
            try:
                if use_json:
                    response = requests.post(url, json=data, proxies=proxies, timeout=timeout)
                else:
                    headers = {"Content-Type": "application/json"}
                    response = requests.post(
                        url, data=json.dumps(data).encode("utf-8"), headers=headers, timeout=timeout
                    )
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    logging.debug(f"重试 {attempt + 1}/{max_retries}: {e}")
                    continue
                else:
                    logging.error(f"❌ HTTP POST失败: {e}")
                    return False
        return False
