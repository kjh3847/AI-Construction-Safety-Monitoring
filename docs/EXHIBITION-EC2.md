# 현장지킴 전시용 EC2 배포

기존 메인 모니터 EC2에 `safety-exhibition`이라는 별도 Compose 프로젝트를 띄웁니다. 전시 영상과 이벤트는 독립 볼륨에 저장합니다. 전시 페이지는 기존 HTTPS 주소의 `/exhibition/`에서 열고, 전시 컨테이너는 로컬 포트 8081을 사용합니다.

## 1. 전시용 브랜치 업로드

GitHub에 아직 전시용 브랜치가 없으면, Windows PowerShell에서 전시용 복제본으로 이동한 뒤 실행합니다.

```powershell
git push -u origin feature/exhibition
```

## 2. EC2에서 전시용 앱 실행

메인 모니터 EC2 콘솔 터미널에서 실행합니다. 기존 프로젝트 경로 밖에서 작업합니다.

```bash
git clone --depth 1 --branch feature/exhibition https://github.com/kjh3847/AI-Construction-Safety-Monitoring.git ~/safety-exhibition
cd ~/safety-exhibition
mkdir -p models
model_file="$(find . -type f -name '2026_09_21_best.pt' -print -quit)"
test -n "$model_file" && install -m 0644 "$model_file" models/best.pt
```

아래 블록은 첫 실행 때 전시 운영 키를 생성합니다. 생성 후 재배포할 때는 기존 `.env`를 사용합니다.

```bash
cd ~/safety-exhibition
if [ ! -e .env ]; then
  (umask 077
   printf 'PUBLIC_APP_URL=https://safety-monitor-2026.duckdns.org\nEXHIBITION_MODEL_FILE=./models/best.pt\nEXHIBITION_OPERATOR_KEY=%s\n' "$(openssl rand -hex 32)" > .env)
fi
test -s models/best.pt && docker compose -f compose.exhibition.yaml up -d --build
docker compose -f compose.exhibition.yaml ps
curl -fsS --retry 8 --retry-connrefused http://127.0.0.1:8081/api/runtime
```

응답에서 `exhibition`이 `true`이고 `yolo_state`가 `not_loaded` 또는 `loaded`인지 확인합니다. 모델은 첫 분석에서 메모리에 올라갑니다. 운영 키는 EC2에서 `grep '^EXHIBITION_OPERATOR_KEY=' .env`로 확인할 수 있습니다.

## 3. 기존 HTTPS 프록시에 전시 경로 추가

현재 HTTPS를 처리하는 프록시에 해당 블록을 하나만 추가합니다. 호스트의 공개 포트는 기존 HTTPS 443을 사용합니다. `PUBLIC_APP_URL`에는 스킴과 호스트만 입력합니다.

**Caddy**를 쓴다면 기존 도메인 블록의 기본 catch-all `handle` 앞에 추가합니다. 기본 백엔드가 블록 없는 `reverse_proxy`라면 같이 둘 수 있습니다.

```caddy
redir /exhibition /exhibition/ 308
handle_path /exhibition/* {
    reverse_proxy 127.0.0.1:8081
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

**Nginx**를 쓴다면 기존 HTTPS `server` 블록에 추가합니다.

```nginx
location = /exhibition {
    return 308 /exhibition/;
}
location ^~ /exhibition/ {
    proxy_pass http://127.0.0.1:8081/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Origin $http_origin;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;
    proxy_read_timeout 75s;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

`https://safety-monitor-2026.duckdns.org/exhibition/api/runtime`에 접근해 전시 모드 응답을 확인한 뒤, 브라우저에서 `/exhibition/`과 기존 홈페이지를 각각 엽니다.

## 4. 전시 영상과 라이브 채널 연결

- 관람객은 전시 주소에서 로그인 없이 화면과 이벤트를 봅니다.
- 영상 교체는 오른쪽 위 **운영 설정**을 열고 키를 입력한 다음, CAM4와 CAM5에서 각각 **영상 업로드**를 누릅니다. 채널당 최대 300 MiB입니다. H.264 MP4를 권장합니다.
- CAM4에는 공사장 영상을, CAM5에는 비공사장 비교 영상을 넣습니다. 두 파일 모두 같은 YOLO 모델로 분석합니다. 모델이 잘못 그린 박스도 영상에서 확인할 수 있습니다.
- 업로드가 끝나면 영상 분석이 시작되어 반복 재생됩니다. Compose를 다시 켜도 저장한 영상으로 자동 시작합니다. 교체할 때는 해당 채널에서 **중단**을 눌러 종료를 기다린 뒤 업로드합니다.
- CAM1~3은 **운영 설정 → 스트림 주소 → 등록 및 연결**을 사용합니다. EC2 컨테이너가 직접 읽을 수 있는 RTSP(S) 또는 HTTP(S) 스트림 주소를 넣습니다. 휴대폰이 행사장 Wi-Fi의 사설 IP만 갖는 경우 EC2가 직접 접속할 수 없으므로, EC2에서 읽을 수 있는 스트리밍 중계 주소가 필요합니다.

전시를 끝낼 때는 전시 사이트 경로를 제거하고 기존 HTTPS 프록시 설정을 검사한 뒤 다시 읽힙니다. 앱을 내릴 때는 `cd ~/safety-exhibition && docker compose -f compose.exhibition.yaml stop`을 사용합니다.
