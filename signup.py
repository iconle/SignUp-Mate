"""问卷星辅助报名：python signup.py，首次运行前安装 requirements.txt。"""
import json
import re
import random
import time
from urllib.parse import urlparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def accept_reading(page):
    """仅勾选带阅读确认文字的复选框，不点击无关选项。"""
    pattern = re.compile(r'请先阅读|我已阅读|已阅读并|阅读并同意')
    for checkbox in page.get_by_role('checkbox', name=pattern).all():
        if checkbox.is_visible() and checkbox.is_enabled():
            checkbox.check(timeout=3000)
    for label in page.locator('label, .ui-checkbox').all():
        if not label.is_visible() or not pattern.search(label.inner_text()):
            continue
        checkbox = label.locator('input[type=checkbox]')
        if checkbox.count() == 1:
            if not checkbox.is_checked():
                checkbox.check(force=True, timeout=3000)


def wait_submission(page, timeout=15):
    """处理提交后的协议弹窗，并等待明确的成功提示。"""
    deadline = time.monotonic() + timeout
    consent_clicked = False
    success = page.get_by_text(re.compile('提交成功|报名成功|答卷已经提交|您已完成'))
    while time.monotonic() < deadline:
        if any(node.is_visible() for node in success.all()):
            return True
        if not consent_clicked:
            consent = page.get_by_text('同意并继续', exact=True)
            buttons = [node for node in consent.all() if node.is_visible()]
            if len(buttons) == 1 and buttons[0].is_enabled():
                buttons[0].click(timeout=3000)
                consent_clicked = True
                print('已确认填答者协议和隐私条款，继续提交……')
        page.wait_for_timeout(50)
    return False


def load_config():
    path = Path(__file__).with_name('config.json')
    config = json.loads(path.read_text(encoding='utf-8'))
    for key, value in config.get('answers', {}).items():
        if not str(value).strip() or str(value).startswith('请填写'):
            answer = input(f'首次设置—{key}（可回车跳过）：').strip()
            if answer:
                config['answers'][key] = answer
    print('个人信息沿用 config.json。按 Ctrl+C 可取消。')
    while True:
        url = input('报名链接（回车沿用原链接）：').strip() or config['url']
        parsed = urlparse(url)
        if parsed.scheme in ('http', 'https') and parsed.hostname:
            break
        print('请输入完整链接，例如 https://www.wjx.top/vm/xxxx.aspx')
    while True:
        raw = input('开始时间（如 2026-11-28 17:30 或 17:30；回车立即开始）：').strip()
        if not raw:
            start_at = ''
            break
        try:
            now = datetime.now(ZoneInfo('Asia/Shanghai'))
            if re.fullmatch(r'\d{1,2}:\d{2}(:\d{2})?', raw):
                parts = [int(part) for part in raw.split(':')]
                target = now.replace(hour=parts[0], minute=parts[1],
                                     second=parts[2] if len(parts) == 3 else 0,
                                     microsecond=0)
            else:
                target = datetime.fromisoformat(raw.replace('/', '-'))
                if target.tzinfo is None:
                    target = target.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
            if target <= now:
                print('该时间已过去，请输入未来时间；立即运行请直接回车。')
                continue
            start_at = target.isoformat()
            break
        except ValueError:
            print('时间格式不正确，请输入 年-月-日 时:分:秒，或今天的 时:分。')
    config.update(url=url, start_at=start_at)
    # 先写临时文件再替换，避免写入中断损坏配置。
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    print(f'已保存配置，开始时间：{start_at or "立即"}')
    return config


def main():
    config = load_config()
    target = None
    if config.get('start_at'):
        target = datetime.fromisoformat(config['start_at'])
        if target.tzinfo is None:
            target = target.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            page.goto(config['url'], wait_until='domcontentloaded', timeout=60000)
            if target and target.timestamp() > time.time():
                print(f'浏览器已打开，等待至 {target.isoformat()} 再报名。')
                print('请核对日期；若输错，按 Ctrl+C 后重新运行。')
                accept_reading(page)
                while (remaining := target.timestamp() - time.time()) > 0:
                    page.wait_for_timeout(min(remaining * 1000, 100))
            deadline = time.monotonic() + float(config.get('wait_open_seconds', 600))
            last_click = 0.0
            last_refresh = time.monotonic()
            refresh_interval = max(3.0, float(config.get('refresh_interval_seconds', 5)))
            while True:
                if page.is_closed():
                    raise RuntimeError('报名页面已关闭')
                pages = page.context.pages
                if pages and pages[-1] != page:
                    page = pages[-1]
                # 先检查题目，出现后立即进入填写，不再固定等待。
                if page.locator('.field:visible').count():
                    break
                now = time.monotonic()
                if now >= deadline:
                    raise RuntimeError('等待开放超时，请检查页面。')
                accept_reading(page)
                entry = page.get_by_text('立即报名', exact=True)
                visible_entries = [node for node in entry.all() if node.is_visible()]
                if (len(visible_entries) == 1 and visible_entries[0].is_enabled()
                        and now - last_click >= 1):
                    try:
                        # trial 检查按钮是否真正可点击（含遮罩检查）。
                        visible_entries[0].click(trial=True, timeout=100)
                        last_click = now
                        visible_entries[0].click(timeout=500)
                        print('已点击报名入口，等待题目出现……')
                    except PlaywrightTimeoutError:
                        pass
                # 只有明确显示未开放且没有可见入口时才刷新。
                # 有入口时保持原页，避免刷新打断跳转或丢失确认框状态。
                unopened = page.get_by_text(re.compile('尚未开始|还未开始|未到.*时间|尚未开放|暂未开放'))
                needs_reload = any(node.is_visible() for node in unopened.all())
                if needs_reload and not visible_entries and now - last_refresh >= refresh_interval:
                    print('页面提示尚未开放，重新加载检查……')
                    page.reload(wait_until='domcontentloaded', timeout=60000)
                    last_refresh = time.monotonic()
                else:
                    # 仅本地检测，不在此轮询中发送刷新请求。
                    page.wait_for_timeout(50)
            form_started = time.monotonic()
            target_duration = random.uniform(3.0, 4.0)
            print(f'本次填表至提交目标用时：{target_duration:.2f} 秒')
            filled = 0
            incomplete = False
            for field in page.locator('.field').all():
                if not field.is_visible():
                    continue
                title_node = field.locator('.field-label')
                if not title_node.count():
                    incomplete = True
                    continue
                title = title_node.first.inner_text().strip()
                if re.search(r'请先阅读|我已阅读|已阅读并|阅读并同意', title):
                    accept_reading(page)
                    checks = field.locator('input[type=checkbox]')
                    if checks.count() and all(c.is_checked() for c in checks.all()):
                        filled += 1
                        print('[已勾选] 阅读确认')
                        continue
                matches = [(k, v) for k, v in config['answers'].items() if k in title]
                # 同义题目键可能同时命中，优先使用最具体的键。
                if matches:
                    matches = [max(matches, key=lambda item: len(item[0]))]
                if len(matches) != 1:
                    incomplete = True
                    print(f'[待手填] {title}（配置匹配数：{len(matches)}）')
                    continue
                value = str(matches[0][1])
                if not value or value.startswith('请填写'):
                    incomplete = True
                    print(f'[待手填] {title}')
                    continue
                inputs = field.locator('input:not([type=hidden]):not([type=radio]):not([type=checkbox]), textarea')
                selects = field.locator('select')
                try:
                    if inputs.count() == 1:
                        inputs.fill(value)
                    elif selects.count() == 1:
                        selects.select_option(label=value)
                    else:
                        options = field.locator('.ui-radio, .ui-checkbox').filter(has_text=value)
                        exact = [o for o in options.all() if o.inner_text().strip() == value]
                        if len(exact) != 1:
                            raise ValueError('选项无法唯一匹配')
                        exact[0].click()
                    print(f'[已填] {title}')
                    filled += 1
                except Exception as error:
                    incomplete = True
                    print(f'[待手填] {title}: {error}')
            if config.get('auto_submit', True) and filled and not incomplete:
                accept_reading(page)
                buttons = page.locator('#ctlNext, #submit_button').all()
                buttons = [button for button in buttons if button.is_visible()]
                if not buttons:
                    buttons = [button for button in page.get_by_text('提交', exact=True).all()
                               if button.is_visible()]
                if len(buttons) == 1 and buttons[0].is_enabled():
                    remaining = target_duration - (time.monotonic() - form_started)
                    if remaining > 0:
                        page.wait_for_timeout(remaining * 1000)
                    buttons[0].click(timeout=5000)
                    print('已点击提交，正在等待结果……')
                    if wait_submission(page):
                        print('页面显示提交成功。')
                    else:
                        print('尚未确认提交成功，请检查页面提示、验证码或校验错误；不会重复提交。')
                else:
                    print('未找到唯一可用的提交按钮，请手动检查。')
            elif incomplete or not filled:
                print('存在未完成或无法识别的题目，已暂停自动提交。')
        except Exception as error:
            print(f'页面未能自动填表，请在浏览器中检查：{error}')
        print('请检查浏览器中的最终结果；如有验证码或漏填，请手动完成。')
        input('完成报名后按回车关闭浏览器……')
        browser.close()


if __name__ == '__main__':
    main()
