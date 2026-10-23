#!/usr/bin/env python3
"""Generate an AltStore / SideStore source.json for iCTRL.

Pulls the newest GitHub Release of OpenMinis/iCTRL and rewrites source.json
in place. Run by .github/workflows/update-source.yml on a schedule, or by hand.
"""
import json
import os
import plistlib
import ssl
import urllib.request
import zipfile
import io

# Some networks (and this sandbox) sit behind a proxy with a self-signed root.
# Set INSECURE_TLS=1 to skip verification; leave it unset on CI.
_SSL = ssl.create_default_context()
if os.environ.get("INSECURE_TLS") == "1":
    _SSL.check_hostname = False
    _SSL.verify_mode = ssl.CERT_NONE


def _urlopen(req, timeout=30):
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL)



REPO = "OpenMinis/iCTRL"
OWNER_REPO_PAGES = os.environ.get("SOURCE_BASE", "").rstrip("/")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

# bundle id -> metadata that cannot be read from GitHub alone
APP_META = {
    "com.openminis.ictrl.uitests.xctrunner": {
        "name": "iCTRL Runner",
        "asset": "iCTRLUITests-Runner.ipa",
        "subtitle": "自动化执行引擎（必装）",
        "icon": "icon_runner.png",
        "description": (
            "XCUITest 自动化引擎。常驻后台，在 8200 端口提供 JSON-RPC 2.0 服务，"
            "让 AI 代理可以点击、滑动、输入、读取任意 App 的界面。\n\n"
            "装好后从桌面点一下图标启动；它没有前台界面，会闪一下进入后台，"
            "随后在通知栏显示「iCTRL Server Ready」。\n\n"
            "前提：开发者磁盘镜像（DDI）已挂载。重启手机后需要重新挂载。"
        ),
    },
    "com.openminis.ictrl": {
        "name": "iCTRL",
        "asset": "iCTRL.ipa",
        "subtitle": "伴侣管理 App（可选）",
        "icon": "icon_app.png",
        "description": (
            "伴侣 App，负责周边事务：\n\n"
            "• 免电脑挂载开发者磁盘镜像（DDI），重启后一键重挂\n"
            "• 启动 / 停止 Runner，查看运行状态\n"
            "• 管理已授权客户端，查看来源并吊销\n"
            "• 实时查看 Runner 日志\n"
            "• 切换可见性：仅本机 / 局域网 / 附近发现\n\n"
            "如果已经用 Xcode 或 StikDebug 挂载 DDI，可以不装这个。"
        ),
    },
}


def gh(path):
    req = urllib.request.Request("https://api.github.com" + path)
    req.add_header("User-Agent", "ictrl-source-generator")
    req.add_header("Accept", "application/vnd.github+json")
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    with _urlopen(req) as r:
        return json.load(r)


def follow(url, limit=10):
    """Return the final URL after redirects (GitHub release assets redirect)."""
    for _ in range(limit):
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "ictrl-source-generator")

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=_SSL))
        try:
            with opener.open(req, timeout=30) as r:
                return url
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                url = e.headers["Location"]
            else:
                return url
    return url


def min_os(ipa_url):
    """Read MinimumOSVersion out of the IPA's Info.plist, best effort."""
    try:
        with _urlopen(ipa_url, timeout=60) as r:
            blob = r.read()
        z = zipfile.ZipFile(io.BytesIO(blob))
        for n in z.namelist():
            if n.count("/") == 2 and n.endswith(".app/Info.plist"):
                d = plistlib.loads(z.read(n))
                return str(d.get("MinimumOSVersion", "16.0")), len(blob)
    except Exception as exc:  # noqa: BLE001
        print("  min_os lookup failed:", exc)
    return "16.0", None


def main():
    rel = gh(f"/repos/{REPO}/releases/latest")
    tag = rel["tag_name"]
    date = rel["published_at"]
    print("latest:", tag, date)

    assets = {a["name"]: a for a in rel.get("assets", [])}
    apps = []

    for bundle_id, meta in APP_META.items():
        asset = assets.get(meta["asset"])
        if not asset:
            print("  skip (no asset):", meta["asset"])
            continue

        # Prefer the versioned URL; it is what AltStore resolves directly.
        url = asset["browser_download_url"]
        final = follow(url)
        os_ver, size = min_os(final if final.startswith("http") else url)
        if size is None:
            size = asset["size"]
        print(f"  {meta['name']}: {tag}  minOS {os_ver}  {size} bytes")

        base = OWNER_REPO_PAGES
        icon = f"{base}/{meta['icon']}" if base else meta["icon"]

        apps.append({
            "name": meta["name"],
            "bundleIdentifier": bundle_id,
            "developerName": "OpenMinis",
            "subtitle": meta["subtitle"],
            "localizedDescription": meta["description"],
            "iconURL": icon,
            "tintColor": "#4A90D9",
            "category": "utilities",
            "versions": [{
                "version": tag.lstrip("v"),
                "date": date,
                "size": size,
                "downloadURL": url,
                "minOSVersion": os_ver,
                "localizedDescription": rel.get("body", "")[:4000],
            }],
            "appPermissions": {"entitlements": [], "privacy": {}},
            "size": size,
            "version": tag.lstrip("v"),
            "versionDate": date,
            "downloadURL": url,
        })

    source = {
        "name": "iCTRL",
        "identifier": "app.openminis.ictrl.altsource",
        "subtitle": "AI 手机自动化引擎",
        "description": "OpenMinis iCTRL 的 AltStore / SideStore 源。自动跟随 GitHub Releases 更新。",
        "iconURL": f"{OWNER_REPO_PAGES}/icon_source.png" if OWNER_REPO_PAGES else "icon_256.png",
        "headerURL": "",
        "website": f"https://github.com/{REPO}",
        "tintColor": "#4A90D9",
        "featuredApps": [a["bundleIdentifier"] for a in apps],
        "apps": apps,
        "news": [],
    }

    with open("source.json", "w", encoding="utf-8") as f:
        json.dump(source, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("wrote source.json with", len(apps), "apps")


if __name__ == "__main__":
    main()
