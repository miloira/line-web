import re
import time
import json
import random
import typing

import pyee
import requests

from line.logger import logger
from line.exceptions import LoginFailureException, BotNotExistsException, BotNotFoundException, InvalidTokenException
from line.authentications import CookieAuthentication, BusinessAuthentication, BrowserAuthentication


CHAT_FOLDER = typing.Literal["ALL", "INBOX", "UNREAD", "FOLLOW_UP", "DONE", "ASSIGNED", "SPAM"]
CONTACT_FIELDS = typing.Literal["DISPLAY_NAME", "FRIEND_TYPE", "LAST_TALKED_AT"]
BUSINESS_HOURS_CHAT_MODE = typing.Literal["MANUAL", "AUTO_RESPONSE", "SMART_RESPONSE", "AUTO_AND_SMART_RESPONSE"]
OUTSIDE_BUSINESS_HOURS_CHAT_MODE = typing.Literal["AUTO_RESPONSE", "SMART_RESPONSE", "AUTO_AND_SMART_RESPONSE"]
ORDER_BY = typing.Literal["ASC", "DESC"]


def manual_chat_mode(f: typing.Callable) -> typing.Callable[["Line", typing.Any], dict]:
    def wrapper(self: "Line", *args: typing.Any, **kwargs: typing.Any) -> dict:
        if "contact_id" not in kwargs:
            raise ValueError("Missing required argument: contact_id")

        self.set_use_manual_chat(kwargs["contact_id"])
        return f(self, *args, **kwargs)

    return wrapper


class Line:

    def __init__(
        self,
        authentication: typing.Union[CookieAuthentication, BusinessAuthentication, BrowserAuthentication],
        bot: str,
        client_type: typing.Optional[str] = "PC",
        device_type: typing.Optional[str] = "",
        ping_secs: typing.Optional[int] = 60,
        streaming_token_retries: typing.Optional[int] = 0.5,
        __x_oa_chat_client_version: typing.Optional[str] = "20230404142351"
    ):
        self.CHAT_HOST = "https://chat.line.biz"
        self.MANAGER_HOST = "https://manager.line.biz"
        self.__x_oa_chat_client_version = __x_oa_chat_client_version
        self.client_type = client_type
        self.device_type = device_type
        self.ping_secs = ping_secs
        self.streaming_token_retries = streaming_token_retries

        try:
            self.session = self._make_session(authentication.login())
        except KeyError:
            raise LoginFailureException(str(authentication))

        self.account = self.me()
        self.bot = self.select_bot(bot)
        self.bot_id = self.bot["botId"]
        self.basic_search_id = self.bot["basicSearchId"]
        self.enable_chat()

        self.event_funcs = {"event": []}
        self.event_emitter = pyee.executor.ExecutorEventEmitter()

    def select_bot(self, name: str) -> dict:
        bots = self.bots()
        try:
            if not bots["list"]:
                raise BotNotExistsException(bots["list"])

            for bot in bots["list"]:
                if bot["name"] == name:
                    return bot
        except KeyError:
            pass

        raise BotNotFoundException(bots)

    @classmethod
    def extract_emojis(cls, raw_text: str) -> typing.Union[list, None]:
        pattern = "\[EM:([\w\d]+),id=([\w\d]+)\]"
        emojis = []
        gap = 0
        for match in re.finditer(pattern, raw_text):
            product_id = match.group(1)
            emoji_id = match.group(2)
            start = match.start()
            end = match.end()
            index = start - gap
            gap += end - start - 1
            emojis.append({
                "productId": product_id,
                "emojiId": emoji_id,
                "length": 1,
                "index": index
            })
        return emojis or None

    def _make_session(self, data: dict) -> requests.Session:
        headers = {
            "x-oa-chat-client-version": self.__x_oa_chat_client_version,
            "x-xsrf-token": data["xsrf_token"],
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        }
        cookies = {
            "XSRF-TOKEN": data["xsrf_token"],
            "ses": data["ses"]
        }
        session = requests.Session()
        session.headers.update(headers)
        session.cookies.update(cookies)
        return session

    def csrf_token(self) -> dict:
        """获取X-XSRF-TOKEN"""
        url = self.CHAT_HOST + "/api/v1/csrfToken"
        response = self.session.get(url)
        return response.json()

    def streaming_api_token(self) -> dict:
        """获取streamingApiToken"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/streamingApiToken"
        response = self.session.post(url)
        return response.json()

    def cms_users(self, page: typing.Optional[int] = 1) -> dict:
        """权限管理-用户列表"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/cmsUsers"
        params = {
            "page": page
        }
        response = self.session.get(url, params=params)
        return response.json()

    def groups(self, page: typing.Optional[int] = 1, size: typing.Optional[int] = 10) -> dict:
        """权限管理-群组列表"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/groups"
        params = {
            "page": page,
            "size": size
        }
        response = self.session.get(url, params=params)
        return response.json()

    def restrict_chat_menu(self) -> dict:
        """账号设置-限制聊天媒体文件"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/restrictChatMenu"
        response = self.session.get(url)
        return response.json()

    def cms_user_role(self) -> dict:
        """账号设置-cms用户角色"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/cmsUserRole"
        response = self.session.get(url)
        return response.json()

    def profile_status(self) -> dict:
        """账号设置-资料状态"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/profileStatus"
        response = self.session.get(url)
        return response.json()

    def timeline_profiles_cover_image(self) -> dict:
        """账号设置-基本资料图片"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/timeline/profiles/coverImage"
        response = self.session.get(url)
        return response.json()

    def group_talk(self) -> dict:
        """账号设置-群聊状态"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/groupTalk"
        response = self.session.get(url)
        return response.json()

    def spot(self) -> dict:
        """账号设置-地址信息"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/spot"
        response = self.session.get(url)
        return response.json()

    def statusbar_setting(self) -> dict:
        """账号设置-状态消息"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/statusbar/setting"
        response = self.session.get(url)
        return response.json()

    def legal_country(self) -> dict:
        """账号设置-国家编码"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/legalCountry"
        response = self.session.get(url)
        return response.json()

    def legal_countries(self) -> dict:
        """账号设置-国家编码列表"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/legalCountries"
        response = self.session.get(url)
        return response.json()

    def verification_status(self) -> dict:
        """账号设置-认证状态"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/verification/status"
        response = self.session.get(url)
        return response.json()

    def purposes_v2x(self) -> dict:
        """账号设置-v2x"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/purposes/v2x"
        response = self.session.get(url)
        return response.json()

    def spot_migration_modal(self) -> dict:
        """账号设置-v2x"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/spot/migration/modal"
        response = self.session.get(url)
        return response.json()

    def spot_migration_status(self) -> dict:
        """账号设置-地址变更状态"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/spot/migration/status"
        response = self.session.get(url)
        return response.json()

    def profile_spot(self) -> dict:
        """账号设置-资料地址"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/profile/spot"
        response = self.session.get(url)
        return response.json()

    def unread_chat_count(self) -> dict:
        """未读聊天消息"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/unreadChatCount"
        response = self.session.get(url)
        return response.json()

    def notifications(self) -> dict:
        """通知列表"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/notifications/v2/list?count=1"
        response = self.session.get(url)
        return response.json()

    def enable_chat(self, enabled: typing.Optional[bool] = True) -> dict:
        """回复设置-启用聊天"""
        url = self.MANAGER_HOST + f"/api/v1/bots/{self.basic_search_id}/responseSettings/enabledChat"
        data = {
            "enabled": enabled
        }
        response = self.session.post(url, json=data)
        return response.json()

    def enable_welcome_message(self, enabled: typing.Optional[bool] = True) -> dict:
        """回复设置-启用加入好友的欢迎信息"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/responseSettings/enabledWelcomeMessage"
        data = {
            "enabled": enabled
        }
        response = self.session.post(url, json=data)
        return response.json()

    def enable_webhook(self, enabled: typing.Optional[bool] = True) -> dict:
        """回复设置-启用webhook"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/responseSettings/enabledWebhook"
        data = {
            "enabled": enabled
        }
        response = self.session.post(url, json=data)
        return response.json()

    def enable_business_hours(self, enabled: typing.Optional[bool] = True) -> dict:
        """回复设置-回复时间"""
        url = self.MANAGER_HOST + f"/api/v2/bots/{self.basic_search_id}/chatModeSettings/enabledBusinessHours"
        data = {
            "enabled": enabled
        }
        response = self.session.put(url, json=data)
        return response.json()

    def chat_mode_in_business_hours(self, chat_mode: BUSINESS_HOURS_CHAT_MODE) -> dict:
        """回复设置-回复时间-聊天模式"""
        url = self.MANAGER_HOST + f"/api/v2/bots/{self.basic_search_id}/chatModeSettings/chatModeInBusinessHours"
        data = {
            "chatMode": chat_mode
        }
        response = self.session.put(url, json=data)
        return response.json()

    def chat_mode_outside_in_business_hours(self, chat_mode: OUTSIDE_BUSINESS_HOURS_CHAT_MODE) -> dict:
        """回复设置-回复时间-聊天模式"""
        url = self.MANAGER_HOST + f"/api/v2/bots/{self.basic_search_id}/chatModeSettings/chatModeOutsideBusinessHours"
        data = {
            "chatMode": chat_mode
        }
        response = self.session.put(url, json=data)
        return response.json()

    def primary_channel(self):
        """消息API"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/primaryChannel"
        response = self.session.get(url)
        return response.json()

    def applicant(self):
        """登录信息"""
        url = self.MANAGER_HOST + f"/api/bots/{self.basic_search_id}/applicant"
        response = self.session.get(url)
        return response.json()

    def state(self, connection_id: int, idle: bool) -> dict:
        """修改连接状态"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/streaming/state"
        data = {
            "connectionId": connection_id,
            "idle": idle
        }
        response = self.session.put(url, json=data)
        return response.json()

    def me(self) -> dict:
        """账号信息"""
        url = self.CHAT_HOST + "/api/v1/me"
        response = self.session.get(url)
        return response.json()

    def settings_call(self) -> dict:
        """呼叫设置信息"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/settings/call"
        response = self.session.get(url)
        return response.json()

    def settings_reservation(self) -> dict:
        """预约设置信息"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/settings/reservation"
        response = self.session.get(url)
        return response.json()

    def chat_mode(self) -> dict:
        """聊天模式"""
        url = self.CHAT_HOST + f"/api/v3/bots/{self.bot_id}/settings/chatMode"
        response = self.session.get(url)
        return response.json()

    def chat_mode_scheduler(self) -> dict:
        """聊天模式日程"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/settings/chatModeSchedules"
        response = self.session.get(url)
        return response.json()

    def settings_pc(self) -> dict:
        """PC端设置信息"""
        url = self.CHAT_HOST + f"/api/v1/me/settings/pc"
        response = self.session.get(url)
        return response.json()

    def available_features(self) -> dict:
        """可用特性"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/availableFeatures"
        response = self.session.get(url)
        return response.json()

    def banner_web(self) -> dict:
        """web端广告"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/banner/web"
        response = self.session.get(url)
        return response.json()

    def owners(self) -> dict:
        """机器人拥有者"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/owners"
        response = self.session.get(url)
        return response.json()

    def search_limitation_stats(self) -> dict:
        """搜索限制统计"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/searchLimitationStats"
        response = self.session.get(url)
        return response.json()

    def whitelist_domains(self) -> dict:
        """白名单域名"""
        url = self.CHAT_HOST + "/api/v1/whitelistDomains"
        response = self.session.get(url)
        return response.json()

    def tags(self) -> dict:
        """标签列表"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/tags"
        response = self.session.get(url)
        return response.json()

    def add_tag(self, name: str) -> dict:
        """添加标签"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/tags"
        data = {
            "name": name
        }
        response = self.session.post(url, json=data)
        return response.json()

    def get_tag(self, tag_id: str) -> dict:
        """标签详情"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/tags/{tag_id}"
        response = self.session.get(url)
        return response.json()

    def auto_tags(self) -> dict:
        """自动标签列表"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/autoTags"
        response = self.session.get(url)
        return response.json()

    def now(self) -> dict:
        """服务器时间"""
        url = self.CHAT_HOST + "/api/v1/clock/now"
        response = self.session.get(url)
        return response.json()

    def bots(self, no_filter: typing.Optional[bool] = True, limit: typing.Optional[int] = 1000) -> dict:
        """机器人列表"""
        url = self.CHAT_HOST + "/api/v1/bots"
        params = {
            "noFilter": no_filter,
            "limit": limit
        }
        response = self.session.get(url, params=params)
        return response.json()

    def contacts(
        self,
        query: typing.Optional[str] = "",
        _next: typing.Optional[str] = "",
        sort_key: typing.Optional[CONTACT_FIELDS] = "DISPLAY_NAME",
        sort_order: typing.Optional[ORDER_BY] = "ASC",
        exclude_spam: typing.Optional[bool] = True,
        limit: typing.Optional[int] = 20
    ) -> dict:
        """查询联系人"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/contacts"
        params = {
            "query": query,
            "sortKey": sort_key,
            "sortOrder": sort_order,
            "excludeSpam": exclude_spam,
            "next": _next,
            "limit": limit
        }
        response = self.session.get(url, params=params)
        return response.json()

    def messages(self, contact_id: str, backward: typing.Optional[str] = "") -> dict:
        """查询聊天记录"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/messages/{contact_id}"
        params = {
            "backward": backward
        }
        response = self.session.get(url, params=params)
        return response.json()

    def chats(
        self,
        folder_type: typing.Optional[CHAT_FOLDER] = "ALL",
        tag_ids: typing.Optional[str] = "",
        auto_tag_ids: typing.Optional[str] = "",
        limit: typing.Optional[int] = 25,
        _next: typing.Optional[str] = "",
        prioritize_pinned_chat: typing.Optional[bool] = True
    ) -> bool:
        """查询会话列表"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/chats"
        params = {
            "folderType": folder_type,
            "tagIds": tag_ids,
            "autoTagIds": auto_tag_ids,
            "limit": limit,
            "next": _next,
            "prioritizePinnedChat": prioritize_pinned_chat
        }
        response = self.session.get(url, params=params)
        return response.json()

    def delete_chat(self, contact_id: str) -> dict:
        """删除会话"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}"
        response = self.session.delete(url)
        return response.json()

    def add_mute_chat(self, contact_id: str) -> dict:
        """禁用会话声音"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/mute/pc"
        response = self.session.put(url)
        return response.json()

    def delete_mute_chat(self, contact_id: str) -> dict:
        """禁用会话声音"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/mute/pc"
        response = self.session.delete(url)
        return response.json()

    def set_use_manual_chat(self, contact_id: str) -> dict:
        """设置手动聊天模式"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/chats/{contact_id}/useManualChat"
        data = {
            "expiresAt": int(time.time() * 1000) + 3600
        }
        response = self.session.put(url, json=data)
        return response.json()

    def get_use_manual_chat(self, contact_id: str) -> dict:
        """查询手动聊天模式"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/chats/{contact_id}/useManualChat"
        response = self.session.get(url)
        return response.json()

    def delete_use_manual_chat(self, contact_id: str) -> dict:
        """取消手动聊天模式"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/chats/{contact_id}/useManualChat"
        response = self.session.delete(url)
        return response.json()

    def add_user_tag(self, contact_id: str, tag_id: str) -> dict:
        """设置用户标签"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/tags/{tag_id}"
        response = self.session.put(url)
        return response.json()

    def delete_user_tag(self, contact_id: str, tag_id: str) -> dict:
        """删除用户标签"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/tags/{tag_id}"
        response = self.session.delete(url)
        return response.json()

    def mark_as_read(self, contact_id: str, message_id: str) -> dict:
        """标记消息为已读"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/markAsRead"
        data = {"messageId": message_id}
        response = self.session.put(url, json=data)
        return response.json()

    def add_follow_up(self, contact_id: str) -> dict:
        """关注用户"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/followUp"
        response = self.session.put(url)
        return response.json()

    def delete_follow_up(self, contact_id: str) -> dict:
        """取消关注用户"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/followUp"
        response = self.session.delete(url)
        return response.json()

    def resolve(self, contact_id: str) -> dict:
        """标记为已处理"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/done"
        response = self.session.put(url)
        return response.json()

    def remark(self, contact_id: str, nickname: str) -> dict:
        """设置备注"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/nickname"
        data = {
            "nickname": nickname
        }
        response = self.session.put(url, json=data)
        return response.json()

    def pin(self, contact_id: str) -> dict:
        """会话置顶"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/pin"
        response = self.session.put(url)
        return response.json()

    def unpin(self, contact_id: str) -> dict:
        """取消会话置顶"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/pin"
        response = self.session.delete(url)
        return response.json()

    def content_preview(self, content_hash: str) -> bytes:
        """获取聊天图片"""
        url = f"https://chat-content.line.biz/bot/{self.bot_id}/{content_hash}"
        response = self.session.get(url)
        return response.content

    def profile_preview(self, content_hash: str) -> bytes:
        """获取联系资料图片"""
        url = f"https://profile.line-scdn.net/{content_hash}"
        response = self.session.get(url)
        return response.content

    def stickers(self, next_token: typing.Optional[str] = "") -> dict:
        """贴纸列表"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/stickers/owned"
        params = {
            "nextToken": next_token
        }
        response = self.session.get(url, params=params)
        return response.json()

    def card_type_messages(self, limit: typing.Optional[int] = 25) -> dict:
        """卡片消息列表"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/cardTypeMessages"
        params = {
            "limit": limit
        }
        response = self.session.get(url, params=params)
        return response.json()

    def coupons(self, page: typing.Optional[int] = 1, page_size: typing.Optional[int] = 25) -> dict:
        """优惠券列表"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/coupons"
        params = {
            "page": page,
            "pageSize": page_size
        }
        response = self.session.get(url, params=params)
        return response.json()

    def save_replies(
        self,
        query: typing.Optional[str] = "",
        sort_key: typing.Optional[str] = "CREATED_AT",
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 25,
        exclude_username_placeholder: typing.Optional[bool] = False
    ) -> dict:
        """标准回复列表"""
        url = self.CHAT_HOST + f"/api/v2/bots/{self.bot_id}/savedReplies"
        params = {
            "query": query,
            "sortKey": sort_key,
            "pageSize": page_size,
            "page": page,
            "excludeUsernamePlaceholder": exclude_username_placeholder
        }
        response = self.session.get(url, params=params)
        return response.json()

    def set_typing(self, contact_id: str) -> dict:
        """设置输入状态"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/chats/{contact_id}/typing"
        response = self.session.put(url)
        return response.json()

    @classmethod
    def make_send_id(cls, contact_id: str) -> str:
        return "_".join([contact_id, str(int(time.time() * 1000)), str(int(random.random() * 1e8))])

    def upload_file(self, contact_id: str, file: typing.Union[bytes, typing.IO]) -> dict:
        """上传待发送文件"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/messages/{contact_id}/uploadFile"
        files = {
            "file": file
        }
        response = self.session.post(url, files=files)
        return response.json()

    def bulk_send_files(self, contact_id: str, data: dict) -> dict:
        """批量发送文件"""
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/messages/{contact_id}/bulkSendFiles"
        response = self.session.post(url, json=data)
        return response.json()

    def send(self, **kwargs: typing.Any) -> dict:
        """发送消息"""
        if "emojis" in kwargs:
            emojis = kwargs.get("emojis")
            if emojis is not None:
                if not isinstance(emojis, list):
                    raise TypeError("emojis must be a list.")

                if not len(emojis) > 0:
                    raise ValueError("emojis length can't be 0.")

                kwargs["text"] = re.sub("\[EM:([\w\d]+),id=([\w\d]+)\]", "$", kwargs["text"])
            else:
                kwargs.pop("emojis")

        if "quoteToken" in kwargs:
            quote_token = kwargs.get("quoteToken")
            if quote_token is not None:
                if not isinstance(quote_token, str):
                    raise TypeError("quoteToken must be a str.")
            else:
                kwargs.pop("quoteToken")

        contact_id = kwargs.pop("contact_id")
        url = self.CHAT_HOST + f"/api/v1/bots/{self.bot_id}/messages/{contact_id}/send"
        send_id = self.make_send_id(contact_id)
        data = {
            "sendId": send_id,
            **kwargs
        }
        response = self.session.post(url, json=data)
        return {
            "send_id": send_id,
            **response.json(),
        }

    @manual_chat_mode
    def send_file_msg(self, contact_id: str, file: typing.Union[bytes, typing.IO]) -> dict:
        """发送文件"""
        send_id = self.make_send_id(contact_id)
        content_message_token = self.upload_file(contact_id, file)["contentMessageToken"]
        data = {"items": [{"contentMessageToken": content_message_token, "sendId": send_id}]}
        return {
            "send_id": send_id,
            **self.bulk_send_files(
                contact_id=contact_id,
                data=data
            )
        }

    @manual_chat_mode
    def send_text_msg(
        self,
        contact_id: str,
        text: str,
        escape: typing.Optional[bool] = False,
        quote_token: typing.Optional[bool] = None
    ) -> dict:
        """发送文本消息"""
        return self.send(**{
            "type": "text",
            "contact_id": contact_id,
            "text": text,
            "emojis": self.extract_emojis(text) if not escape else None,
            "quoteToken": quote_token
        })

    @manual_chat_mode
    def send_sticker_msg(
        self,
        contact_id: str,
        package_id: int,
        sticker_id: int,
        quote_token: typing.Optional[str] = None
    ) -> dict:
        """发送表情包消息"""
        return self.send(**{
            "type": "sticker",
            "contact_id": contact_id,
            "stickerId": sticker_id,
            "packageId": package_id,
            "quoteToken": quote_token
        })

    @manual_chat_mode
    def send_card_msg(self, contact_id: str, card_type_message_id: str) -> dict:
        """发送卡片消息"""
        return self.send(**{
            "type": "cardType",
            "contact_id": contact_id,
            "cardTypeMessageId": card_type_message_id
        })

    @manual_chat_mode
    def send_call_msg(self, contact_id: str) -> dict:
        """发送语音聊天邀请"""
        return self.send(**{
            "type": "callGuide",
            "contact_id": contact_id,
        })

    def sse(
        self,
        token: str,
        last_event_id: typing.Optional[str] = None,
        device_type: typing.Optional[str] = "",
        client_type: typing.Optional[str] = "PC",
        ping_secs: typing.Optional[int] = 60
    ) -> typing.Generator:
        """sse事件"""
        url = "https://chat-streaming-api.line.biz/api/v2/sse"
        params = {
            "token": token,
            "deviceType": device_type,
            "clientType": client_type,
            "pingSecs": ping_secs,
            "lastEventId": last_event_id
        }
        response = self.session.get(url, params=params, stream=True)
        for event_data in response.iter_lines(delimiter=b"\n\n"):
            if event_data != b"":
                yield event_data

    def handle(self, event: typing.Optional[str] = None, sub_event: typing.Optional[str] = None) -> typing.Callable:
        def wrapper(f: typing.Callable) -> None:
            if event is not None:
                if not isinstance(event, str):
                    raise TypeError("event must be a str.")

            if sub_event is not None:
                if not isinstance(sub_event, str):
                    raise TypeError("sub_event must be a str.")

            event_name = None
            if event is not None and sub_event is not None:
                event_name = f"{event}-{sub_event}"
            elif event is not None and sub_event is None:
                event_name = event
            elif event is None and sub_event is not None:
                raise ValueError("sub_event need a event.")
            else:
                self.event_emitter.on("event", f)

            if event_name is not None:
                self.event_emitter.on(event_name, f)

        return wrapper

    def run(self) -> typing.NoReturn:
        logger.info(f"Account: %s" % self.account["name"])
        logger.info(f"Bot: %s" % self.bot["name"])
        logger.info(f"Message listening...")
        while True:
            try:
                streaming_api_token = self.streaming_api_token()
                logger.debug(streaming_api_token)

                for event_data in self.sse(
                    token=streaming_api_token["streamingApiToken"],
                    last_event_id=streaming_api_token.get("lastEventId"),
                    device_type=self.device_type,
                    client_type=self.client_type,
                    ping_secs=self.ping_secs
                ):
                    event_data = event_data.decode()
                    event_data_part = event_data.split("\n")
                    _id = event_data_part[0].replace("id:", "")
                    event_name = event_data_part[1].replace("event:", "")
                    data = event_data_part[2].replace("data:", "")

                    if data == "ping":
                        data = "{}"

                    event = {
                        "id": _id,
                        "event": event_name,
                        "data": json.loads(data)
                    }
                    logger.debug(event)

                    self.event_emitter.emit("event", self, event)
                    self.event_emitter.emit(event_name, self, event)
                    if event["event"] and "subEvent" in event["data"]:
                        event_name = "%s-%s" % (event["event"], event["data"]["subEvent"])
                        self.event_emitter.emit(event_name, self, event)

                    if event["event"] == "fail":
                        if event["data"]["subEvent"] == "invalid_token":
                            raise InvalidTokenException

            except InvalidTokenException as e:
                logger.error(e)

            except Exception as e:
                logger.error(e)

            time.sleep(self.streaming_token_retries)
