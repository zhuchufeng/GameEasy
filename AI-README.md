# AI-README — 洛克王国减负小助手 v1.2

## 概述

Windows 洛克王国游戏全功能自动化工具。Python 3.10 + PySide6 + YOLO (ultralytics/ONNX)。

**唯一输入方案**: Interception 内核驱动（PS/2 扫描码注入），需要管理员权限。

## 快速开始

```bash
pip install -r requirements.txt
python -m roco_auto   # 自动提权到管理员
```

## 目录结构

```
├── roco_auto/                 # 主 Python 包
│   ├── __main__.py            # 入口 (DPI感知+自动提权)
│   ├── app.py                 # QApplication
│   ├── core/
│   │   ├── game_automation.py     # 总协调器 (配置+后端+5个Runner)
│   │   ├── mode_runner.py         # ModeRunner ABC + RunnerContext
│   │   ├── input_backend.py       # 输入后端接口
│   │   ├── uiohook_backend.py     # Interception 内核驱动后端 (不动!)
│   │   ├── interception_controller.py  # Interception DLL 封装 (不动!)
│   │   ├── hotkey_manager.py      # 全局热键 (GetAsyncKeyState轮询) (不动!)
│   │   ├── visitor_engine.py      # 互访炫彩 8阶段状态机 (不动!)
│   │   ├── box_check.py           # 宝箱检测 YOLO 状态机
│   │   ├── yolo_detector.py       # YOLO ONNX 推理 (旧, 已弃用)
│   │   ├── screen_capture.py      # mss 屏幕截图
│   │   ├── window_finder.py       # Win32 窗口枚举
│   │   ├── config_manager.py      # JSON 配置持久化
│   │   ├── serial_client.py       # 串口通信 QThread
│   │   ├── serial_protocol.py     # 串口协议 {CMD}\n
│   │   ├── anti_detection.py      # 反检测 (随机延迟/人类节奏)
│   │   ├── mouse_trajectory.py    # 贝塞尔鼠标轨迹
│   │   ├── port_discovery.py      # USB VID/PID Arduino发现
│   │   └── runners/
│   │       ├── battle_runner.py   # 自动战斗
│   │       ├── skip_runner.py     # 跳过剧情 (ultralytics YOLO) (不动!)
│   │       ├── mine_runner.py     # 采矿切宠
│   │       ├── release_runner.py  # 一键放生 (x0,y0)+(x30,y30)网格 (不动!)
│   │       └── throw_runner.py    # 自动丢球
│   ├── ui/
│   │   ├── main_window.py         # 主窗口 8页侧边栏
│   │   ├── game_page.py           # 5个功能页面 + 浮窗
│   │   ├── box_check_page.py      # 宝箱检测页
│   │   ├── visitor_page.py        # 互访炫彩页 (双窗口+5模型) (不动!)
│   │   ├── serial_manager.py      # 串口管理
│   │   ├── region_selector.py     # 区域框选
│   │   └── hotkey_capture.py      # 热键捕获控件 (松开即捕获) (不动!)
│   └── data/saved_config.json     # 配置持久化
├── models/
│   ├── skip/skip_model.onnx       # 跳过剧情 (yolo11)
│   ├── visitor/*.onnx             # 互访炫彩 5阶段模型
│   ├── colorful.onnx              # 小地图 PT/HB 检测
│   ├── boxcheck.onnx              # 宝箱检测
│   └── boxcheck_seg.onnx          # 宝箱检测(分割)
├── Arduino固件/
│   ├── roco_firmware_v1.ino       # 原版固件 (Keyboard+Mouse+MouseTo)
│   └── roco_firmware_v2_hid.ino   # HID-Project 版固件
├── interception.dll               # Interception 驱动 DLL
└── requirements.txt
```

## 核心设计原则

### 输入系统 (禁止修改)
- 键盘: Interception 枚举设备→PS/2扫描码注入
- 鼠标: Interception 绝对坐标(0-65535)映射
- 以上代码**已验证稳定，任何修改都会导致失效**

### 全局热键 (禁止修改)
- GetAsyncKeyState 后台轮询, 30ms 间隔
- 鼠标侧键 = 全局紧急停止 (只设标志位, 不碰Interception)
- F8 = 可自定义全局停止热键
- 热键捕获: 松开所有键后自动捕获

### 互访炫彩 (禁止修改)
- 8阶段: ENTER→REQUEST→ACCEPT→WORLD_CHECK→MINIMAP→EXIT→循环
- 双窗口切换: SendInput+SetForegroundWindow
- 每阶段独立 YOLO 模型

### 放生 (禁止修改)
- (x0,y0)+(x30,y30) 两点法自动计算 dx,dy
- 第1阶段: 点选30个宠物槽
- 第2阶段: 确认4次(150ms间隔)+最终确认

### 跳过剧情 (禁止修改)
- ultralytics YOLO 推理
- cutscene: 点击→等confirm出现→点击
- dialog_1: 连按1×3

## 重要注意事项

1. **管理员权限是必须的** — 程序自动提权, Interception 驱动需要
2. **重启电脑** — Interception 注入异常时第一解决方案
3. **代码冻结** — 标记"(不动!)"的文件已稳定, 不要改
4. **模型放在固定路径** — models/ 目录随程序分发
5. **DPI感知** — SetProcessDpiAwareness(2) 已在入口设置
