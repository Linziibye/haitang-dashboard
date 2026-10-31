"""Use installed stable browsers through Playwright's supported branded channels."""
import os
import json
from .config import HOME
from pathlib import Path

class SystemBrowserError(RuntimeError):
    pass

LABELS = {'msedge': 'Microsoft Edge', 'chrome': 'Google Chrome'}

def _locations(channel):
    suffix = ('Microsoft/Edge/Application/msedge.exe' if channel == 'msedge'
              else 'Google/Chrome/Application/chrome.exe')
    roots = [os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'),
             os.environ.get('LOCALAPPDATA')]
    return [Path(root)/suffix for root in roots if root]

def installed_browsers():
    return [channel for channel in LABELS if any(p.is_file() for p in _locations(channel))]

def system_default_channel():
    if os.name != 'nt':
        return None
    import winreg
    try:
        key = r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            progid = winreg.QueryValueEx(handle, 'ProgId')[0].lower()
    except OSError:
        return None
    if progid.startswith('chromehtml'):
        return 'chrome'
    if progid.startswith('msedgehtm'):
        return 'msedge'
    return None

def read_preference():
    path = HOME/'data'/'browser-settings.json'
    if not path.exists():
        return 'auto'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))['channel']
    except (OSError, ValueError, KeyError) as exc:
        raise SystemBrowserError('浏览器设置无法读取，请在设置中重新选择登录与采集浏览器。') from exc
    if value not in ('auto', *LABELS):
        raise SystemBrowserError('浏览器设置无效，请选择系统默认、Chrome或Edge。')
    return value

def save_preference(value):
    if value not in ('auto', *LABELS):
        raise SystemBrowserError('浏览器选项无效。')
    path = HOME/'data'/'browser-settings.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'channel':value}),encoding='utf-8')
    os.replace(tmp,path)

def resolve_browser(preference=None):
    preference = preference or os.environ.get('HAITANG_BROWSER') or read_preference()
    if preference not in ('auto', *LABELS):
        raise SystemBrowserError('HAITANG_BROWSER仅支持auto、msedge或chrome。')
    available = installed_browsers()
    if not available:
        raise SystemBrowserError('未检测到已安装的Microsoft Edge或Google Chrome。请先安装其中一种系统浏览器，再重新打开看板；本程序不会额外下载Chromium。')
    channel = system_default_channel() if preference == 'auto' else preference
    if channel is None:
        raise SystemBrowserError('系统默认浏览器不受自动采集支持，或无法识别。请在设置中选择已安装的Google Chrome或Microsoft Edge；不会修改系统默认浏览器或下载替代浏览器。')
    if channel in available:
        return channel
    raise SystemBrowserError(f'未检测到系统{LABELS[channel]}，请在设置中选择已有的Chrome或Edge，或检查HAITANG_BROWSER设置。本程序不会额外下载浏览器。')

def main():
    try:
        print('采集将复用系统浏览器：' + LABELS[resolve_browser()])
    except SystemBrowserError as exc:
        print(str(exc))
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
