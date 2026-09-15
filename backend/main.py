from pathlib import Path
from threading import Lock
import time

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from ultralytics import YOLO

app = FastAPI()

# main.py와 같은 폴더에 있는 파일 사용
BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "best.pt"
VIDEO_PATH = BASE_DIR / "test.mp4"

# 학습된 모델 불러오기
model = YOLO(str(MODEL_PATH))

# 첫 테스트에서는 영상 창 하나만 사용
stream_lock = Lock()


@app.get("/")
def home():
    return {"message": "YOLO 분석 서버 실행 중"}


@app.get("/video")
def video():
    if not stream_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="기존 분석 영상 탭을 닫고 다시 열어 주세요.",
        )

    cap = cv2.VideoCapture(str(VIDEO_PATH))

    if not cap.isOpened():
        cap.release()
        stream_lock.release()
        raise HTTPException(
            status_code=400,
            detail="test.mp4를 열 수 없습니다. 파일을 확인해 주세요.",
        )

    fps = cap.get(cv2.CAP_PROP_FPS)
    interval = 1 / fps if 0 < fps <= 240 else 1 / 25

    def generate_frames():
        try:
            while True:
                started = time.monotonic()
                success, frame = cap.read()

                if not success:
                    break

                # CPU로 영상 한 장씩 분석
                result = model.predict(
                    source=frame,
                    imgsz=640,
                    conf=0.4,
                    device="cpu",
                    verbose=False,
                )[0]

                # 탐지 박스와 이름 그리기
                annotated = result.plot()

                success, buffer = cv2.imencode(".jpg", annotated)

                if not success:
                    continue

                # 분석 이미지를 연속해서 브라우저로 전달
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buffer.tobytes()
                    + b"\r\n"
                )

                elapsed = time.monotonic() - started
                time.sleep(max(0, interval - elapsed))

        finally:
            cap.release()
            stream_lock.release()

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )