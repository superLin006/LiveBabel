"""麦克风诊断:列出所有音频设备,定位默认输入设备,尝试打开并读一小段。

在 Windows 的 subtitle 环境里跑(项目根目录):
    python tools/diag_mic.py
把完整输出发回,用于排查"麦克风无效"。
"""

from __future__ import annotations

import sys


def main() -> None:
    try:
        import pyaudiowpatch as pyaudio
    except Exception as e:
        print("[FAIL] 无法导入 pyaudiowpatch:", e)
        print("       请在 subtitle 环境 pip install pyaudiowpatch")
        return

    import numpy as np
    pa = pyaudio.PyAudio()

    # 1) host API 概况
    print("=" * 60)
    print("Host APIs:")
    wasapi_idx = None
    for i in range(pa.get_host_api_count()):
        h = pa.get_host_api_info_by_index(i)
        print(f"  [{i}] {h['name']}  设备数={h['deviceCount']} "
              f"默认输入={h.get('defaultInputDevice')} 默认输出={h.get('defaultOutputDevice')}")
        if h["type"] == pyaudio.paWASAPI:
            wasapi_idx = i

    # 2) 所有"可输入"的设备
    print("=" * 60)
    print("所有输入设备(maxInputChannels>0):")
    inputs = []
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d.get("maxInputChannels", 0) > 0:
            inputs.append(d)
            print(f"  index={d['index']:>2}  hostApi={d['hostApi']}  "
                  f"ch={int(d['maxInputChannels'])}  rate={int(d['defaultSampleRate'])}  "
                  f"name={d['name']}")
    if not inputs:
        print("  (没有任何输入设备!可能麦克风未接/被禁用/无权限)")

    # 3) 默认输入设备
    print("=" * 60)
    try:
        di = pa.get_default_input_device_info()
        print(f"默认输入设备: index={di['index']} name={di['name']} "
              f"hostApi={di['hostApi']} ch={int(di['maxInputChannels'])} "
              f"rate={int(di['defaultSampleRate'])}")
    except Exception as e:
        print("[FAIL] 取默认输入设备失败:", e)
        di = None

    # 4) WASAPI 默认输入
    if wasapi_idx is not None:
        w = pa.get_host_api_info_by_index(wasapi_idx)
        print(f"WASAPI 默认输入设备 index = {w.get('defaultInputDevice')}")

    # 5) 尝试打开默认输入设备读 0.5s
    print("=" * 60)
    if di is not None:
        for ch in (1, int(di["maxInputChannels"])):
            try:
                rate = int(di["defaultSampleRate"])
                fpb = int(rate * 0.1)
                st = pa.open(format=pyaudio.paFloat32, channels=ch, rate=rate,
                             frames_per_buffer=fpb, input=True,
                             input_device_index=di["index"])
                raw = st.read(fpb, exception_on_overflow=False)
                a = np.frombuffer(raw, dtype=np.float32)
                lvl = float(np.sqrt(np.mean(a**2))) if len(a) else 0.0
                print(f"[OK] 打开成功 ch={ch} rate={rate};读到 {len(a)} 样本,"
                      f"音量RMS={lvl:.4f}  ({'有声音' if lvl>1e-3 else '静音/没说话'})")
                st.stop_stream(); st.close()
                break
            except Exception as e:
                print(f"[FAIL] 打开默认输入设备失败 ch={ch}: {e}")

    pa.terminate()
    print("=" * 60)
    print("诊断结束。把以上全部输出发回。")


if __name__ == "__main__":
    main()
