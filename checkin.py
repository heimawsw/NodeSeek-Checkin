# -- coding: utf-8 --
import os
import requests
import re
import sys
import json
import hmac
import hashlib
import base64
import urllib.parse
import time
from datetime import datetime

# ========== 钉钉配置（直接填写） ==========
DD_BOT_TOKEN = "3bad21b529967b114235c5e5c7a5d987719a905ae9d95b480c555a235bbba612"
DD_BOT_SECRET = "SEC4a050251f92e72d5864c44b2e76edbc518380260bc67f4651064d8d3d9ea8e3e"
# ========================================

def parse_expiry_date(expiry_str):
    """解析过期日期（格式：YYYY-MM-DD），返回剩余天数"""
    if not expiry_str:
        return None
    try:
        expiry = datetime.strptime(expiry_str.strip(), "%Y-%m-%d")
        delta = expiry - datetime.now()
        return delta.days
    except Exception:
        return None

def send_telegram_message(text):
    bot_token = os.getenv('TG_BOT_TOKEN')
    chat_id = os.getenv('TG_CHAT_ID')
    if not bot_token or not chat_id:
        print("未配置 Telegram 通知，跳过。")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }, timeout=10)
        if resp.status_code == 200:
            print("Telegram 通知发送成功。")
        else:
            print(f"Telegram 通知失败: {resp.text}")
    except Exception as e:
        print(f"发送 Telegram 异常: {e}")

def calc_dingtalk_sign(secret):
    """计算钉钉机器人加签签名，返回 (timestamp, sign)"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = f"{timestamp}\n{secret}"
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign

def send_dingtalk_message(text):
    """发送钉钉机器人通知（Markdown格式）"""
    if not DD_BOT_TOKEN or not DD_BOT_SECRET:
        print("未配置钉钉通知，跳过。")
        return
    
    timestamp, sign = calc_dingtalk_sign(DD_BOT_SECRET)
    url = f"https://oapi.dingtalk.com/robot/send?access_token={DD_BOT_TOKEN}&timestamp={timestamp}&sign={sign}"
    
    # 将 HTML 加粗标签转换为 Markdown
    markdown_content = text.replace('<b>', '**').replace('</b>', '**')
    
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": "NodeSeek 签到汇总",
            "text": markdown_content
        }
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get('errcode') == 0:
            print("钉钉通知发送成功。")
        else:
            print(f"钉钉通知失败: {result.get('errmsg', resp.text)}")
    except Exception as e:
        print(f"发送钉钉异常: {e}")

def checkin(cookie, random_mode=False):
    """签到函数"""
    random_param = 'true' if random_mode else 'false'
    url = f"https://www.nodeseek.com/api/attendance?random={random_param}"
    
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh-Hans;q=0.9,en;q=0.8',
        'Content-Type': 'application/json',
        'Cookie': cookie,
        'Origin': 'https://www.nodeseek.com',
        'Referer': 'https://www.nodeseek.com/board',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        resp = requests.post(url, headers=headers, timeout=15)
    except Exception as e:
        return False, f"请求异常: {e}", 0

    if resp.status_code != 200:
        if resp.status_code == 500:
            if '已签到' in resp.text or '重复' in resp.text:
                return True, "已签到（今日已打卡）", 0
        return False, f"HTTP {resp.status_code}", 0

    try:
        result = resp.json()
    except:
        return False, f"非JSON响应: {resp.text[:100]}", 0

    success = result.get('success', False)
    msg = result.get('message', '')
    state = result.get('state', '')

    if not success and re.search(r'(已完成签到|已签到|重复|already|duplicate)', msg, re.I):
        return True, "已签到（今日已打卡）", 0

    chicken = 0
    if success or state == 'success':
        m = re.search(r'获得(\d+)鸡腿', msg)
        if m:
            chicken = int(m.group(1))
        return True, msg, chicken

    return False, msg, 0

def main():
    cookies_raw = os.getenv('NS_COOKIES')
    if not cookies_raw:
        print("错误: 未设置 NS_COOKIES")
        sys.exit(1)

    random_mode = os.getenv('NS_RANDOM', 'false').strip().lower() == 'true'

    lines = [line.strip() for line in cookies_raw.split('\n') if line.strip()]
    if not lines:
        print("错误: NS_COOKIES 为空")
        sys.exit(1)

    print(f"签到模式: {'试试手气' if random_mode else '固定鸡腿'}")
    print(f"检测到 {len(lines)} 个账号，开始签到...")
    results = []

    accounts = []
    for line in lines:
        parts = line.split('|')
        if len(parts) >= 3:
            username = parts[0].strip()
            cookie = parts[1].strip()
            expiry_date = parts[2].strip()
        elif len(parts) == 2:
            username = parts[0].strip()
            cookie = parts[1].strip()
            expiry_date = None
        else:
            username = None
            cookie = line
            expiry_date = None
        accounts.append((username, cookie, expiry_date))

    for idx, (username, cookie, expiry_date) in enumerate(accounts, 1):
        display_name = username if username else f"账号 {idx}"

        days_left = parse_expiry_date(expiry_date)
        days_str = f"{days_left} 天" if days_left is not None else "未知"

        success, msg, chicken = checkin(cookie, random_mode)
        status_icon = "✅" if success else "❌"
        if success and chicken == 0:
            numbers = re.findall(r'\d+', msg)
            if numbers:
                chicken = int(numbers[0])

        result_line = f"{display_name}: {status_icon} {msg}\n 获得 {chicken} 鸡腿 \n cookie到期剩余 {days_str} \n https://www.nodeseek.com/"
        results.append(result_line)
        print(result_line)

    final_msg = "<b>📅 NodeSeek 签到汇总</b>\n" + "\n".join(results)
    send_telegram_message(final_msg)
    send_dingtalk_message(final_msg)

if __name__ == "__main__":
    main()
