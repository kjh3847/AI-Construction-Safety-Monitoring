import {defineConfig} from 'vite';

const accountProxy = () => ({
  target: process.env.ACCOUNTS_API_URL || 'https://safety-capstone-2026.duckdns.org',
  changeOrigin: true,
  secure: true,
  configure(proxy) {
    proxy.on('proxyRes', (response, request) => {
      // The cloud connection keeps TLS verification. Only localhost's HTTP
      // development proxy removes Secure from its browser-facing cookie.
      const host = request.headers.host?.split(':')[0];
      if (!request.socket.encrypted && ['localhost', '127.0.0.1'].includes(host)) {
        const cookies = response.headers['set-cookie'];
        if (cookies) response.headers['set-cookie'] = cookies.map(cookie => cookie.replace(/;\s*Secure(?=;|$)/gi, ''));
      }
    });
  },
});

export default defineConfig({server:{port:5173,strictPort:true,
  // Recording frames change continuously; watching runtime trees can starve
  // the development proxy and delay WHEP handshakes past their deadline.
  watch:{ignored:['**/.local-run/**','**/.secrets/**','**/models/**','**/backend/recordings/**','**/.venv/**']},
  proxy:{
  '/api/auth': accountProxy(),
  '/api/admin': accountProxy(),
  '/api':{target:process.env.MONITOR_API_URL || 'http://127.0.0.1:8002',ws:true},
  '/video':process.env.MONITOR_API_URL || 'http://127.0.0.1:8002',
}}});
