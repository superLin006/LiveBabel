"""音频设备诊断:列出所有输出/ loopback 设备和当前默认输出,排查抓错设备的问题。

在 Windows 上(激活 subtitle 环境)运行:
    python diag_audio.py
把输出整个贴回来。
"""
import pyaudiowpatch as p

pa = p.PyAudio()
wasapi = pa.get_host_api_info_by_type(p.paWASAPI)
def_out_idx = wasapi["defaultOutputDevice"]
def_out = pa.get_device_info_by_index(def_out_idx)

print("=" * 70)
print(f"当前默认输出设备: index={def_out_idx}  name={def_out['name']!r}")
print("=" * 70)

print("\n--- 所有 WASAPI 输出设备(普通,非 loopback)---")
for i in range(pa.get_device_count()):
    d = pa.get_device_info_by_index(i)
    if d.get("hostApi") == wasapi["index"] and d.get("maxOutputChannels", 0) > 0:
        mark = "  <== 默认" if i == def_out_idx else ""
        print(f"  index={d['index']:>3} | {d['name']}{mark}")

print("\n--- 所有 loopback 设备 ---")
for d in pa.get_loopback_device_info_generator():
    print(f"  index={d['index']:>3} | {d['name']} | in={d['maxInputChannels']} "
          f"| rate={int(d['defaultSampleRate'])}")

print("\n--- get_default_wasapi_loopback() 返回 ---")
try:
    lb = pa.get_default_wasapi_loopback()
    print(f"  index={lb['index']} | {lb['name']}" if lb else "  None")
except Exception as e:
    print("  报错:", e)

pa.terminate()
