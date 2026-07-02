"""会议模式的平台分发:按 OS 选采集后端(Windows=pyaudiowpatch / macOS=sounddevice)。

meeting_window 只调这里的 make_pipeline()/has_microphone()/has_system_audio(),
不直接 import 平台相关模块,平台判断集中一处。
"""

from __future__ import annotations

import sys

IS_MAC = sys.platform == "darwin"


def make_pipeline(recorder, on_update, use_mic: bool = True, use_loopback: bool = True,
                  mic_label: str = "我"):
    """创建会议管线:macOS 用 MacMeetingPipeline,其余用 MeetingPipeline。
    mic_label:麦克风一路的说话人标签(线下仅麦克风时传"现场")。"""
    if IS_MAC:
        from livebabel.meeting.pipeline_mac import MacMeetingPipeline
        return MacMeetingPipeline(recorder, on_update, use_mic=use_mic,
                                  use_loopback=use_loopback, mic_label=mic_label)
    from livebabel.meeting.pipeline import MeetingPipeline
    return MeetingPipeline(recorder, on_update, use_mic=use_mic,
                           use_loopback=use_loopback, mic_label=mic_label)


def has_microphone() -> bool:
    if IS_MAC:
        from livebabel.asr.audio_source_mac import MacMicrophoneSource
        return MacMicrophoneSource.has_microphone()
    from livebabel.asr.audio_source_mic import MicrophoneSource
    return MicrophoneSource.has_microphone()


def has_system_audio() -> bool:
    """能否抓系统声音。Windows 看有无 loopback(基本都有);macOS 看是否装了 BlackHole。"""
    if IS_MAC:
        from livebabel.asr.audio_source_mac import has_blackhole
        return has_blackhole()
    return True   # Windows WASAPI loopback 系统级支持,视为总可用


def system_audio_hint() -> str:
    """系统声不可用时给用户的引导文案(按平台)。"""
    if IS_MAC:
        return ("未检测到 BlackHole 虚拟声卡,无法录系统声音。\n"
                "请安装 BlackHole(brew install blackhole-2ch),并在「音频 MIDI 设置」里\n"
                "建「多输出设备」同时含扬声器和 BlackHole,把系统输出切到它。")
    return "未检测到可用的系统声音采集设备(loopback)。"
