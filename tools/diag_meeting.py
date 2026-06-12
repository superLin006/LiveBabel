"""1:1 复现会议双流崩溃:直接用真实 MeetingPipeline 跑几秒,带 Qt 事件循环。

subtitle 环境、项目根跑(会真的抓麦克风+系统声音):
    python tools/diag_meeting.py
跑约 8 秒后正常应打印转录条数;若中途崩退,最后的 [step] 就是崩的位置。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from livebabel.meeting.recorder import MeetingRecorder
    from livebabel.meeting.pipeline import MeetingPipeline

    print("[step] 建 QApplication"); sys.stdout.flush()
    app = QApplication(sys.argv)

    rec = MeetingRecorder()
    print("[step] 建 MeetingPipeline(mic+loopback 双流)"); sys.stdout.flush()
    pipe = MeetingPipeline(rec, on_update=lambda: None,
                           use_mic=True, use_loopback=True)

    print("[step] pipeline.start() —— 真实双流采集+GPU推理"); sys.stdout.flush()
    pipe.start()

    def stop_and_report():
        print("[step] 停止"); sys.stdout.flush()
        pipe.stop()
        segs = rec.segments()
        print(f"[result] 跑完没崩!转录 {len(segs)} 条")
        for u in segs[:5]:
            print("   ", u.speaker, u.text)
        app.quit()

    # 跑 8 秒(期间对着麦克风说话 + 放点系统声音)
    QTimer.singleShot(8000, stop_and_report)
    print("[step] 进入事件循环,跑 8 秒(请说话+放声音)…"); sys.stdout.flush()
    app.exec()


if __name__ == "__main__":
    main()
