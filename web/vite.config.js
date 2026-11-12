import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 공개 배포는 빌드본(vite preview)으로 — 개발 서버는 연결이 끊겼다 돌아오면(휴대폰에서 다른 앱을 보고 올 때) 페이지를 통째로 새로고침한다
  preview: {
    allowedHosts: ['.trycloudflare.com'],
    proxy: { '/api': { target: 'http://127.0.0.1:8770', rewrite: (p) => p.replace(/^\/api/, '') } },
  },
  server: {
    // 휴대폰 시연: cloudflared 임시 터널(https://*.trycloudflare.com) 하나로 웹과 API 를 같이 연다 (HTTPS 라 카메라 허용)
    allowedHosts: ['.trycloudflare.com'],
    // /api/... → 이 PC 의 파이썬 API 서버. 브라우저는 같은 주소로만 요청하므로 휴대폰에서도 동작
    proxy: { '/api': { target: 'http://127.0.0.1:8770', rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
