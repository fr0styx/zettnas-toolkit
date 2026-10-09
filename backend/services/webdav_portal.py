"""
ZettNAS Toolkit - Modern WebDAV Cloud Portal
Provides a responsive, dark glassmorphic web interface for WebDAV file browsing and login.
"""

import html
import os
import time
import urllib.parse
from typing import Any, Dict, List, Optional


def format_size(bytes_val: int) -> str:
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


def format_mtime(timestamp: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except Exception:
        return "--"


def get_file_icon(name: str, is_dir: bool) -> str:
    if is_dir:
        return "📁"
    ext = os.path.splitext(name)[1].lower()
    if ext in (".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar"):
        return "📦"
    elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"):
        return "🖼️"
    elif ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"):
        return "🎬"
    elif ext in (".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a"):
        return "🎵"
    elif ext in (".pdf", ".doc", ".docx", ".txt", ".md", ".rtf"):
        return "📄"
    elif ext in (".py", ".js", ".ts", ".json", ".yaml", ".yml", ".sh", ".html", ".css"):
        return "📜"
    elif ext in (".iso", ".img", ".vmdk", ".qcow2"):
        return "💿"
    return "📄"


def render_webdav_login(error_msg: Optional[str] = None) -> str:
    err_html = (
        f"""
    <div style="background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #fca5a5; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;">
        <span>⚠️</span> <span>{html.escape(error_msg)}</span>
    </div>
    """
        if error_msg
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sign In • ZettNAS WebDAV Portal</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #080c14;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            background-image:
                radial-gradient(circle at 50% 10%, rgba(14, 165, 233, 0.12) 0%, transparent 50%),
                radial-gradient(circle at 90% 90%, rgba(16, 185, 129, 0.08) 0%, transparent 40%);
        }}
        .login-card {{
            background: rgba(17, 24, 39, 0.88);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 36px;
            width: 100%;
            max-width: 420px;
            box-shadow: 0 25px 60px rgba(0, 0, 0, 0.8), 0 0 40px rgba(14, 165, 233, 0.12);
        }}
        .brand-header {{
            text-align: center;
            margin-bottom: 28px;
        }}
        .brand-icon {{
            font-size: 40px;
            display: inline-block;
            margin-bottom: 12px;
            filter: drop-shadow(0 0 16px rgba(56, 189, 248, 0.5));
        }}
        .brand-title {{
            font-size: 20px;
            font-weight: 800;
            letter-spacing: 0.5px;
            color: #fff;
            margin-bottom: 6px;
        }}
        .brand-subtitle {{
            font-size: 13px;
            color: #94a3b8;
        }}
        .form-group {{
            margin-bottom: 18px;
        }}
        .form-label {{
            display: block;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #94a3b8;
            margin-bottom: 6px;
        }}
        .form-input {{
            width: 100%;
            background: rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            padding: 12px 14px;
            color: #fff;
            font-size: 14px;
            outline: none;
            transition: all 0.2s ease;
        }}
        .form-input:focus {{
            border-color: #38bdf8;
            box-shadow: 0 0 12px rgba(56, 189, 248, 0.3);
            background: rgba(0, 0, 0, 0.6);
        }}
        .btn-submit {{
            width: 100%;
            background: linear-gradient(135deg, #0284c7 0%, #0369a1 100%);
            border: 1px solid rgba(56, 189, 248, 0.4);
            color: #fff;
            font-weight: 700;
            font-size: 14px;
            padding: 12px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            margin-top: 10px;
            box-shadow: 0 4px 14px rgba(2, 132, 199, 0.4);
        }}
        .btn-submit:hover {{
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%);
            box-shadow: 0 6px 20px rgba(14, 165, 233, 0.6);
            transform: translateY(-1px);
        }}
        .footer-links {{
            margin-top: 24px;
            text-align: center;
            font-size: 12px;
            color: #64748b;
        }}
        .footer-links a {{
            color: #38bdf8;
            text-decoration: none;
            font-weight: 600;
        }}
        .footer-links a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="login-card">
        <div class="brand-header">
            <div class="brand-icon">☁️</div>
            <h1 class="brand-title">ZettNAS WebDAV Portal</h1>
            <p class="brand-subtitle">Sign in with your storage credentials</p>
        </div>
        {err_html}
        <form action="/webdav/auth/login" method="POST">
            <div class="form-group">
                <label class="form-label" for="username">Username</label>
                <input class="form-input" type="text" id="username" name="username" value="admin" required autofocus autocomplete="username">
            </div>
            <div class="form-group">
                <label class="form-label" for="password">Password</label>
                <input class="form-input" type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            <button class="btn-submit" type="submit">Sign In to WebDAV</button>
        </form>
        <div class="footer-links">
            <a href="/">← Return to ZettNAS Workbench</a>
        </div>
    </div>
</body>
</html>"""


def render_webdav_portal(current_subpath: str, root_path: str, username: str) -> str:
    clean_sub = current_subpath.strip("/")
    abs_dir = os.path.abspath(os.path.join(root_path, clean_sub)) if clean_sub else os.path.abspath(root_path)

    # Path traversal protection
    if not abs_dir.startswith(os.path.abspath(root_path)):
        abs_dir = os.path.abspath(root_path)
        clean_sub = ""

    items: List[Dict[str, Any]] = []

    if os.path.isdir(abs_dir):
        try:
            with os.scandir(abs_dir) as entries:
                for entry in entries:
                    try:
                        st = entry.stat()
                        is_dir = entry.is_dir(follow_symlinks=True)
                        items.append(
                            {
                                "name": entry.name,
                                "is_dir": is_dir,
                                "size": st.st_size if not is_dir else 0,
                                "mtime": st.st_mtime,
                            }
                        )
                    except (PermissionError, FileNotFoundError):
                        continue
        except Exception:
            pass

    # Sort folders first, then alphabetically
    items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    # Build breadcrumbs
    parts = [p for p in clean_sub.split("/") if p]
    crumbs_html = ['<a href="/webdav/" class="crumb">Root</a>']
    cum_path = ""
    for p in parts:
        cum_path += f"/{urllib.parse.quote(p)}"
        crumbs_html.append(
            f'<span class="crumb-sep">/</span><a href="/webdav{cum_path}/" class="crumb">{html.escape(p)}</a>'
        )
    breadcrumbs_rendered = " ".join(crumbs_html)

    # Parent directory link
    parent_html = ""
    if parts:
        parent_parts = parts[:-1]
        parent_encoded = "/".join(urllib.parse.quote(p) for p in parent_parts)
        parent_href = f"/webdav/{parent_encoded}/" if parent_parts else "/webdav/"
        parent_html = f"""
        <tr class="dir-row parent-dir-row">
            <td class="col-icon">📁</td>
            <td class="col-name"><a href="{parent_href}" class="file-link">.. (Go up)</a></td>
            <td class="col-size">--</td>
            <td class="col-date">--</td>
            <td class="col-action"></td>
        </tr>
        """

    rows_html = []
    for it in items:
        name = it["name"]
        is_dir = it["is_dir"]
        icon = get_file_icon(name, is_dir)
        size_str = "--" if is_dir else format_size(it["size"])
        date_str = format_mtime(it["mtime"])

        rel_target = f"{clean_sub}/{name}" if clean_sub else name
        encoded_target = "/".join(urllib.parse.quote(part) for part in rel_target.split("/"))
        if is_dir:
            href = f"/webdav/{encoded_target}/"
            action_btn = f'<a href="{href}" class="btn-open">Open</a>'
            link_target = ""
        else:
            href = f"/webdav/{encoded_target}"
            action_btn = f'<a href="{href}?raw=1" download="{html.escape(name)}" class="btn-download">⬇️ Download</a>'
            link_target = 'target="_blank" rel="noopener noreferrer"'

        rows_html.append(f"""
        <tr class="file-row {"is-dir" if is_dir else "is-file"}">
            <td class="col-icon">{icon}</td>
            <td class="col-name"><a href="{href}" class="file-link {"dir-link" if is_dir else ""}" {link_target}>{html.escape(name)}</a></td>
            <td class="col-size">{size_str}</td>
            <td class="col-date">{date_str}</td>
            <td class="col-action">{action_btn}</td>
        </tr>
        """)

    tbody_content = parent_html + "".join(rows_html)
    if not items and not parent_html:
        tbody_content = """<tr><td colspan="5" style="text-align:center; padding:30px; color:#64748b;">Directory is empty.</td></tr>"""

    item_count = len(items)
    dir_count = sum(1 for it in items if it["is_dir"])
    file_count = item_count - dir_count

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ZettNAS WebDAV • /{html.escape(clean_sub)}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #080c14;
            color: #f1f5f9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        .top-navbar {{
            background: rgba(15, 23, 42, 0.92);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
        }}
        .brand {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 15px;
            font-weight: 800;
            color: #fff;
            text-decoration: none;
        }}
        .brand-badge {{
            background: rgba(56, 189, 248, 0.15);
            border: 1px solid rgba(56, 189, 248, 0.3);
            color: #38bdf8;
            font-size: 10px;
            font-weight: 700;
            padding: 2px 7px;
            border-radius: 4px;
            letter-spacing: 0.5px;
        }}
        .nav-actions {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .btn-nav {{
            font-size: 12px;
            font-weight: 600;
            padding: 6px 12px;
            border-radius: 6px;
            text-decoration: none;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }}
        .btn-home {{
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #94a3b8;
        }}
        .btn-home:hover {{
            background: rgba(255, 255, 255, 0.12);
            color: #fff;
        }}
        .btn-logout {{
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.25);
            color: #f87171;
        }}
        .btn-logout:hover {{
            background: #ef4444;
            color: #fff;
        }}
        .main-container {{
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
            padding: 24px;
            flex: 1;
        }}
        .toolbar {{
            background: rgba(17, 24, 39, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 14px 18px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            flex-wrap: wrap;
        }}
        .breadcrumbs {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 13.5px;
            font-weight: 600;
            color: #94a3b8;
        }}
        .crumb {{
            color: #38bdf8;
            text-decoration: none;
            transition: color 0.15s;
        }}
        .crumb:hover {{
            text-decoration: underline;
            color: #7dd3fc;
        }}
        .crumb-sep {{
            color: #475569;
        }}
        .search-box {{
            position: relative;
            min-width: 240px;
        }}
        .search-input {{
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #fff;
            padding: 7px 12px 7px 32px;
            border-radius: 6px;
            font-size: 12.5px;
            outline: none;
            width: 100%;
            transition: all 0.2s;
        }}
        .search-input:focus {{
            border-color: #38bdf8;
            background: rgba(0, 0, 0, 0.55);
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);
        }}
        .search-icon {{
            position: absolute;
            left: 10px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 13px;
            opacity: 0.5;
        }}
        .table-card {{
            background: rgba(17, 24, 39, 0.85);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 16px 36px rgba(0, 0, 0, 0.5);
        }}
        .file-table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 13px;
        }}
        .file-table th {{
            background: rgba(255, 255, 255, 0.03);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding: 12px 16px;
            font-size: 11px;
            font-weight: 700;
            color: #94a3b8;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .file-table td {{
            padding: 12px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            vertical-align: middle;
        }}
        .file-row:hover {{
            background: rgba(255, 255, 255, 0.04);
        }}
        .col-icon {{
            width: 38px;
            text-align: center;
            font-size: 18px;
        }}
        .col-name {{
            font-weight: 600;
        }}
        .col-size {{
            color: #94a3b8;
            font-family: monospace;
            font-size: 12px;
            width: 110px;
        }}
        .col-date {{
            color: #64748b;
            font-size: 12px;
            width: 160px;
        }}
        .col-action {{
            width: 110px;
            text-align: right;
        }}
        .file-link {{
            color: #e2e8f0;
            text-decoration: none;
            transition: color 0.15s;
        }}
        .file-link.dir-link {{
            color: #38bdf8;
            font-weight: 700;
        }}
        .file-link:hover {{
            color: #67e8f9;
            text-decoration: underline;
        }}
        .btn-download, .btn-open {{
            background: rgba(56, 189, 248, 0.1);
            border: 1px solid rgba(56, 189, 248, 0.25);
            color: #38bdf8;
            padding: 4px 10px;
            border-radius: 4px;
            text-decoration: none;
            font-size: 11px;
            font-weight: 600;
            transition: all 0.15s;
            display: inline-block;
        }}
        .btn-download:hover, .btn-open:hover {{
            background: #38bdf8;
            color: #0b131a;
            box-shadow: 0 0 8px rgba(56, 189, 248, 0.4);
        }}
        .meta-footer {{
            margin-top: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
            color: #64748b;
            padding: 0 6px;
        }}
    </style>
</head>
<body>
    <header class="top-navbar">
        <a href="/webdav/" class="brand">
            <span>☁️</span>
            <span>ZettNAS WebDAV Portal</span>
            <span class="brand-badge">LINE-RATE</span>
        </a>
        <div class="nav-actions">
            <span style="font-size: 12px; color: #94a3b8;">👤 {html.escape(username)}</span>
            <a href="/" class="btn-nav btn-home">🖥️ Workbench Desktop</a>
            <a href="/webdav/auth/logout" class="btn-nav btn-logout">Sign Out</a>
        </div>
    </header>

    <main class="main-container">
        <div class="toolbar">
            <div class="breadcrumbs">
                {breadcrumbs_rendered}
            </div>
            <div class="search-box">
                <span class="search-icon">🔍</span>
                <input type="text" id="search-input" class="search-input" placeholder="Filter files & folders..." oninput="filterFiles()">
            </div>
        </div>

        <div class="table-card">
            <table class="file-table">
                <thead>
                    <tr>
                        <th class="col-icon"></th>
                        <th class="col-name">Name</th>
                        <th class="col-size">Size</th>
                        <th class="col-date">Modified</th>
                        <th class="col-action">Action</th>
                    </tr>
                </thead>
                <tbody id="file-table-body">
                    {tbody_content}
                </tbody>
            </table>
        </div>

        <div class="meta-footer">
            <div>Path: <code style="color:#38bdf8;">/{html.escape(clean_sub)}</code></div>
            <div>{dir_count} folder{"s" if dir_count != 1 else ""}, {file_count} file{"s" if file_count != 1 else ""}</div>
        </div>
    </main>

    <script>
        function filterFiles() {{
            const query = document.getElementById('search-input').value.toLowerCase();
            const rows = document.querySelectorAll('#file-table-body .file-row');
            rows.forEach(r => {{
                const name = r.querySelector('.col-name')?.textContent.toLowerCase() || '';
                r.style.display = name.includes(query) ? '' : 'none';
            }});
        }}
    </script>
</body>
</html>"""
