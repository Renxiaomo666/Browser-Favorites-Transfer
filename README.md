# 🔖 Bookmark Tool Pro (全能书签同步助手)

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![UI](https://img.shields.io/badge/UI-ttkbootstrap-orange)

一款基于 Python 开发的现代化书签管理工具，支持 **Microsoft Edge** 和 **Google Chrome** 之间的书签双向互导。拥有美观的图形界面，支持自动备份与智能清理，让跨浏览器书签同步变得简单安全。

## ✨ 主要功能 (Features)

* **双向互导**：支持 Edge ↔ Chrome 的双向书签迁移。
* **格式通用**：采用中间态 `.txt` 文件（标题+URL），方便编辑和分享。
* **安全备份**：导入前自动生成 `.bak` 备份文件，防止数据丢失。
* **智能清理**：自动检测并清理超过 7 天的旧备份文件，节省空间。
* **现代化 UI**：基于 `ttkbootstrap` 的扁平化界面，支持日志实时显示。
* **灵活配置**：支持自定义 Profile、根目录位置（收藏栏/其他）、文件夹递归导出。

## 🛠️ 安装说明 (Installation)

### 1. 克隆项目
```bash
git clone [https://github.com/Renxiaomo666/edge_value.git](https://github.com/Renxiaomo666/edge_value.git)
cd edge_value

安装依赖：
pip install -r requirements.txt
