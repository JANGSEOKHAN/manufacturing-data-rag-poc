# RAG 관리자 페이지 (React)

React 기반의 현대적인 관리자 페이지입니다. 기존 Streamlit과 FastAPI HTML 관리자 페이지의 기능을 통합했습니다.

## 주요 기능

- 📊 **대시보드**: 시스템 상태 및 문서 통계
- 📄 **문서 관리**: 문서 목록, 상세 정보, 삭제
- 📤 **파일 업로드**: Word, PowerPoint, Excel 등 문서 업로드
- 💬 **질의응답**: RAG 시스템을 통한 질의응답 인터페이스
- 🖼️ **이미지 관리**: 이미지 요약 및 미리보기
- 🔄 **벡터 스토어 관리**: 재구성 및 초기화

## 설치 및 실행

### 1. 의존성 설치

```bash
cd admin-frontend
npm install
```

### 2. 개발 서버 실행

```bash
npm run dev
```

개발 서버는 `http://localhost:8902`에서 실행됩니다.

### 3. 프로덕션 빌드

```bash
npm run build
```

빌드된 파일은 `dist/` 디렉토리에 생성됩니다.

## 환경 변수

`.env` 파일을 생성하여 API URL을 설정할 수 있습니다:

```env
VITE_API_URL=http://localhost:8601
```

기본값은 `http://localhost:8601`입니다.

## 백엔드 설정

백엔드 서버가 `http://localhost:8601`에서 실행 중이어야 합니다.

Vite 개발 서버는 자동으로 `/api`와 `/static` 경로를 백엔드로 프록시합니다.

## 기술 스택

- **React 18**: UI 라이브러리
- **TypeScript**: 타입 안정성
- **Vite**: 빌드 도구
- **React Router**: 라우팅
- **TanStack Query**: 데이터 페칭 및 캐싱
- **Tailwind CSS**: 스타일링
- **Lucide React**: 아이콘

## 프로젝트 구조

```
admin-frontend/
├── src/
│   ├── api/           # API 클라이언트
│   ├── components/    # 재사용 가능한 컴포넌트
│   ├── pages/         # 페이지 컴포넌트
│   ├── App.tsx        # 메인 앱 컴포넌트
│   └── main.tsx       # 진입점
├── public/            # 정적 파일
└── package.json       # 의존성
```

## API 엔드포인트

- `GET /api/admin/documents` - 모든 문서 목록
- `GET /api/admin/documents/{filename}` - 문서 상세 정보
- `GET /status` - 시스템 상태
- `POST /upload_file` - 파일 업로드
- `DELETE /delete_file/{filename}` - 파일 삭제
- `POST /rag_query` - RAG 질의응답

## 브라우저 지원

- Chrome (최신)
- Firefox (최신)
- Safari (최신)
- Edge (최신)
