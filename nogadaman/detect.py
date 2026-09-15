from ultralytics import YOLO

model = YOLO("weight/best.pt")

results = model.predict(
    source="test/test.jpg",
    conf=0.4,
    save=True
)

print("탐지 완료")