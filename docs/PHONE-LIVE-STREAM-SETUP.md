# 스마트폰 3대 송출 설정

현재 공개 AWS 송출 서버는 배포하지 않았다. 아래의 `stream.example.com`은 형식 설명용이며 실제 접속 주소가 아니다.
서버 운영자가 공인 DNS/TLS와 인증정보를 준비한 후 연결한다. 같은 Wi-Fi일 필요는 없다.
스마트폰이 공용 서버로 연결을 시작하는 구조이므로 휴대폰의 사설 IP나 공유기 포트포워딩을 입력하지 않는다.
기존 직접 IP Camera 방식은 서버에서 휴대폰 주소까지 연결할 수 있는 LAN/VPN 등 경로가 필요하다.

## 운영자가 카메라별 연결정보 발급

프로젝트 루트에서 실제 서버 DNS를 사용한다. 기존 파일이 있으면 덮어쓰지 않고 중단한다.

```powershell
.\.venv\Scripts\python.exe tools/issue_stream_credentials.py --host stream.example.com
```

- `.env.media`: 카메라별 게시 계정 3개, 내부 AI 읽기/WebRTC 게이트웨이/관리 계정. 서버 전용.
- `.local-run/phone-live-connections.json`: CAM별 `connection_url`. 로컬 파일에서 해당 휴대폰에 해당 URL만 전달한다.
- 파일은 Git 제외 및 소유자 접근 권한으로 생성한다. URL에는 비밀번호가 포함되므로 화면 공유/로그/이슈/메일 본문에 붙여넣지 않는다.
- 이미 발급한 정보는 기존 파일을 사용한다. 교체 시 새 파일명으로 생성하고 서버 설정을 안전하게 교체한 뒤 해당 송출을 재연결한다.

| 휴대폰 | 대시보드 | 스트림 경로 | 입력할 값 |
|---|---|---|---|
| 1 | CAM-01 | cam01 | JSON의 CAM-01.connection_url |
| 2 | CAM-02 | cam02 | JSON의 CAM-02.connection_url |
| 3 | CAM-03 | cam03 | JSON의 CAM-03.connection_url |

주소 형식은 `rtmps://stream.example.com:1936/cam01?user=사용자&pass=비밀번호`이다.
발급 스크립트가 인코딩까지 처리한다. Larix의 별도 Login/Password 인증 입력란은 비운다.
이 프로젝트는 URL 쿼리 인증을 사용한다. 카메라 계정으로 다른 경로에 게시하거나 영상을 읽을 수 없다.
[MediaMTX 공식 인증 규격](https://mediamtx.org/docs/features/authentication).

한 대만 연결해도 된다. 나머지 타일은 연결 안 됨으로 유지되며 각각 따로 연결·재연결한다.

## Android

1. Google Play의 Softvelum **Larix Broadcaster**를 설치하고 카메라 권한을 허용한다. 음성은 이 관제 화면에서 사용하지 않으므로 가능하면 Video only로 설정한다.
2. 톱니바퀴 Settings → **Connections → New connection**을 연다. 이름은 CAM-01처럼 지정한다.
3. URL에 발급받은 `connection_url` 전체를 붙여넣고 저장한다. 이름만 바꿔 다른 카메라의 URL을 재사용하지 않는다.
4. Video 또는 Capture/encoding 영상 설정에서 **1280×720, 15 FPS, H.264/AVC**, 가능하면 Baseline, 키프레임 1초, B-frame 없음으로 시작한다. 초기 비트레이트는 1.5~2 Mbps로 설정하고 현장 업로드 속도에 맞춰 조정한다.
5. 앱 버전의 연결 재시도/자동 재연결 옵션을 확인하고 활성화한다. 별도 스위치가 없는 버전도 있으므로 비행기 모드 ON/OFF 후 같은 CAM으로 복구되는지 실제로 시험한다.
6. 휴대폰 설정에서 Larix의 배터리 사용 제한을 해제하고 화면을 켜 둔다. 지속 송출 중에는 발열·충전 상태를 확인한다.
7. 프리뷰로 돌아와 빨간 방송 시작 버튼을 누른다. 송출 비트레이트와 연결 상태가 증가하는지 확인한다.
8. 웹사이트에 로그인해 해당 CAM의 **영상 연결됨 / 최근 수신 / 표시 FPS**를 확인한다. AI 상태는 영상 연결과 별도다.

Connections/New connection과 방송 시작 흐름은 [Softvelum Android 설정 문서](https://blog.wmspanel.com/2015/08/larix-broadcaster-live-streaming-setup.html) 기준이다.
공식 연결 문서는 오래된 화면도 포함한다. 현재 앱의 언어·버전에 따른 세부 메뉴 위치와 자동 재연결 동작은 실물 확인이 남아 있다.

## iPhone

1. App Store에서 Softvelum Larix Broadcaster를 설치하고 카메라 권한을 허용한다.
2. Settings → Connections에서 새 연결을 만들고 해당 CAM의 전체 URL을 입력한다.
3. Settings → Capture and encoding → Video 계열 설정에서 H.264, 720p, 15 FPS를 선택한다. 앱 버전에 따라 이름/배치가 다를 수 있다.
4. Android와 같은 송출 설정으로 시작하고 한 대씩 웹사이트에서 확인한다.
5. 영상 송출 중 앱을 전면에 두고 화면을 잠그지 않는다. iOS의 음성 백그라운드 송출 지원을 카메라 영상 백그라운드 지원으로 간주하지 않는다. 앱 전환·잠금 후 연결을 다시 확인한다.
6. 장시간 충전 송출 시 발열로 FPS가 낮아지거나 종료될 수 있으므로 거치대 통풍, 화면 밝기, 배터리 상태를 점검한다.

연결 흐름: [Softvelum iOS 설정](https://blog.wmspanel.com/2015/10/larix-broadcaster-ios-broadcasting-setup.html).
RTMPS/H.264, 적응 비트레이트, SEI/NTP 옵션 지원: [공식 iOS 기능](https://softvelum.com/larix/ios/).
SEI 시간 삽입은 유료 기능이며 이 프로젝트에는 해당 송신 시각 파서가 아직 없다.
옵션을 켜는 것만으로 카메라 간 촬영 시간이 검증되는 것은 아니다.

## 영상 품질과 추적

H.265 또는 B-frame이 포함된 H.264는 브라우저 호환 문제가 생길 수 있다.
초기에는 H.264 Baseline으로 확인한다. [MediaMTX 브라우저 코덱 안내](https://mediamtx.org/docs/features/webrtc-specific-features).
ABR(적응 비트레이트)은 연결이 약할 때 사용 가능하지만 실제 기기의 재연결·화질 변화와 AI 성능을 함께 확인해야 한다.
화면의 지터 버퍼 ms는 휴대폰 촬영부터 화면까지의 전체 지연이 아니다.

Push 입력의 RTP 시각은 같은 영상과 텍스트의 매칭에만 사용한다. 서로 다른 폰의 촬영 시각은 현재 미동기화 상태다.
카메라별 Local/Global ID와 이벤트는 유지하되, Push 카메라 간 자동 동일인 연결은 보수적으로 비활성화한다.
공통 촬영 시계 검증/시간 파서 구현과 실제 인물 평가가 후속 작업이다.

## 문제 해결

| 증상 | 확인/조치 |
|---|---|
| Connection Failed | 공개 DNS가 실제 서버를 가리키는지, 인터넷 연결과 TCP 1936 허용 여부 확인 |
| Connection Refused | MediaMTX 실행, Docker 포트, 서버 방화벽, AWS 보안 그룹 확인 |
| Authentication Failed | 해당 CAM URL 전체 재복사, 경로/사용자/비밀번호 확인. 다른 CAM 계정은 거부됨 |
| TLS/Certificate Error | 폰 시각, 인증서 만료, DNS와 SAN 일치, 전체 체인 확인. 인증서 검증 해제로 우회하지 않음 |
| Camera Offline | 폰 방송 시작 여부, 수신 바이트/최근 시각 확인. AI 시작 버튼은 폰 송출 버튼이 아님 |
| 수신 중인데 검은 화면 | H.264/B-frame, WebRTC UDP/TCP 8189, 서버 공개 ICE 주소 확인 |
| 영상은 보이지만 AI 없음 | best.pt 경로와 클래스, 감지 시작, 모델 로드 오류 확인. 영상은 AI와 독립 재생 |
| 반복 단절 | 업로드 대역폭, 비트레이트, 발열, 배터리 제한 확인. 재접속 중 다른 채널 재생 확인 |
| Wi-Fi 성공/LTE 실패 | 통신망의 포트 제한 확인. 웹 시청 실패는 TCP ICE 대안 검토; 필요 시 인증 TURN 별도 구축 |
| Wi-Fi↔LTE 전환 | 기존 소켓 단절은 정상일 수 있음. 송출 앱 재시도와 같은 CAM 복구 확인 |
| 영상은 정상/위치 텍스트 없음 | AI 결과의 RTP 시각이 재생 프레임과 일치할 때만 표시. 미일치/브라우저 미지원이면 위치 텍스트 숨김 |

## PRISM 및 SRT

PRISM은 보조 후보이며 실제 앱/이 서버 조합의 호환성은 미검증이다. Custom RTMP 설정이 있는 버전에서는
발급 파일의 `prism_server`와 `prism_stream_key`를 각각 서버/키에 입력해 시험한다.
RTMPS 및 키의 쿼리 문자열 보존이 되는지 먼저 한 채널로 확인하고, 실패하면 Larix를 사용한다.
SRT는 현재 비활성화다. 추가 시 전용 인증 역할, streamid 경로 제한, 암호화 passphrase, UDP 방화벽과 패킷 손실 테스트를 함께 구현해야 한다.

## 실제 현장 인수 테스트 (미완료)

CAM-01 한 대 → CAM-02/03 추가 → 서로 다른 Wi-Fi/LTE/5G → 한 대 송출 중지/재연결 →
시청 로그아웃/인증 거부 → 실제 YOLO 보호구 검출 → 촬영 시각 및 ReID 평가 → 24시간 시험 순서로 수행한다.
현재 네이티브 Windows FFmpeg 시험은 실제 Larix 송출 또는 AWS 배포 완료를 의미하지 않는다.
