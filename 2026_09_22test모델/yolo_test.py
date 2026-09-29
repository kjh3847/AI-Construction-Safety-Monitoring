"""Windows YOLO tester. Install: py -m pip install -U ultralytics opencv-python"""
from pathlib import Path
from datetime import datetime
import math
import os
import shutil
import tempfile
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

MODEL_PATH = Path(__file__).resolve().parent / "2026_09_21_best.pt"
CONFIDENCE = 0.4
WINDOW = "YOLO result - ESC / Q to exit"
IMAGES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VIDEOS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v", ".webm"}


def unused_path(folder, stem, suffix):
    """Return a path that will not overwrite an earlier result."""
    candidate = folder / f"{stem}{suffix}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{number}{suffix}"
        number += 1
    return candidate


def show_frame(cv2, frame):
    # Resize only the preview; save results at full resolution.
    height, width = frame.shape[:2]
    scale = min(1200 / width, 800 / height, 1.0)
    preview = cv2.resize(frame, (max(1, int(width * scale)),
                                 max(1, int(height * scale))))
    cv2.imshow(WINDOW, preview)


def stopped(cv2, delay=20):
    key = cv2.waitKey(delay) & 0xFF
    if key in (27, ord("q"), ord("Q")):
        return True
    try:
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def test_image(cv2, np, model, source, output, confidence):
    # imdecode + Python file IO safely handles Korean Windows filenames.
    frame = cv2.imdecode(np.frombuffer(source.read_bytes(), dtype=np.uint8),
                         cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError("이미지를 읽을 수 없습니다. 다른 이미지로 시도해 주세요.")
    annotated = model.predict(source=frame, conf=confidence, verbose=False)[0].plot()
    destination = unused_path(output, source.stem + "_result", ".jpg")
    ok, encoded = cv2.imencode(".jpg", annotated)
    if not ok:
        raise RuntimeError("결과 이미지 변환에 실패했습니다.")
    destination.write_bytes(encoded.tobytes())
    print(f"저장 완료: {destination}", flush=True)
    show_frame(cv2, annotated)
    # Show the result briefly, then continue automatically to the next file.
    interrupted = stopped(cv2, 500)
    return destination, interrupted


def test_video(cv2, model, source, output, confidence):
    # Use ASCII relative filenames for video backends; shutil handles Unicode.
    # A temporary input copy needs extra free disk space.
    previous_cwd = Path.cwd()
    count = 0
    interrupted = False
    total = 0
    with tempfile.TemporaryDirectory(prefix="yolo_test_") as temporary:
        stage = Path(temporary).resolve()
        print("동영상을 임시 작업 폴더로 복사 중입니다...", flush=True)
        shutil.copyfile(source, stage / ("input" + source.suffix.lower()))
        capture = None
        writer = None
        try:
            os.chdir(stage)
            capture = cv2.VideoCapture("input" + source.suffix.lower())
            if not capture.isOpened():
                raise RuntimeError("동영상을 열 수 없습니다. MP4(H.264) 파일로 시도해 주세요.")
            fps = capture.get(cv2.CAP_PROP_FPS)
            if not math.isfinite(fps) or fps <= 0:
                fps = 30.0
                print("원본 FPS를 읽지 못해 30 FPS로 저장합니다.", flush=True)
            raw_total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            total = int(raw_total) if math.isfinite(raw_total) and raw_total > 0 else 0
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("동영상의 첫 프레임을 읽을 수 없습니다.")
            height, width = frame.shape[:2]
            # Common encoders require even dimensions; pad rather than crop.
            size = (width + width % 2, height + height % 2)
            temp_name = "result.mp4"
            writer = cv2.VideoWriter(temp_name, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
            if not writer.isOpened():
                writer.release()
                temp_name = "result.avi"
                writer = cv2.VideoWriter(temp_name, cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
            if not writer.isOpened():
                raise RuntimeError("영상 저장 코덱을 사용할 수 없습니다.")
            while ok:
                annotated = model.predict(source=frame, conf=confidence, verbose=False)[0].plot()
                annotated = cv2.copyMakeBorder(annotated, 0, size[1] - height,
                                              0, size[0] - width, cv2.BORDER_CONSTANT)
                writer.write(annotated)
                count += 1
                show_frame(cv2, annotated)
                if count == 1 or count % 30 == 0:
                    print(f"처리한 프레임: {count} / {total or '?'}", flush=True)
                if stopped(cv2, 1):
                    interrupted = True
                    break
                ok, frame = capture.read()
            writer.release()
            writer = None
            capture.release()
            capture = None
            short_read = total > 0 and count < total
            suffix = "_partial" if interrupted or short_read else "_result"
            destination = unused_path(output, source.stem + suffix, Path(temp_name).suffix)
            # Check that the encoder produced a readable file.
            check = cv2.VideoCapture(temp_name)
            try:
                readable, _ = check.read()
            finally:
                check.release()
            if not readable:
                raise RuntimeError("저장한 동영상을 읽을 수 없습니다. 코덱을 확인해 주세요.")
            shutil.copyfile(stage / temp_name, destination)
            state = "중단 지점까지 저장했습니다." if interrupted else "결과 영상을 저장했습니다."
            if short_read and not interrupted:
                state = "원본의 예상 프레임 수보다 일찍 읽기가 끝났습니다. 저장 영상을 확인해 주세요."
            return destination, interrupted, count, state
        finally:
            if writer is not None:
                writer.release()
            if capture is not None:
                capture.release()
            os.chdir(previous_cwd)


def main():
    root = tk.Tk()
    root.withdraw()
    cv2 = None
    output = None
    try:
        source_names = filedialog.askopenfilenames(
            parent=root, title="테스트할 이미지 또는 동영상을 여러 개 선택하세요",
            initialdir=str(MODEL_PATH.parent) if MODEL_PATH.parent.exists() else str(Path.home()),
            filetypes=[("이미지 및 동영상", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.mp4 *.avi *.mov *.mkv *.wmv *.m4v *.webm"),
                       ("모든 파일", "*.*")])
        if not source_names:
            return
        sources = [Path(name).resolve() for name in source_names]
        unsupported = [item.name for item in sources if item.suffix.lower() not in IMAGES | VIDEOS]
        if unsupported:
            raise RuntimeError("지원하지 않는 형식이 포함되어 있습니다.\n" + "\n".join(unsupported))
        confidence = simpledialog.askfloat("탐지 신뢰도", "0~1 사이 값 (기본 0.4)\n낮추면 더 많은 객체를 탐지합니다.",
                                           initialvalue=CONFIDENCE, minvalue=0.0, maxvalue=1.0, parent=root)
        if confidence is None:
            return
        if not MODEL_PATH.is_file():
            raise FileNotFoundError(f"모델 파일이 없습니다.\n{MODEL_PATH}\n프로그램의 MODEL_PATH를 확인해 주세요.")
        try:
            import cv2
            import numpy as np
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("필요한 패키지를 설치해 주세요.\n명령 프롬프트에서:\npy -m pip install -U ultralytics opencv-python\n\n" + str(exc)) from exc
        output = Path(__file__).resolve().parent / "results" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output.mkdir(parents=True, exist_ok=False)
        print(f"모델을 불러오는 중: {MODEL_PATH}\n첫 추론은 시간이 걸릴 수 있습니다.", flush=True)
        model = YOLO(str(MODEL_PATH))
        completed = []
        interrupted = False
        total_files = len(sources)
        for index, source in enumerate(sources, start=1):
            print(f"\n[{index}/{total_files}] 처리 중: {source}", flush=True)
            if source.suffix.lower() in IMAGES:
                destination, interrupted = test_image(
                    cv2, np, model, source, output, confidence)
                completed.append(f"이미지: {source.name} → {destination.name}")
            else:
                destination, interrupted, frame_count, state = test_video(
                    cv2, model, source, output, confidence)
                completed.append(
                    f"영상: {source.name} → {destination.name} ({frame_count} 프레임, {state})")
            if interrupted:
                print("사용자가 작업을 중단했습니다.", flush=True)
                break
        cv2.destroyAllWindows()
        status = "사용자 요청으로 중단했습니다." if interrupted else "선택한 파일 처리가 완료되었습니다."
        summary = (f"{status}\n\n완료: {len(completed)} / {total_files}개\n"
                   f"결과 폴더:\n{output}\n\n" + "\n".join(completed))
        print("\n" + summary, flush=True)
        messagebox.showinfo("완료", summary, parent=root)
    except Exception as exc:
        details = traceback.format_exc()
        print(details, flush=True)
        if output is not None:
            try:
                (output / "error.txt").write_text(details, encoding="utf-8")
            except OSError:
                pass
        messagebox.showerror("실행 오류", str(exc), parent=root)
    finally:
        if cv2 is not None:
            cv2.destroyAllWindows()
        root.destroy()


if __name__ == "__main__":
    main()
