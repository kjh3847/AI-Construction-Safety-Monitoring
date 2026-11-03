export const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
export async function accountRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {credentials:'include',signal:AbortSignal.timeout(25000),...options,headers:{'Content-Type':'application/json',...options.headers}});
  const data = await response.json().catch(()=>({}));
  if (!response.ok) {
    if(response.status===401) window.dispatchEvent(new Event('session-expired'));
    throw new Error(typeof data.detail==='string'?data.detail:'입력값 또는 서버 연결을 확인하세요.');
  }
  return data;
}
