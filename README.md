# 广告视频自动化混剪工具

把原始视频素材丢进去，自动完成二倍速、调色、拼接、去重、滤镜、贴纸、字幕、配音，一键生成竖屏广告短视频。

## 快速开始

### 1. 准备素材

把文件放到对应文件夹即可：

| 文件类型 | 放到哪里 | 说明 |
|----------|----------|------|
| 原始视频 | `raw_clips/` | MP4格式，竖屏最佳，**数量不限**，有几段用几段 |
| 去重视频 | `dedup_videos/` | MP4格式，每段60-90秒，**数量不限**，用于叠加去重 |
| 字幕文件 | `subtitles/caption.srt` | SRT格式，**自己手动切割好**，效果最好 |
| 配音文案 | `subtitles/sub1.txt` | 纯文本，TTS会朗读这段文字 |
| 贴纸 | `sticker_lib/` | 透明背景PNG，程序随机选4张贴四角 |
| 字体 | `font_lib/` | TTF格式中文字体，程序随机选1个 |
| 滤镜 | `filter_lib/` | TXT格式FFmpeg滤镜链，程序随机选2个 |

### 2. 修改配置

打开 `config.yaml`，改输出文件夹名：
```yaml
output_subdir: "毕节七星关区"   # 成品会放在 output/毕节七星关区/ 下面
```

### 3. 运行

```bash
python main.py
```

成品在 `output/你的文件夹名/final_video_with_tts.mp4`。

---

## 环境要求

- **Windows 10/11**
- **Python 3.10+**
- **FFmpeg**（需支持 libass 字幕烧录，推荐 gyan.dev essentials_build）
- **NVIDIA显卡**（可选，驱动610.00+自动启用硬件加速，没有也能用CPU编码）

## 安装

```bash
# 1. 安装FFmpeg，把bin目录加入系统环境变量
# 验证：ffmpeg -version

# 2. 安装Python依赖
pip install edge-tts pyyaml

# 3. 把素材放进对应文件夹，运行
python main.py
```

## 程序做了什么

```
原始视频 → 二倍速 → 统一调色/分辨率 → 裁剪对齐 → 拼接
                                          ↓
去重视频 → 切片 → 多层低透明度叠加（防平台查重）
                                          ↓
随机滤镜（2个低透明度混合）+ 随机贴纸（4张贴四角）
                                          ↓
烧录字幕 + 替换TTS配音 → 成品MP4
```

每次运行随机抽取不同的音色、字体、滤镜、贴纸组合，避免重复。

## 输出文件

```
output/你的文件夹名/
├── final_video_with_tts.mp4    # 成品视频（1080x1920竖屏）
└── 随机参数记录.txt             # 本次用了什么音色/字体/滤镜/贴纸
```

## 配置说明（config.yaml）

```yaml
# 输出
output_subdir: "毕节七星关区"    # 输出子文件夹名

# 视频
speed_rate: 2.0                  # 倍速
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
```

## 注意事项

- **字幕自己切**：推荐手动准备 `caption.srt`，自己控制每句显示时机，效果比自动切割好
- **配音文案直接写**：`sub1.txt` 里写完整的广告文案，程序直接朗读，不做任何替换
- **硬件加速**：有N卡且驱动够新会自动启用，速度快5-10倍；驱动不够自动降级CPU编码
- **去重缓存**：去重视频切片会缓存，相同参数第二次运行秒级复用
- **贴纸要透明**：必须是带Alpha通道的PNG，否则会有白色方块

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
└── logs/                    # 运行日志
```

## 许可证

MIT License
