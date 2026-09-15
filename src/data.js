export const cameras = [
  { id: 'CAM-01', name: 'A동 작업 구역', location: '1층 · 철근 작업', image: '/demo-detection.png', workers: 2 },
  { id: 'CAM-02', name: '자재 반입 구역', location: '현장 출입구', image: null, workers: null },
  { id: 'CAM-03', name: 'B동 작업 구역', location: '2층 · 골조 작업', image: null, workers: null },
];
export const initialEvents = [
  { id: 'EV-003', time: '2026-09-15T10:42:18', camera: 'CAM-01', equipment: '안전모', worker: '작업자 03', reviewed: false },
  { id: 'EV-002', time: '2026-09-15T10:35:04', camera: 'CAM-01', equipment: '안전조끼', worker: '작업자 02', reviewed: false },
  { id: 'EV-001', time: '2026-09-15T09:58:21', camera: 'CAM-01', equipment: '안전모', worker: '작업자 01', reviewed: true },
];
// FastAPI를 연결할 때 이 파일의 예시 데이터 대신 API 응답을 사용하세요.
// 이벤트: { id, time: ISO 날짜 문자열, camera, equipment, worker, reviewed }
// 미착용 의심 이벤트와 현재 프레임의 착용 상태는 서로 별도 데이터입니다.
