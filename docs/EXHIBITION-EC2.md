# 전시용 QR 카메라와 S3 시연 영상

작업 브랜치는 `feature/exhibition-qr-s3`입니다. 전시 앱은 `safety-exhibition-qr-s3` Compose 프로젝트와 별도 영상·이벤트 볼륨을 사용합니다. 새 앱은 EC2 내부 `127.0.0.1:8082`에서, 관객은 기존 HTTPS 호스트의 `/exhibition/`에서 접속합니다.

| 화면 | 용도 |
|---|---|
| CAM1~3 | 채널별 QR → 휴대폰 카메라 권한 허용 → 실시간 AI 표시. 종료·백그라운드 이동·연결 끊김 후 QR 복귀. 체험 영상과 이벤트는 저장하지 않습니다. |
| CAM4 | 건설장비 착용 · S3의 `착용.mp4` |
| CAM5 | 건설장비 미착용 · S3의 `미착용.mp4` |

## 1. EC2에 새 버전 실행

메인 모니터 EC2의 콘솔 터미널에서 실행합니다. 첫 블록은 모델과 전시 설정을 준비합니다. 이미 이 폴더에 클론했다면 `git clone` 대신 그 폴더에서 `git pull --ff-only`를 실행하세요.

```bash
git clone --depth 1 --branch feature/exhibition-qr-s3 https://github.com/kjh3847/AI-Construction-Safety-Monitoring.git ~/safety-exhibition-qr-s3
cd ~/safety-exhibition-qr-s3
mkdir -p models exhibition-videos
model_file="$(find . -type f -name '2026_09_21_best.pt' -print -quit)"
test -n "$model_file" && install -m 0644 "$model_file" models/best.pt
if [ ! -e .env ]; then
  (umask 077
   printf 'PUBLIC_APP_URL=https://safety-monitor-2026.duckdns.org\nEXHIBITION_STREAM_HOST=safety-monitor-2026.duckdns.org\nEXHIBITION_MODEL_FILE=./models/best.pt\nEXHIBITION_OPERATOR_KEY=%s\nEXHIBITION_RELAY_KEY=%s\n' "$(openssl rand -hex 32)" "$(openssl rand -hex 32)" > .env)
fi
```

두 번째 블록은 앱을 실행하고 전시 모드를 확인합니다.

```bash
cd ~/safety-exhibition-qr-s3
test -s models/best.pt && docker compose -f compose.exhibition.yaml up -d --build
docker compose -f compose.exhibition.yaml ps
curl -fsS --retry 8 --retry-connrefused http://127.0.0.1:8082/api/runtime
```

응답에서 `exhibition`과 `interactive`가 둘 다 `true`인지 확인합니다. `yolo_state`는 첫 분석 전에는 `not_loaded`일 수 있습니다.

## 2. HTTPS와 휴대폰 영상 연결

EC2 보안 그룹에서 관객 휴대폰이 접속하는 네트워크에 **UDP 8190**을 허용합니다. 행사장 Wi-Fi에서 UDP가 막힐 때를 대비해 **TCP 8190**도 사용합니다. 모바일 데이터로 체험하는 경우 해당 관객 접속 범위를 포함해야 합니다. 8190은 WebRTC 미디어 포트이고, QR 페이지와 신호 교환은 기존 HTTPS 443을 사용합니다.

현재 HTTPS 프록시의 기존 도메인 설정에 전시 경로를 아래와 같이 연결합니다. `/exhibition/`이 이미 있으면 해당 전시 경로의 업스트림만 8082로 바꿉니다. `PUBLIC_APP_URL`과 `EXHIBITION_STREAM_HOST`를 바꿀 경우 전자는 HTTPS 주소 전체, 후자는 호스트 이름만 넣습니다.

**Caddy** 사이트 블록

```caddy
redir /exhibition /exhibition/ 308
handle_path /exhibition/* {
    reverse_proxy 127.0.0.1:8082
}
```

`sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy`

**Nginx** HTTPS server 블록

```nginx
location = /exhibition {
    return 308 /exhibition/;
}
location ^~ /exhibition/ {
    proxy_pass http://127.0.0.1:8082/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Origin $http_origin;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 75s;
}
```

`sudo nginx -t && sudo systemctl reload nginx`

[전시 화면](https://safety-monitor-2026.duckdns.org/exhibition/)을 열고 CAM1의 QR을 Android Chrome 또는 iPhone Safari로 찍습니다. **카메라 시작**을 누르고 권한을 허용합니다. 전시장에 원본 영상과 AI 박스가 표시되는지 확인한 뒤 **카메라 종료**를 눌러 QR이 돌아오는지 확인합니다.

## 3. S3에 MP4 두 개 올리고 EC2에 내려받기

S3 콘솔에서 같은 버킷 또는 같은 폴더에 `착용.mp4`, `미착용.mp4`를 업로드합니다. EC2에 연결된 IAM 역할에는 두 객체에 대한 `s3:GetObject` 권한이 필요합니다. AWS CLI가 설치된 EC2에서 버킷 주소를 바꿔 실행합니다.

```bash
cd ~/safety-exhibition-qr-s3
bash deploy/sync-exhibition-videos.sh 's3://내-버킷-이름'
```

버킷 안 폴더에 저장했다면 `s3://내-버킷-이름/폴더이름`을 넣습니다. 동기화가 끝나면 전시 화면에서 **운영 설정**을 열고 CAM4, CAM5의 **감지·녹화 시작**을 각각 누릅니다. 운영 키는 EC2 터미널에서 `grep '^EXHIBITION_OPERATOR_KEY=' .env`로 확인합니다. 파일을 교체할 때는 CAM4·5을 중단한 다음 동기화 명령을 다시 실행합니다.

## 4. 전시 직전 확인과 복귀

- 시연 영상은 브라우저에서 재생 가능한 H.264 MP4를 사용합니다. 720p 정도로 준비하면 대역폭을 아낄 수 있습니다.
- 관객 휴대폰 3대와 CAM4·5을 동시에 켜고 **운영 설정**의 CPU 사용률과 채널별 분석 FPS를 봅니다. 영상은 재생되는데 박스 갱신만 느리면 `EXHIBITION_ANALYSIS_FPS=4`부터 확인합니다. 기본 추론 크기는 `512`이며, 멀리 있는 보호구가 잘 안 보이면 `EXHIBITION_INFERENCE_SIZE=640`에서 속도와 함께 비교합니다. 환경값 변경 후 Compose의 `up -d`를 다시 실행합니다.
- 기존 전시 앱으로 돌아갈 때는 HTTPS의 전시 경로를 기존 8081로 돌리고 프록시 설정을 검사한 뒤 다시 읽힙니다. 새 전시 앱은 해당 폴더에서 `docker compose -f compose.exhibition.yaml stop`으로 중단합니다.
