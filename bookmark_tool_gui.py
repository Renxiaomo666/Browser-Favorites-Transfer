#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Bookmark Tool Pro V2
Refactored by IT_MAN
功能：全能书签互导工具 (Edge/Chrome 双向支持)，支持自动备份与清理，现代化 UI。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
import glob
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from threading import Thread

# 引入现代化 UI 库
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from tkinter import filedialog


# =============================================================================
# 1. 基础配置与日志 (Infrastructure)
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("BookmarkTool")

APP_TITLE = "全能书签同步助手 Pro"
APP_SIZE = (900, 700)  # 稍微调高一点高度以容纳新选项
OUTPUT_DIR = Path.cwd() / "output"
BACKUP_RETENTION_DAYS = 7


# =============================================================================
# 2. 数据模型 (Data Models)
# =============================================================================

@dataclass(frozen=True)
class ExportRequest:
    """导出请求参数"""
    browser: str        # "chrome" / "edge" (新增字段)
    profile: str        # 原 edge_profile 改为通用 profile
    root: str           # "bookmark_bar" / "other" / "synced"
    folder_name: str
    include_subfolders: bool


@dataclass(frozen=True)
class ImportRequest:
    """导入请求参数"""
    browser: str        # "chrome" / "edge"
    profile: str
    root: str           # "bookmark_bar" / "other"
    folder_name: str
    txt_path: Path


# =============================================================================
# 3. 工具类 (Utilities)
# =============================================================================

class FileUtils:
    """文件操作工具集"""

    @staticmethod
    def chromium_time_us() -> str:
        unix_us = int(time.time() * 1_000_000)
        chromium_us = unix_us + 11644473600 * 1_000_000
        return str(chromium_us)

    @staticmethod
    def sanitize_filename(name: str, max_len: int = 120) -> str:
        name = name.strip()
        name = re.sub(r'[\\/:*?"<>|]+', "_", name)
        name = re.sub(r"[\x00-\x1f\x7f]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        if not name:
            name = "export"
        return name[:max_len].rstrip()

    @staticmethod
    def read_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Bookmarks 文件未找到：{path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise ValueError(f"文件损坏，无法解析 JSON：{path}")

    @staticmethod
    def write_json(path: Path, data: Dict[str, Any]) -> None:
        temp_path = path.with_suffix(".tmp")
        try:
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(path)
        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            raise e


class AutoCleaner:
    """自动清理逻辑"""
    
    @staticmethod
    def clean_old_backups(target_dir: Path, pattern: str = "*.bak_*", days: int = 7) -> int:
        if not target_dir.exists():
            return 0
        
        count = 0
        now = time.time()
        retention_sec = days * 86400
        search_pattern = str(target_dir / pattern)
        
        for file_path in glob.glob(search_pattern):
            p = Path(file_path)
            try:
                mtime = p.stat().st_mtime
                if now - mtime > retention_sec:
                    p.unlink()
                    logger.info(f"清理过期备份: {p.name}")
                    count += 1
            except Exception as e:
                logger.warning(f"无法删除文件 {p}: {e}")
        return count


class PathFinder:
    """路径探测逻辑"""
    
    @staticmethod
    def get_bookmarks_path(browser: str, profile: str) -> Path:
        home = Path.home()
        browser = browser.lower()
        
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise FileNotFoundError("无法获取 LOCALAPPDATA 环境变量")
            
            base = Path(local_app_data)
            if browser == "chrome":
                return base / "Google" / "Chrome" / "User Data" / profile / "Bookmarks"
            elif browser == "edge":
                return base / "Microsoft" / "Edge" / "User Data" / profile / "Bookmarks"

        elif sys.platform == "darwin":
            app_support = home / "Library" / "Application Support"
            if browser == "chrome":
                return app_support / "Google" / "Chrome" / profile / "Bookmarks"
            elif browser == "edge":
                return app_support / "Microsoft Edge" / profile / "Bookmarks"

        else:
            config = home / ".config"
            candidates = []
            if browser == "chrome":
                candidates = ["google-chrome", "chromium"]
            elif browser == "edge":
                candidates = ["microsoft-edge", "microsoft-edge-beta", "microsoft-edge-dev"]
            
            for folder in candidates:
                p = config / folder / profile / "Bookmarks"
                if p.exists():
                    return p
            if candidates:
                return config / candidates[0] / profile / "Bookmarks"

        raise ValueError(f"不支持的浏览器类型: {browser}")


# =============================================================================
# 4. 核心业务逻辑 (Business Logic)
# =============================================================================

class BookmarkManager:
    """书签管理核心业务类"""

    def export_bookmarks(self, req: ExportRequest) -> Tuple[str, int, str]:
        """执行导出逻辑"""
        # 1. 定位文件 (根据请求的 browser 类型)
        bm_path = PathFinder.get_bookmarks_path(req.browser, req.profile)
        logger.info(f"正在读取 {req.browser} 书签: {bm_path}")
        
        data = FileUtils.read_json(bm_path)
        
        # 2. 定位根节点
        root_node = data.get("roots", {}).get(req.root)
        if not root_node:
            raise KeyError(f"在 {req.profile} 中找不到根目录 '{req.root}'")

        # 3. 递归查找目标文件夹
        target_node = self._find_node_by_name(root_node, req.folder_name)
        if not target_node:
            raise FileNotFoundError(f"在 {req.browser} 的 {req.root} 下未找到文件夹: '{req.folder_name}'")

        # 4. 收集 URL
        pairs = self._collect_urls(target_node, req.include_subfolders)
        if not pairs:
            raise ValueError("该文件夹下为空，没有可导出的书签。")

        # 5. 写入 TXT
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        file_name = f"{FileUtils.sanitize_filename(req.folder_name)}.txt"
        out_path = OUTPUT_DIR / file_name
        
        with out_path.open("w", encoding="utf-8") as f:
            for name, url in pairs:
                f.write(f"{name}\n{url}\n\n")

        return str(out_path), len(pairs), str(bm_path)

    def import_bookmarks(self, req: ImportRequest) -> Tuple[str, int, str, str]:
        """执行导入逻辑"""
        pairs = self._parse_txt(req.txt_path)
        if not pairs:
            raise ValueError("TXT 文件格式不正确或为空。")

        bm_path = PathFinder.get_bookmarks_path(req.browser, req.profile)
        data = FileUtils.read_json(bm_path)

        # 备份
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_path = bm_path.with_name(f"{bm_path.name}.bak_{ts}")
        backup_path.write_bytes(bm_path.read_bytes())
        
        # 自动清理
        AutoCleaner.clean_old_backups(bm_path.parent, days=BACKUP_RETENTION_DAYS)

        root_node = data.get("roots", {}).get(req.root)
        if not root_node:
            raise KeyError(f"找不到根目录 '{req.root}'")

        max_id = self._find_max_id(data)
        next_id = max_id + 1

        folder_name = req.folder_name
        if self._check_folder_exists(root_node, folder_name):
            folder_name = f"{folder_name}_{ts}"

        new_folder = {
            "children": [],
            "date_added": FileUtils.chromium_time_us(),
            "date_modified": FileUtils.chromium_time_us(),
            "id": str(next_id),
            "name": folder_name,
            "type": "folder",
            "guid": str(uuid.uuid4()),
        }
        next_id += 1

        for title, url in pairs:
            new_url_node = {
                "date_added": FileUtils.chromium_time_us(),
                "id": str(next_id),
                "name": title,
                "type": "url",
                "url": url,
                "guid": str(uuid.uuid4()),
            }
            new_folder["children"].append(new_url_node)
            next_id += 1
        
        root_node.setdefault("children", []).append(new_folder)
        FileUtils.write_json(bm_path, data)

        return folder_name, len(pairs), str(bm_path), str(backup_path)

    # --- Helpers ---
    def _find_node_by_name(self, node: Dict, name: str) -> Optional[Dict]:
        if node.get("type") == "folder" and node.get("name") == name:
            return node
        for child in node.get("children", []):
            if child.get("type") == "folder":
                res = self._find_node_by_name(child, name)
                if res: return res
        return None

    def _collect_urls(self, node: Dict, recursive: bool) -> List[Tuple[str, str]]:
        results = []
        for child in node.get("children", []):
            ctype = child.get("type")
            if ctype == "url":
                results.append((child.get("name", ""), child.get("url", "")))
            elif ctype == "folder" and recursive:
                results.extend(self._collect_urls(child, True))
        return results

    def _parse_txt(self, path: Path) -> List[Tuple[str, str]]:
        lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]
        pairs = []
        i = 0
        while i + 1 < len(lines):
            title = lines[i]
            url = lines[i+1]
            if re.match(r"^https?://", url, re.IGNORECASE):
                pairs.append((title, url))
                i += 2
            else:
                i += 1
        return pairs

    def _find_max_id(self, node: Any) -> int:
        max_id = 0
        if isinstance(node, dict):
            if "id" in node:
                try: max_id = int(node["id"])
                except: pass
            for v in node.values():
                m = self._find_max_id(v)
                if m > max_id: max_id = m
        elif isinstance(node, list):
            for item in node:
                m = self._find_max_id(item)
                if m > max_id: max_id = m
        return max_id

    def _check_folder_exists(self, root_node: Dict, name: str) -> bool:
        for ch in root_node.get("children", []):
            if ch.get("type") == "folder" and ch.get("name") == name:
                return True
        return False


# =============================================================================
# 5. 现代化 GUI 界面 (Modern UI)
# =============================================================================

class LogPanel(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.label = ttk.Label(self, text="运行日志", font=("Microsoft YaHei", 10, "bold"), bootstyle="secondary")
        self.label.pack(anchor="w", pady=(0, 5))
        
        self.text_area = ttk.Text(self, height=8, state="disabled", font=("Consolas", 9))
        self.text_area.pack(fill="both", expand=True, side="left")
        
        self.scrollbar = ttk.Scrollbar(self, command=self.text_area.yview)
        self.scrollbar.pack(side="right", fill="y")
        self.text_area.configure(yscrollcommand=self.scrollbar.set)

    def append(self, msg: str, level: str = "INFO"):
        self.text_area.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        tag = "ERR" if level == "ERROR" else "NRM"
        
        full_msg = f"[{ts}] {msg}\n"
        self.text_area.insert("end", full_msg, tag)
        if level == "ERROR":
            self.text_area.tag_config("ERR", foreground="red")
        
        self.text_area.see("end")
        self.text_area.configure(state="disabled")
        if level == "ERROR":
            logger.error(msg)
        else:
            logger.info(msg)


class MainApp(ttk.Window):
    def __init__(self):
        super().__init__(themename="cosmo", title=APP_TITLE, size=APP_SIZE, resizable=(True, True))
        self.logic = BookmarkManager()
        self._init_ui()

    def _init_ui(self):
        # Header
        header = ttk.Frame(self, padding=20, bootstyle="primary")
        header.pack(fill="x")
        ttk.Label(header, text="🌐 全能书签同步助手 Pro", font=("Microsoft YaHei", 18, "bold"), bootstyle="inverse-primary").pack(side="left")
        ttk.Label(header, text="Edge/Chrome 双向互导 | 智能管理", bootstyle="inverse-primary").pack(side="left", padx=20, pady=(8, 0))

        # Tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=20, pady=15)

        self.tab_export = ttk.Frame(self.notebook, padding=15)
        self.tab_import = ttk.Frame(self.notebook, padding=15)
        
        self.notebook.add(self.tab_export, text=" 📤 导出 (Edge/Chrome -> TXT) ")
        self.notebook.add(self.tab_import, text=" 📥 导入 (TXT -> Edge/Chrome) ")

        self._build_export_tab()
        self._build_import_tab()

        # Log & Status
        self.log_panel = LogPanel(self, padding=20)
        self.log_panel.pack(fill="x", side="bottom")
        
        self.status_var = ttk.StringVar(value="就绪")
        ttk.Label(self, textvariable=self.status_var, bootstyle="secondary", padding=(20, 5)).pack(fill="x", side="bottom")

    def _build_export_tab(self):
        f = self.tab_export
        f.columnconfigure(1, weight=1)

        # 1. 配置区域
        lf = ttk.Labelframe(f, text="导出设置", padding=15)
        lf.pack(fill="x", pady=10)

        # 来源浏览器 (新增功能)
        ttk.Label(lf, text="来源浏览器:").grid(row=0, column=0, sticky="e", padx=5, pady=10)
        self.exp_browser = ttk.StringVar(value="edge")
        b_frame = ttk.Frame(lf)
        b_frame.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(b_frame, text="Microsoft Edge", variable=self.exp_browser, value="edge").pack(side="left", padx=5)
        ttk.Radiobutton(b_frame, text="Google Chrome", variable=self.exp_browser, value="chrome").pack(side="left", padx=5)

        # Profile
        ttk.Label(lf, text="Profile 名称:").grid(row=1, column=0, sticky="e", padx=5, pady=10)
        self.exp_profile = ttk.Entry(lf)
        self.exp_profile.insert(0, "Default")
        self.exp_profile.grid(row=1, column=1, sticky="ew", padx=5)
        ttk.Label(lf, text="(默认为 Default)", bootstyle="secondary").grid(row=1, column=2, sticky="w")

        # Root
        ttk.Label(lf, text="查找位置:").grid(row=2, column=0, sticky="e", padx=5, pady=10)
        self.exp_root = ttk.StringVar(value="bookmark_bar")
        r_frame = ttk.Frame(lf)
        r_frame.grid(row=2, column=1, sticky="w")
        ttk.Radiobutton(r_frame, text="收藏栏", variable=self.exp_root, value="bookmark_bar").pack(side="left", padx=5)
        ttk.Radiobutton(r_frame, text="其他收藏夹", variable=self.exp_root, value="other").pack(side="left", padx=5)

        # Folder
        ttk.Label(lf, text="目标文件夹:").grid(row=3, column=0, sticky="e", padx=5, pady=10)
        self.exp_folder = ttk.Entry(lf)
        self.exp_folder.grid(row=3, column=1, sticky="ew", padx=5)
        
        # Options
        self.exp_recursive = ttk.BooleanVar(value=True)
        ttk.Checkbutton(lf, text="递归包含子文件夹", variable=self.exp_recursive, bootstyle="round-toggle").grid(row=4, column=1, sticky="w", padx=5, pady=10)

        # 2. 按钮区域
        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill="x", pady=10)
        self.btn_export = ttk.Button(btn_frame, text="执行导出", bootstyle="success", width=20, command=self._on_export_click)
        self.btn_export.pack(side="right")
        ttk.Label(f, text="💡 输出位置：./output 目录", bootstyle="info").pack(side="left", padx=5)

    def _build_import_tab(self):
        f = self.tab_import
        f.columnconfigure(1, weight=1)

        # 1. 目标
        lf_target = ttk.Labelframe(f, text="导入目标", padding=15)
        lf_target.pack(fill="x", pady=10)

        ttk.Label(lf_target, text="导入到:").grid(row=0, column=0, sticky="e", padx=5, pady=10)
        self.imp_browser = ttk.StringVar(value="chrome")
        b_frame = ttk.Frame(lf_target)
        b_frame.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(b_frame, text="Google Chrome", variable=self.imp_browser, value="chrome").pack(side="left", padx=5)
        ttk.Radiobutton(b_frame, text="Microsoft Edge", variable=self.imp_browser, value="edge").pack(side="left", padx=5)

        ttk.Label(lf_target, text="Profile:").grid(row=1, column=0, sticky="e", padx=5, pady=10)
        self.imp_profile = ttk.Entry(lf_target)
        self.imp_profile.insert(0, "Default")
        self.imp_profile.grid(row=1, column=1, sticky="ew", padx=5)

        # 2. 文件
        lf_file = ttk.Labelframe(f, text="TXT 数据源", padding=15)
        lf_file.pack(fill="x", pady=10)

        ttk.Label(lf_file, text="文件路径:").grid(row=0, column=0, sticky="e", padx=5, pady=10)
        self.imp_txt_path = ttk.Entry(lf_file)
        self.imp_txt_path.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(lf_file, text="浏览", command=self._select_file, bootstyle="outline").grid(row=0, column=2, padx=5)

        ttk.Label(lf_file, text="新建文件夹名:").grid(row=1, column=0, sticky="e", padx=5, pady=10)
        self.imp_folder_name = ttk.Entry(lf_file)
        self.imp_folder_name.grid(row=1, column=1, sticky="ew", padx=5)

        # 3. 按钮
        btn_frame = ttk.Frame(f)
        btn_frame.pack(fill="x", pady=10)
        self.btn_import = ttk.Button(btn_frame, text="执行导入", bootstyle="danger", width=20, command=self._on_import_click)
        self.btn_import.pack(side="right")
        ttk.Label(f, text="⚠️ 导入前请关闭目标浏览器", bootstyle="warning").pack(side="left")

    # --- Events ---
    def _select_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")])
        if path:
            self.imp_txt_path.delete(0, "end")
            self.imp_txt_path.insert(0, path)
            if not self.imp_folder_name.get():
                self.imp_folder_name.insert(0, Path(path).stem)

    def _on_export_click(self):
        folder = self.exp_folder.get().strip()
        browser = self.exp_browser.get()
        if not folder:
            Messagebox.show_error("请输入要导出的文件夹名称", "缺少参数")
            return

        req = ExportRequest(
            browser=browser,
            profile=self.exp_profile.get().strip(),
            root=self.exp_root.get(),
            folder_name=folder,
            include_subfolders=self.exp_recursive.get()
        )
        self._run_async(self._export_task, req)

    def _export_task(self, req: ExportRequest):
        try:
            self.status_var.set(f"正在从 {req.browser} 导出...")
            self.log_panel.append(f"导出任务: Browser={req.browser}, Folder='{req.folder_name}'")
            
            out_path, count, src = self.logic.export_bookmarks(req)
            
            self.log_panel.append(f"成功导出 {count} 条链接。")
            self.log_panel.append(f"源文件: {src}")
            self.status_var.set("导出成功")
            self.after(0, lambda: Messagebox.show_info(f"导出完成！\n路径：{out_path}", "成功"))
        except Exception as e:
            self.log_panel.append(f"导出中断: {str(e)}", "ERROR")
            self.status_var.set("出错")
            self.after(0, lambda: Messagebox.show_error(str(e), "错误"))

    def _on_import_click(self):
        txt = self.imp_txt_path.get().strip()
        folder = self.imp_folder_name.get().strip()
        if not txt or not Path(txt).exists():
            Messagebox.show_error("请选择有效的 TXT 文件", "文件错误")
            return
        if not folder:
            Messagebox.show_error("请输入目标文件夹名称", "缺少参数")
            return

        if Messagebox.show_question(f"即将导入到 {self.imp_browser.get()}，确认浏览器已关闭？", "确认") != "Yes":
            return

        req = ImportRequest(
            browser=self.imp_browser.get(),
            profile=self.imp_profile.get().strip(),
            root="bookmark_bar",
            folder_name=folder,
            txt_path=Path(txt)
        )
        self._run_async(self._import_task, req)

    def _import_task(self, req: ImportRequest):
        try:
            self.status_var.set(f"正在导入到 {req.browser}...")
            self.log_panel.append(f"导入任务: Browser={req.browser}, Folder='{req.folder_name}'")
            
            folder, count, bm_path, bak_path = self.logic.import_bookmarks(req)
            
            self.log_panel.append(f"导入成功 {count} 条。")
            self.log_panel.append(f"备份文件: {Path(bak_path).name}")
            self.status_var.set("导入完成")
            self.after(0, lambda: Messagebox.show_info(f"导入完成！\n已备份至：{bak_path}", "成功"))
        except Exception as e:
            self.log_panel.append(f"导入中断: {str(e)}", "ERROR")
            self.status_var.set("出错")
            self.after(0, lambda: Messagebox.show_error(str(e), "错误"))

    def _run_async(self, func, *args):
        Thread(target=func, args=args, daemon=True).start()


if __name__ == "__main__":
    app = MainApp()
    app.place_window_center()
    app.mainloop()