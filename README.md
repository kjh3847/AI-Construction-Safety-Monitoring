# AI Construction Safety Monitoring System

YOLO 기반으로 공사현장 CCTV 영상에서 작업자의 안전복장 착용 여부를 감지하고,
미착용 발생 시 관리자 대시보드에 로그를 저장하는 캡스톤 디자인 프로젝트입니다.

---

## 프로젝트 개요

공사현장 CCTV 영상을 기반으로 작업자를 탐지하고,
안전모 및 안전조끼 착용 여부를 AI가 자동으로 판별합니다.

미착용자가 감지되면 해당 시점의 이미지와 감지 정보를 저장하고,
관리자는 웹 대시보드에서 위반 내역을 확인할 수 있습니다.

---

## 주요 기능

- CCTV / 영상 기반 작업자 탐지
- 안전모 착용 여부 감지
- 안전조끼 착용 여부 감지
- 안전모 미착용 감지
- 안전조끼 미착용 감지
- 위반 발생 시간 및 CCTV 정보 저장
- 위반 이미지 캡처 저장
- 관리자 대시보드에서 위반 로그 조회
- AWS 서버 배포

---

## AI 탐지 클래스

| Class | Description |
|---|---|
| Hardhat | 안전모 착용 |
| NO-Hardhat | 안전모 미착용 |
| Safety Vest | 안전조끼 착용 |
| NO-Safety Vest | 안전조끼 미착용 |
| Person | 작업자 |

---

## 기술 스택

### AI
- Python
- Ultralytics YOLO
- OpenCV
- PyTorch

### Backend
- FastAPI
- Python

### Frontend
- React

### Database
- PostgreSQL

### Cloud
- AWS EC2
- AWS S3
- Docker

---

## 시스템 구조

```text
CCTV / Video
      ↓
   OpenCV
      ↓
     YOLO
      ↓
안전복장 착용 여부 판단
      ↓
    FastAPI
      ↓
 ┌─────────────┐
 │             │
PostgreSQL    AWS S3
위반 로그      캡처 이미지
 │
 ↓
React 관리자 대시보드

데이터 흐름
CCTV 영상 입력
      ↓
프레임 추출
      ↓
YOLO 객체 탐지
      ↓
Person / Hardhat / Safety Vest 탐지
      ↓
미착용 여부 판단
      ↓
위반 이벤트 발생
      ↓
DB 로그 저장 + 이미지 저장
      ↓
관리자 대시보드 출력

데이터베이스 저장 정보
CCTV ID
CCTV 위치
위반 유형
감지 시간
AI Confidence
위반 이미지 경로
처리 상태

예시

CCTV : CAM_01
위반 : NO_HARDHAT
시간 : 2026-09-08 14:32:18
신뢰도 : 0.94
상태 : 미처리

프로젝트 구조
capstone_2_B/

├── ai/
│   ├── dataset/
│   ├── train.py
│   └── best.pt
│
├── backend/
│   └── FastAPI
│
├── frontend/
│   └── React
│
├── database/
│   └── schema.sql
│
├── docs/
│   └── architecture.png
│
└── README.md

팀 역할

담당	역할
AI / Data	데이터 수집, 라벨 검증, YOLO 학습 및 성능 평가
Backend / Video	OpenCV 영상 처리, FastAPI, AI 모델 연동
Frontend	React 관리자 대시보드 및 위반 로그 UI
DB / AWS	PostgreSQL, AWS EC2·S3, Docker 및 배포
개발 진행 상황
 프로젝트 주제 선정
 PPE 데이터셋 수집
 안전모 / 안전조끼 라벨 검증
 YOLO 모델 학습
 영상 실시간 탐지
 FastAPI 개발
 PostgreSQL 연동
 React 관리자 대시보드
 AWS 배포
 최종 통합 테스트
