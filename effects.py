"""
特效合成模块
构建 FFmpeg filter_complex 滤镜链：去重叠加 → 滤镜混合 → 贴纸叠加 → 字幕烧录
这是整个项目最复杂的部分，输入流索引必须精确管理
"""
from config import config
from logger import logger


def build_dedup_chain(dedup_clips: list, start_input_idx: int, base_stream: str) -> tuple:
    """
    构建多层去重 blend 叠加链
    每一层用 blend=all_mode=overlay:all_opacity=低透明度 叠加
    :param dedup_clips: 去重切片路径列表
    :param start_input_idx: 起始输入流索引（去重图层从这个索引开始）
    :param base_stream: 基础流标签，如 "[0:v]"
    :return: (额外的-i参数列表, 滤镜链片段列表, 最终输出标签, 下一个可用输入索引)
    """
    extra_inputs = []
    filter_segments = []
    current_stream = base_stream
    num_layers = len(dedup_clips)

    for layer_idx, dedup_clip in enumerate(dedup_clips):
        extra_inputs.extend(["-i", dedup_clip])
        dedup_input_idx = start_input_idx + layer_idx
        # 最后一层输出标签用 [dedup_final]，中间层用 [dedup_N]
        out_label = f"[dedup_{layer_idx}]" if layer_idx < num_layers - 1 else "[dedup_final]"
        filter_segments.append(
            f"{current_stream}[{dedup_input_idx}:v]blend=all_mode=overlay:all_opacity={config.DEDUP_ALPHA}{out_label}"
        )
        current_stream = out_label

    next_input_idx = start_input_idx + num_layers
    logger.info(f"已构建{num_layers}层去重叠加滤镜")
    return extra_inputs, filter_segments, current_stream, next_input_idx


def build_filter_chain(selected_filters: list, base_stream: str) -> tuple:
    """
    构建随机滤镜 split+blend 低透明度混合链
    原理：split复制一份画面，对副本应用滤镜，再用blend以2%透明度和原画面混合
    :param selected_filters: 选中的滤镜列表 [(文件名, 滤镜参数字符串), ...]
    :param base_stream: 基础流标签
    :return: (滤镜链片段列表, 最终输出标签)
    """
    if not selected_filters:
        return [], base_stream

    # 把所有滤镜参数用逗号连接（FFmpeg滤镜链语法）
    all_filter_params = ",".join([f[1] for f in selected_filters])

    filter_segments = [
        # split 复制一份：[orig]保留原画面，[filt]应用滤镜
        f"{base_stream}split[orig][filt]",
        # 对 [filt] 应用所有滤镜
        f"[filt]{all_filter_params}[filt_out]",
        # 用 blend 以2%透明度把滤镜效果混合回原画面
        f"[orig][filt_out]blend=all_mode=overlay:all_opacity={config.FILTER_BLEND_OPACITY}[filtered]"
    ]

    logger.info(f"已应用{len(selected_filters)}个随机滤镜组合（{config.FILTER_BLEND_OPACITY*100:.0f}%低透明度混合）")
    return filter_segments, "[filtered]"


def build_sticker_chain(sticker_paths: list, corner_positions: list, start_input_idx: int, base_stream: str) -> tuple:
    """
    构建四张贴纸 overlay 叠加链
    每张贴纸先 scale 缩放 + colorchannelmixer 调透明度，然后 overlay 到对应角落
    注意：overlay 绝对不能加 shortest=1，否则会导致 frame=0 黑屏
    :param sticker_paths: 贴纸路径列表（4张）
    :param corner_positions: 四角位置配置 [(x, y, 路径), ...]
    :param start_input_idx: 起始输入流索引
    :param base_stream: 基础流标签
    :return: (额外的-i参数列表, 滤镜链片段列表, 最终输出标签, 下一个可用输入索引)
    """
    extra_inputs = []
    filter_segments = []
    current_stream = base_stream
    sticker_start_idx = start_input_idx

    # 第一步：预处理每张贴纸（缩放+透明度），同时添加 -i 输入
    for idx, (x_pos, y_pos, stk_path) in enumerate(corner_positions):
        input_idx = sticker_start_idx + idx
        extra_inputs.extend(["-i", stk_path])
        filter_segments.append(
            f"[{input_idx}:v]scale=iw*{config.STICKER_SCALE}:ih*{config.STICKER_SCALE},"
            f"colorchannelmixer=aa={config.STICKER_ALPHA}[stk{input_idx}]"
        )

    # 第二步：逐层 overlay 叠加四张贴纸到四个角落
    for idx in range(4):
        input_idx = sticker_start_idx + idx
        x_pos, y_pos, _ = corner_positions[idx]
        out_label = f"[tmp{input_idx}]"
        filter_segments.append(
            f"{current_stream}[stk{input_idx}]overlay=x={x_pos}:y={y_pos}{out_label}"
        )
        current_stream = out_label

    next_input_idx = sticker_start_idx + 4
    return extra_inputs, filter_segments, current_stream, next_input_idx


def build_final_filter_complex(
    base_video: str,
    tts_audio: str,
    dedup_clips: list,
    selected_filters: list,
    sticker_paths: list,
    subtitle_filter: str
) -> tuple:
    """
    构建完整的 filter_complex 滤镜链 + 输入参数
    顺序：去重叠加 → 滤镜混合 → 贴纸叠加 → 字幕烧录
    输入索引分配：0=主视频, 1=TTS音频, 2~N=去重图层, N+1~=贴纸
    :param base_video: 基础拼接视频路径
    :param tts_audio: TTS音频路径
    :param dedup_clips: 去重切片路径列表
    :param selected_filters: 选中的滤镜列表
    :param sticker_paths: 贴纸路径列表（4张）
    :param subtitle_filter: 已转义好的 subtitles 滤镜字符串
    :return: (完整的input_cmds列表, 完整的filter_complex字符串)
    """
    # 基础输入：0=主视频, 1=TTS音频
    input_cmds = ["ffmpeg", "-y", "-i", base_video, "-i", tts_audio]
    all_filter_segments = []

    # 四角位置配置（左上、右上、左下、右下）
    corner_positions = [
        ("10", "10", sticker_paths[0]),
        ("W-w-10", "10", sticker_paths[1]),
        ("10", "H-h-10", sticker_paths[2]),
        ("W-w-10", "H-h-10", sticker_paths[3]),
    ]

    # 第1层：去重叠加（输入索引从2开始）
    dedup_inputs, dedup_segments, current_stream, next_idx = build_dedup_chain(
        dedup_clips, start_input_idx=2, base_stream="[0:v]"
    )
    input_cmds.extend(dedup_inputs)
    all_filter_segments.extend(dedup_segments)

    # 第2层：随机滤镜混合
    filter_segments, current_stream = build_filter_chain(selected_filters, current_stream)
    all_filter_segments.extend(filter_segments)

    # 第3层：四张贴纸叠加（输入索引接在去重图层后面）
    sticker_inputs, sticker_segments, current_stream, next_idx = build_sticker_chain(
        sticker_paths, corner_positions, start_input_idx=next_idx, base_stream=current_stream
    )
    input_cmds.extend(sticker_inputs)
    all_filter_segments.extend(sticker_segments)

    # 第4层：烧录字幕（最后一步，输出 [out_video]）
    all_filter_segments.append(f"{current_stream}{subtitle_filter}[out_video]")

    # 用分号连接所有滤镜片段
    full_filter_complex = ";".join(all_filter_segments)

    return input_cmds, full_filter_complex
