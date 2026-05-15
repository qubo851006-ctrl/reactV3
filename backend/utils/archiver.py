import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import shutil
import re
from config import DATA_ROOT


ARCHIVE_ROOT = os.path.join(DATA_ROOT, "培训档案")


def sanitize_folder_name(name: str) -> str:
    """去掉文件夹名中不合法的字符"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def archive_files(
    notice_path: str,
    sign_in_path: str,
    category: str,
    date: str,
    topic: str,
) -> str:
    """
    将培训通知和签到表归档到对应文件夹
    返回: 归档后的文件夹路径
    """
    safe_date = sanitize_folder_name(date) if date else "日期未知"
    safe_topic = sanitize_folder_name(topic) if topic else "主题未知"
    safe_category = sanitize_folder_name(category) if category else "其他培训"

    folder_name = f"{safe_date}_{safe_topic}"
    target_dir = os.path.join(ARCHIVE_ROOT, safe_category, folder_name)
    os.makedirs(target_dir, exist_ok=True)

    # 归档培训通知
    notice_ext = os.path.splitext(notice_path)[1]
    notice_dest = os.path.join(target_dir, f"培训通知{notice_ext}")
    shutil.copy2(notice_path, notice_dest)

    # 归档签到表
    sign_in_ext = os.path.splitext(sign_in_path)[1]
    sign_in_dest = os.path.join(target_dir, f"签到表{sign_in_ext}")
    shutil.copy2(sign_in_path, sign_in_dest)

    return target_dir
