from __future__ import annotations

from datetime import datetime, date
import zoneinfo

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.all import AstrBotConfig
from astrbot.core.platform.message_type import MessageType
try:
    import chinese_calendar as calendar_cn
    CHINESE_CALENDAR_AVAILABLE = True
except ImportError:
    CHINESE_CALENDAR_AVAILABLE = False
    logger.warning("chinese-calendar 库未安装，节假日识别功能将受限")

try:
    from lunarcalendar import Converter, Solar
    LUNAR_CALENDAR_AVAILABLE = True
except ImportError:
    LUNAR_CALENDAR_AVAILABLE = False
    logger.warning("lunarcalendar 库未安装，农历/节气/黄历功能将不可用")


# 农历月份和日期的中文表示
LUNAR_MONTHS = ["正月", "二月", "三月", "四月", "五月", "六月",
                "七月", "八月", "九月", "十月", "冬月", "腊月"]
LUNAR_DAYS = ["初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
              "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
              "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十"]

# 二十四节气
SOLAR_TERMS = [
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分",
    "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
    "小暑", "大暑", "立秋", "处暑", "白露", "秋分",
    "寒露", "霜降", "立冬", "小雪", "大雪", "冬至"
]

# 天干地支
TIAN_GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DI_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
SHENG_XIAO = ["鼠", "牛", "虎", "兔", "龙", "蛇", "马", "羊", "猴", "鸡", "狗", "猪"]

# 黄历宜忌（简化版，基于日期的简单算法）
YI_ITEMS = ["祭祀", "祈福", "求嗣", "开光", "出行", "解除", "动土", "起基",
            "开市", "交易", "立券", "挂匾", "安床", "入宅", "移徙", "栽种",
            "纳畜", "入殓", "安葬", "启钻", "除服", "成服", "修造", "竖柱"]
JI_ITEMS = ["嫁娶", "开市", "安葬", "动土", "破土", "作灶", "安床", "入宅",
            "移徙", "出行", "祭祀", "祈福", "开光", "纳采", "订盟", "造庙"]


# 常量定义
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

PLATFORM_DISPLAY_NAMES = {
    "aiocqhttp": "QQ",
    "telegram": "Telegram",
    "discord": "Discord",
    "weixin_official_account": "微信公众号",
    "wecom": "企业微信",
    "wecom_ai_bot": "企业微信AI机器人",
    "satori": "Satori",
    "misskey": "Misskey",
}


@register("add_time", "miaomiao", "让每次请求都携带这次请求的时间", "1.1.0")
class MyPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)

        # 从配置文件读取设置
        timezone_name = config.get("timezone", "Asia/Shanghai")
        self.enable_holiday = config.get("enable_holiday_perception", True)
        self.enable_platform = config.get("enable_platform_perception", True)
        self.enable_lunar = config.get("enable_lunar_perception", True)
        self.enable_solar_term = config.get("enable_solar_term_perception", True)
        self.enable_almanac = config.get("enable_almanac_perception", False)
        self.holiday_country = config.get("holiday_country", "CN")

        # 初始化时区
        try:
            self.timezone = zoneinfo.ZoneInfo(timezone_name)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError) as e:
            logger.error(f"无效的时区设置 '{timezone_name}': {e}，使用默认时区 Asia/Shanghai")
            self.timezone = zoneinfo.ZoneInfo("Asia/Shanghai")
            timezone_name = "Asia/Shanghai"

        # 记录插件加载信息
        calendar_status = "已启用" if CHINESE_CALENDAR_AVAILABLE else "受限(未安装chinese-calendar)"
        lunar_status = "已启用" if LUNAR_CALENDAR_AVAILABLE else "不可用(未安装lunarcalendar)"
        logger.info(
            f"LLMPerception 插件已加载 | 时区: {timezone_name} | "
            f"节假日感知: {self.enable_holiday}({calendar_status}) | "
            f"平台感知: {self.enable_platform} | "
            f"农历感知: {self.enable_lunar}({lunar_status}) | "
            f"节气感知: {self.enable_solar_term} | "
            f"黄历感知: {self.enable_almanac}"
        )

    def _get_holiday_info(self, current_time: datetime) -> str:
        """获取节假日信息"""
        if not self.enable_holiday:
            return ""

        info_parts = []

        # 判断是否为周末
        weekday = current_time.weekday()
        info_parts.append(WEEKDAY_NAMES[weekday])

        # 使用 chinese-calendar 库进行节假日判断（仅支持中国）
        if self.holiday_country == "CN" and CHINESE_CALENDAR_AVAILABLE:
            current_date = date(current_time.year, current_time.month, current_time.day)

            # 判断是否为法定节假日
            is_holiday = calendar_cn.is_holiday(current_date)
            # 判断是否为工作日（考虑调休）
            is_workday = calendar_cn.is_workday(current_date)

            if is_holiday:
                # 获取节日名称
                # get_holiday_detail 返回 (is_on_holiday, holiday_name) 元组
                holiday_detail = calendar_cn.get_holiday_detail(current_date)
                holiday_name = holiday_detail[1] if holiday_detail and holiday_detail[1] else "法定节假日"

                # 区分周末和工作日的法定节假日
                if weekday >= 5:
                    info_parts.append(f"周末({holiday_name})")
                else:
                    info_parts.append(f"法定节假日({holiday_name})")
            elif is_workday:
                if weekday >= 5:
                    info_parts.append("调休工作日")
                else:
                    info_parts.append("工作日")
            else:
                info_parts.append("周末")
        else:
            # 降级方案：简单判断周末
            if weekday >= 5:
                info_parts.append("周末")
            else:
                info_parts.append("工作日")

        # 判断时间段
        hour = current_time.hour
        if 5 <= hour < 12:
            time_period = "上午"
        elif 12 <= hour < 14:
            time_period = "中午"
        elif 14 <= hour < 18:
            time_period = "下午"
        elif 18 <= hour < 22:
            time_period = "晚上"
        else:
            time_period = "深夜"
        info_parts.append(time_period)

        safe_parts = [str(part) for part in info_parts if part]
        return ", ".join(safe_parts)

    def _get_lunar_info(self, current_time: datetime) -> str:
        """获取农历日期信息"""
        if not self.enable_lunar or not LUNAR_CALENDAR_AVAILABLE:
            return ""

        try:
            solar = Solar(current_time.year, current_time.month, current_time.day)
            lunar = Converter.Solar2Lunar(solar)

            # 获取农历月份和日期的中文表示
            month_str = LUNAR_MONTHS[lunar.month - 1]
            day_str = LUNAR_DAYS[lunar.day - 1]

            # 处理闰月
            if lunar.isleap:
                month_str = "闰" + month_str

            # 计算天干地支年份
            year_gan = TIAN_GAN[(lunar.year - 4) % 10]
            year_zhi = DI_ZHI[(lunar.year - 4) % 12]
            sheng_xiao = SHENG_XIAO[(lunar.year - 4) % 12]

            return f"农历{year_gan}{year_zhi}年({sheng_xiao}年){month_str}{day_str}"
        except Exception as e:
            logger.debug(f"获取农历信息失败: {e}")
            return ""

    def _get_solar_term_info(self, current_time: datetime) -> str:
        """获取节气信息"""
        if not self.enable_solar_term or not LUNAR_CALENDAR_AVAILABLE:
            return ""

        try:
            # 节气日期表（简化版，基于平均值）
            # 每个节气大约相隔15天，从小寒开始
            solar_term_dates = [
                (1, 6), (1, 20),   # 小寒、大寒
                (2, 4), (2, 19),   # 立春、雨水
                (3, 6), (3, 21),   # 惊蛰、春分
                (4, 5), (4, 20),   # 清明、谷雨
                (5, 6), (5, 21),   # 立夏、小满
                (6, 6), (6, 21),   # 芒种、夏至
                (7, 7), (7, 23),   # 小暑、大暑
                (8, 7), (8, 23),   # 立秋、处暑
                (9, 8), (9, 23),   # 白露、秋分
                (10, 8), (10, 23), # 寒露、霜降
                (11, 7), (11, 22), # 立冬、小雪
                (12, 7), (12, 22)  # 大雪、冬至
            ]

            current_month = current_time.month
            current_day = current_time.day

            # 查找当前日期对应的节气（前后3天内）
            for i, (month, day) in enumerate(solar_term_dates):
                if current_month == month and abs(current_day - day) <= 2:
                    if current_day == day:
                        return f"今日{SOLAR_TERMS[i]}"
                    elif current_day < day:
                        return f"临近{SOLAR_TERMS[i]}"
                    else:
                        return f"{SOLAR_TERMS[i]}已过"

            # 查找当前处于哪两个节气之间
            for i, (month, day) in enumerate(solar_term_dates):
                next_i = (i + 1) % 24
                next_month, next_day = solar_term_dates[next_i]

                # 判断当前日期是否在这两个节气之间
                current_ordinal = current_month * 100 + current_day
                this_ordinal = month * 100 + day
                next_ordinal = next_month * 100 + next_day

                # 处理跨年的情况
                if next_ordinal < this_ordinal:  # 跨年
                    if current_ordinal >= this_ordinal or current_ordinal < next_ordinal:
                        return f"当前节气: {SOLAR_TERMS[i]}"
                else:
                    if this_ordinal <= current_ordinal < next_ordinal:
                        return f"当前节气: {SOLAR_TERMS[i]}"

            return ""
        except Exception as e:
            logger.debug(f"获取节气信息失败: {e}")
            return ""

    def _get_almanac_info(self, current_time: datetime) -> str:
        """获取黄历宜忌信息（简化版，仅供娱乐）"""
        if not self.enable_almanac:
            return ""

        try:
            # 使用日期生成伪随机的宜忌（基于日期的简单哈希）
            day_hash = (current_time.year * 10000 + current_time.month * 100 + current_time.day)

            # 根据日期哈希选择宜忌项目
            yi_count = (day_hash % 4) + 2  # 2-5个宜
            ji_count = (day_hash % 3) + 2  # 2-4个忌

            # 使用日期作为种子选择具体项目
            yi_start = day_hash % len(YI_ITEMS)
            ji_start = (day_hash * 7) % len(JI_ITEMS)

            yi_list = []
            ji_list = []

            for i in range(yi_count):
                yi_list.append(YI_ITEMS[(yi_start + i * 3) % len(YI_ITEMS)])

            for i in range(ji_count):
                ji_list.append(JI_ITEMS[(ji_start + i * 5) % len(JI_ITEMS)])

            yi_str = "、".join(yi_list)
            ji_str = "、".join(ji_list)

            return f"宜: {yi_str} | 忌: {ji_str}"
        except Exception as e:
            logger.debug(f"获取黄历信息失败: {e}")
            return ""

    @staticmethod
    def _clean_group_name(name: str | None) -> str | None:
        if not name:
            return None
        candidate = str(name).strip()
        if not candidate:
            return None
        placeholders = {"N/A", "NONE", "NULL", "UNKNOWN"}
        if candidate.upper() in placeholders:
            return None
        return candidate

    async def _get_group_name(self, event: AstrMessageEvent) -> str | None:
        """优先从消息对象中读取群名称，否则调用协议端接口获取"""
        message_obj = getattr(event, "message_obj", None)
        group_obj = getattr(message_obj, "group", None) if message_obj else None
        if group_obj:
            group_name = self._clean_group_name(getattr(group_obj, "group_name", None))
            if group_name:
                return group_name

        get_group_fn = getattr(event, "get_group", None)
        if not callable(get_group_fn):
            return None

        group_id = ""
        if hasattr(event, "get_group_id"):
            group_id = event.get_group_id()
        elif message_obj:
            group_id = getattr(message_obj, "group_id", "")

        if not group_id:
            return None

        try:
            group_info = await get_group_fn(group_id=group_id)
        except Exception as exc:
            logger.debug(f"LLMPerception: 获取群聊信息失败: {exc}")
            return None

        if group_info:
            group_name = self._clean_group_name(getattr(group_info, "group_name", None))
            if group_name:
                return group_name
        return None

    async def _get_platform_info(self, event: AstrMessageEvent) -> str:
        """获取平台环境信息"""
        if not self.enable_platform:
            return ""

        info_parts = []

        # 平台类型
        platform_name = event.get_platform_name()
        platform_display = PLATFORM_DISPLAY_NAMES.get(platform_name, platform_name)
        info_parts.append(f"平台: {platform_display}")

        # 判断是群聊还是私聊，优先使用 AstrMessageEvent 提供的接口
        message_type = None
        if hasattr(event, "get_message_type"):
            message_type = event.get_message_type()
        elif getattr(event, "message_obj", None):
            message_type = event.message_obj.type

        is_group_chat = False
        if message_type == MessageType.GROUP_MESSAGE:
            info_parts.append("群聊")
            is_group_chat = True
        elif message_type == MessageType.FRIEND_MESSAGE:
            info_parts.append("私聊")
        else:
            group_id = ""
            if hasattr(event, "get_group_id"):
                group_id = event.get_group_id()
            elif getattr(event, "message_obj", None):
                group_id = getattr(event.message_obj, "group_id", "")
            if group_id:
                info_parts.append("群聊")
                is_group_chat = True

        if is_group_chat:
            group_name = await self._get_group_name(event)
            if group_name:
                info_parts.append(f"群名: {group_name}")

        # 消息类型
        message_chain = event.message_obj
        if message_chain and hasattr(message_chain, 'message'):
            has_image = any(seg.type == "image" for seg in message_chain.message)
            has_audio = any(seg.type in ["voice", "audio"] for seg in message_chain.message)
            has_video = any(seg.type == "video" for seg in message_chain.message)

            if has_image:
                info_parts.append("含图片")
            if has_audio:
                info_parts.append("含语音")
            if has_video:
                info_parts.append("含视频")

        return ", ".join(info_parts)

    @filter.on_llm_request()
    async def my_custom_hook_1(self, event: AstrMessageEvent, req: ProviderRequest):
        # 获取当前时间（使用配置的时区）
        current_time = datetime.now(self.timezone)

        # 基础时间信息
        timestr = current_time.strftime("%Y-%m-%d %H:%M:%S")

        # 构建感知信息
        perception_parts = [f"发送时间: {timestr}"]

        # 添加节假日信息
        holiday_info = self._get_holiday_info(current_time)
        if holiday_info:
            perception_parts.append(holiday_info)

        # 添加农历信息
        lunar_info = self._get_lunar_info(current_time)
        if lunar_info:
            perception_parts.append(lunar_info)

        # 添加节气信息
        solar_term_info = self._get_solar_term_info(current_time)
        if solar_term_info:
            perception_parts.append(solar_term_info)

        # 添加黄历信息
        almanac_info = self._get_almanac_info(current_time)
        if almanac_info:
            perception_parts.append(almanac_info)

        # 添加平台信息
        platform_info = await self._get_platform_info(event)
        if platform_info:
            perception_parts.append(platform_info)

        # 组合所有感知信息
        perception_text = " | ".join(perception_parts)

        # 在用户消息前添加感知信息
        req.prompt = f"[{perception_text}]\n{req.prompt}"

        logger.info(f"已添加感知信息: {perception_text}")

    async def terminate(self):
        """Plugin shutdown hook (currently no-op)."""
        return
