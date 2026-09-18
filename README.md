# 广告视频自动化混剪工具

面向 Windows 的竖屏广告视频自动生成流水线。程序从 Excel 读取地点，依据固定事实生成并校验文案，生成带真实时间戳的 AI 旁白，再从人物出镜区间规划画面，同时输出快速预览 MP4 和可继续编辑的剪映草稿。

> 当前项目用于学习和流程验证。正式商用前，请自行确认 TTS、字体、贴纸、滤镜和视频素材的授权范围，并遵守发布平台规则。

## 快速开始

### 1. 准备素材

把文件放到对应文件夹即可：

| 文件类型 | 放到哪里 | 说明 |
|----------|----------|------|
| 原始视频 | `raw_clips/` | MP4格式，竖屏最佳，**数量不限**，有几段用几段 |
| 去重视频 | `dedup_videos/` | MP4格式，每段60-90秒，**数量不限**，用于叠加去重 |
| 地点库 | `地区.xlsx` | 表头为“省份 / 州市 / 县区”，程序只读 |
| 固定事实 | `facts.yaml` | 从 `facts.example.yaml` 复制后填写；AI 只能围绕这里的事实改写 |
| 贴纸 | `sticker_lib/` | 透明背景PNG，程序随机选4张贴四角 |
| 字体 | `font_lib/` | TTF格式中文字体，程序随机选1个 |
| 滤镜 | `filter_lib/` | TXT格式FFmpeg滤镜链，程序随机选2个 |

### 2. 配置密钥与参数

先创建本机配置文件（这些文件已被 Git 忽略）：

```powershell
Copy-Item .env.example .env
Copy-Item facts.example.yaml facts.yaml
Copy-Item subtitles/sub1.example.txt subtitles/sub1.txt
```

在 `.env` 中填写密钥：

```dotenv
DEEPSEEK_API_KEY=替换为新密钥
```

旧密钥如曾写入配置文件，请先在服务商控制台撤销并重新生成。

然后在 `config.yaml` 中确认地点文件与数据行。相对路径均以项目目录为基准：
```yaml
base_dir: "."
locations_file: "地区.xlsx"
location_row: 1
```

### 3. 运行

```bash
python main.py
```

同名任务默认不会覆盖。测试重跑时显式使用：

```bash
python main.py --overwrite
```

也可以临时指定任务名：

```bash
python main.py --job 贵阳市南明区 --overwrite
```

选择 Excel 中第 3 条地点：

```bash
python main.py --location-row 3 --overwrite
```

跳过 AI 文案生成、直接测试指定文案：

```bash
python main.py --script "完整测试文案" --overwrite
```

人物模型尚未安装时，可用完整素材调试其余链路：

```bash
python main.py --no-person-detection --overwrite
```

成品在 `output/你的文件夹名/final_video_with_tts.mp4`。

同时生成可编辑剪映草稿：

```text
output/你的文件夹名/jianying_draft/editable/
```

草稿固定为 1080×1920、30fps，主视频、旁白、逐句字幕、本地贴纸、原生滤镜和低透明度去重素材均位于独立可编辑轨道。新版剪映不做自动点击导出；请在剪映专业版中打开草稿后自行预览和导出。

当前草稿格式已在 Windows 剪映专业版 10.7.0 中完成人工打开验证；其他版本仍建议先运行兼容性检查并手动预览。视觉变化功能不保证规避平台检测，发布时请遵守对应平台规则。

扫描现有贴纸、字体、滤镜和音色库：

```bash
python main.py --scan-resources
```

清单生成到 `resource_manifest.json`。第一版花字项会明确显示“未配置”，不会写入未经验证的在线资源 ID。

批量处理 Excel 中全部地点：

```bash
python main.py --all-locations
```

批量中断后继续：

```bash
python main.py --all-locations --resume
```

程序会逐步检查已有产物，从最早失效步骤继续。批量结果写入 `output/batch_report.json` 和 `output/batch_report.csv`。

检查某个任务的剪映草稿结构：

```bash
python main.py --jianying-compat-test --job 示例任务
```

结构通过时状态为 `structure_passed_manual_open_pending`。这表示文件、画布、轨道和素材路径检查通过；仍需在剪映 10.7.0 中实际打开一次，才算完成版本兼容确认。

---

## 环境要求

- **Windows 10/11**
- **Python 3.10**
- **FFmpeg**（需支持 libass 字幕烧录，推荐 gyan.dev essentials_build）
- **NVIDIA显卡**（可选，驱动610.00+自动启用硬件加速，没有也能用CPU编码）

## 安装

```bash
# 1. 安装FFmpeg，把bin目录加入系统环境变量
# 验证：ffmpeg -version

# 2. 安装基础依赖
python -m pip install -r requirements.txt

# 启用 YOLO 人物出镜检测
python -m pip install -r requirements-vision.txt

# 启用可编辑剪映草稿输出
python -m pip install -r requirements-jianying.txt

# 3. 把素材放进对应文件夹，运行
python main.py
```

开发测试：

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## 程序做了什么

```
Excel地点 + facts.yaml → 生成并校验文案 → Edge TTS真实时间戳 → SRT
                                          ↓
原始视频 → YOLO人物区间 → 2倍速优先/最低1倍速 → 等比例竖屏裁切
                                          ↓
辅助视频 → 切片 → 多层低透明度叠加（形成视觉版本差异）
                                          ↓
随机滤镜（2个低透明度混合）+ 随机贴纸（4张贴四角）
                                          ↓
烧录字幕 + 替换TTS配音 → 成品MP4
                                          ↓
主视频/旁白/字幕/贴纸/滤镜/去重层 → 可编辑剪映草稿
```

人物源时长足以覆盖旁白的两倍时保持 2.0 倍速；不足时在 1.0–2.0 倍之间自动计算速度；1.0 倍速仍不足就终止并报告缺少秒数，不复用片段。每次运行仍随机抽取不同的音色、字体、滤镜和贴纸组合。

## 输出文件

```
output/你的文件夹名/
├── final_video_with_tts.mp4       # 快速预览成片（1080x1920竖屏）
├── jianying_compatibility.json    # 草稿结构检查结果
├── jianying_draft/
│   └── editable/                  # 可编辑剪映草稿
└── 随机参数记录.txt                # 本次用了什么音色/字体/滤镜/贴纸
```

每个任务的独立中间文件与状态位于：

```text
temp/jobs/任务名/
├── status.json                 # 当前步骤、已完成步骤和失败原因
├── checkpoint.json             # 断点续跑所需上下文
├── tts_audio.mp3
├── auto_subtitle.srt
├── ad_script.txt              # 已校验的本次广告文案
├── clip_plan.json             # 人物区间、实际倍速和裁切计划
└── 其他中间文件
```

失败时会保留有用的诊断文件并清除零字节残留；使用 `--overwrite` 只会清理所选任务对应的临时目录和输出目录。

## 配置说明（config.yaml）

```yaml
# 输出
output_subdir: "示例任务"        # 输出子文件夹名

# 视频
preferred_speed: 2.0             # 素材充足时的首选倍速
minimum_speed: 1.0               # 最低倍速；仍不足就报错
video_encoder: "h264_nvenc"      # libx264(CPU) 或 h264_nvenc(N卡加速)
x264_crf: 23                     # CPU编码画质（越小越清晰）
nvenc_preset: "p4"               # N卡编码速度 p1(快)~p7(慢)
nvenc_cq: 23                     # N卡编码画质

# 贴纸
sticker_alpha: 0.08              # 贴纸透明度
sticker_scale: 0.05              # 贴纸大小
sticker_count: 4                 # 贴纸数量

# 去重
dedup_alpha: 0.03                # 每层去重视频透明度

# 滤镜
num_random_filters: 2            # 随机滤镜数量
filter_blend_opacity: 0.02       # 滤镜强度（2%很淡）

# TTS
tts_max_retries: 3               # 网络失败重试次数

# 字幕
subtitle_max_chars_per_line: 12  # 每行最多字符数，每帧最多两行
subtitle_down_ratio: 0.235       # 累计下移23.5%（先15%，再相对下降10%）
subtitle_font_size: 15           # 字号
```

## 注意事项

- **字幕来自真实语音时间戳**：程序读取 Edge TTS 的 WordBoundary，不再按总时长平均分配
- **最多两行字幕**：预计显示三行以上时优先让 DeepSeek 按语义重新断句；结果必须完整保留原文，否则自动使用本地拆分
- **人物检测**：默认使用轻量 YOLO 模型，只选含人物的区间；首次运行可能需要下载模型
- **素材不足**：最低降到 1.0 倍速后仍不足会明确报错，不会重复人物片段
- **TTS用途**：当前 Edge TTS 适合学习测试；正式投放前请自行确认语音服务的商业使用条款
- **硬件加速**：有N卡且驱动够新会自动启用，速度快5-10倍；驱动不够自动降级CPU编码
- **去重缓存**：去重视频切片会缓存，相同参数第二次运行秒级复用
- **其他缓存**：TTS音频/时间戳、FFprobe媒体信息和人物检测区间都会按源文件与参数缓存
- **贴纸要透明**：必须是带Alpha通道的PNG，否则会有白色方块
- **草稿去重轨道**：每个去重切片是一条独立视频轨道，默认透明度3%并使用“叠加”混合模式
- **公开仓库不含素材**：原始视频、去重视频、贴纸、字体、地点表、业务事实和模型权重需要在本机准备

## 项目结构

```
ad_auto/
├── main.py                  # 运行入口
├── config.yaml              # 改参数在这里
├── config.py                # 配置读取
├── pipeline.py              # 主流程
├── video_processor.py       # 视频处理
├── effects.py               # 特效合成
├── tts.py                   # 语音合成
├── subtitle.py              # 字幕处理
├── location_loader.py       # Excel 地点读取
├── copywriter.py            # 事实库、文案生成和校验
├── person_detector.py       # YOLO人物区间检测
├── clip_planner.py          # 旁白时长与动态倍速规划
├── facts.yaml               # 固定事实库
├── facts.example.yaml       # 可公开提交的事实库示例
├── libraries.py             # 随机库
├── output_manager.py        # 输出管理
├── cache_manager.py         # 切片缓存
├── logger.py                # 日志
├── utils.py                 # 工具函数
├── raw_clips/               # ← 原始视频放这里
├── dedup_videos/            # ← 去重视频放这里
├── sticker_lib/             # ← 贴纸放这里
├── font_lib/                # ← 字体放这里
├── filter_lib/              # ← 滤镜放这里
├── voice_lib/               # 音色列表
├── subtitles/               # ← 字幕(caption.srt)和文案(sub1.txt)放这里
├── output/                  # 成品输出
├── temp/                    # 临时文件
├── logs/                    # 运行日志
├── tests/                   # 单元与流水线测试
└── .github/workflows/       # GitHub Actions（Python 3.10）
```

## 许可证

[MIT License](LICENSE)
