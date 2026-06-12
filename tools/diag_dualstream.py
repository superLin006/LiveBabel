"""诊断会议双流崩溃:测试不同方式同时开 麦克风 + loopback 两个输入流。

在 subtitle 环境、项目根跑:
    python tools/diag_dualstream.py
逐个测试,看哪种方式不崩(崩了会直接退出,最后打印的"测试X"就是崩的那个)。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyaudiowpatch as pyaudio


def find_loopback(pa):
    # 用和程序完全一样的 loopback 选择逻辑
    try:
        from livebabel.asr.audio_source_windows import WasapiLoopbackSource
        return WasapiLoopbackSource()._find_loopback_device(pa)
    except Exception:
        for d in pa.get_loopback_device_info_generator():
            return d
    return None


def find_mic(pa):
    # 用和程序完全一样的麦克风选择逻辑(复现真实设备)
    try:
        from livebabel.asr.audio_source_mic import MicrophoneSource
        return MicrophoneSource._pick_input_device(pa)
    except Exception:
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("maxInputChannels", 0) > 0 and "loopback" not in str(d["name"]).lower():
                return d
    return None


def main() -> None:
    pa = pyaudio.PyAudio()
    lb = find_loopback(pa)
    mic = find_mic(pa)
    print(f"loopback: {lb['name']} rate={int(lb['defaultSampleRate'])}")
    print(f"mic:      {mic['name']} rate={int(mic['defaultSampleRate'])}")

    print("\n[测试1] 阻塞模式:同一PyAudio,同时开两个 input stream,各 read 5 次")
    sys.stdout.flush()
    try:
        s1 = pa.open(format=pyaudio.paFloat32, channels=int(lb["maxInputChannels"]),
                     rate=int(lb["defaultSampleRate"]), input=True,
                     input_device_index=lb["index"], frames_per_buffer=1600)
        s2 = pa.open(format=pyaudio.paFloat32, channels=int(mic["maxInputChannels"]),
                     rate=int(mic["defaultSampleRate"]), input=True,
                     input_device_index=mic["index"], frames_per_buffer=1600)
        for _ in range(5):
            s1.read(1600, exception_on_overflow=False)
            s2.read(1600, exception_on_overflow=False)
        s1.close(); s2.close()
        print("  [测试1] OK —— 阻塞双流可行!")
    except Exception as e:
        print("  [测试1] 异常(非崩溃):", e)
    pa.terminate()

    print("\n[测试2] 回调模式:同一PyAudio,两个 input stream 用 callback 各跑 1 秒")
    sys.stdout.flush()
    pa = pyaudio.PyAudio()
    cnt = {"lb": 0, "mic": 0}

    def cb_lb(in_data, n, t, status):
        cnt["lb"] += 1
        return (None, pyaudio.paContinue)

    def cb_mic(in_data, n, t, status):
        cnt["mic"] += 1
        return (None, pyaudio.paContinue)

    try:
        s1 = pa.open(format=pyaudio.paFloat32, channels=int(lb["maxInputChannels"]),
                     rate=int(lb["defaultSampleRate"]), input=True,
                     input_device_index=lb["index"], frames_per_buffer=1600,
                     stream_callback=cb_lb)
        s2 = pa.open(format=pyaudio.paFloat32, channels=int(mic["maxInputChannels"]),
                     rate=int(mic["defaultSampleRate"]), input=True,
                     input_device_index=mic["index"], frames_per_buffer=1600,
                     stream_callback=cb_mic)
        s1.start_stream(); s2.start_stream()
        time.sleep(1.0)
        s1.stop_stream(); s2.stop_stream(); s1.close(); s2.close()
        print(f"  [测试2] OK —— 回调双流可行!lb 回调 {cnt['lb']} 次,mic 回调 {cnt['mic']} 次")
    except Exception as e:
        print("  [测试2] 异常(非崩溃):", e)
    pa.terminate()

    print("\n[测试3] 两个 sherpa GPU 引擎在两个线程并发推理(最可疑)")
    sys.stdout.flush()
    try:
        import threading
        import numpy as np
        from livebabel.asr.vad_engine import VadTwoPassAsr
        from livebabel.paths import FIRST_DIR, SECOND_DIR
        a1 = VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
        a2 = VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
        print(f"  两引擎 provider: {a1.provider} / {a2.provider}")
        sys.stdout.flush()
        noise = (np.random.randn(1600) * 0.05).astype(np.float32)

        def feed(asr, tag):
            try:
                for _ in range(30):
                    list(asr.feed(noise))
                print(f"  [{tag}] 推理 30 次完成")
            except Exception as e:
                print(f"  [{tag}] 异常:", e)

        t1 = threading.Thread(target=feed, args=(a1, "引擎A"))
        t2 = threading.Thread(target=feed, args=(a2, "引擎B"))
        t1.start(); t2.start(); t1.join(); t2.join()
        print("  [测试3] OK —— 两个 GPU 引擎并发推理不崩!")
    except Exception as e:
        print("  [测试3] 异常(非崩溃):", e)

    print("\n全部测试跑完(没中途崩退就说明都不崩;崩了则最后那行 [测试X] 是元凶)。")


if __name__ == "__main__":
    main()
