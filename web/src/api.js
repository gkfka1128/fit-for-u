// 파이썬 추천 API (code/api_server.py) 호출. 배포 시 VITE_API 를 Cloud Run 주소로 바꾼다.
export const API = import.meta.env.VITE_API || "http://127.0.0.1:8770";

// 로그인 토큰 — 이 브라우저에는 토큰만 남고 회원 정보는 서버 DB(code/data/members.db)에 있다
const TOKEN = "ffu_token";
export const token = {
  get: () => { try { return localStorage.getItem(TOKEN) || ""; } catch { return ""; } },
  set: (t) => { try { if (t) localStorage.setItem(TOKEN, t); else localStorage.removeItem(TOKEN); } catch { /* 사생활 보호 모드 — 이번 화면에서만 유지 */ } },
};
export class AuthError extends Error {}

async function call(path, opts = {}) {
  const t = token.get();
  const headers = { ...(opts.body ? { "Content-Type": "application/json" } : {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) };
  let r;
  try { r = await fetch(API + path, { ...opts, headers }); }
  catch { throw new Error("추천 서버에 연결할 수 없어요. API 서버(api_server.py)가 켜져 있는지 확인해 주세요."); }
  const d = await r.json().catch(() => ({}));
  if (r.status === 401) throw new AuthError(d.error || "로그인이 필요합니다");
  if (!r.ok) throw new Error(d.error || `요청 실패 (${r.status})`);
  return d;
}
const post = (path, body) => call(path, { method: "POST", body: JSON.stringify(body) });

export const getRegions = () => call("/regions");
export const getWeather = (params) => call("/weather?" + new URLSearchParams(params));
export const recommend = (body) => post("/web/recommend", body);
export const sendFeedback = (body) => post("/web/feedback", body);
export const similar = (body) => post("/web/similar", body);
export const classifyBody = (body) => post("/body/classify", body);
export const classifyPhoto = (body) => post("/body/photo", body);

// 회원
export const signup = (id, pw, profile) => post("/auth/signup", { id, pw, profile });
export const login = (id, pw) => post("/auth/login", { id, pw });
export const logout = () => post("/auth/logout", {});
export const getMe = () => call("/me");
export const updateMe = (profile) => post("/me", { profile });
export const listSaved = () => call("/saved");
export const addSaved = (snap) => post("/saved", { snap });
export const deleteSaved = (id) => post("/saved/delete", { id });
export const getPref = () => call("/prefs");
export const setPref = (pref) => post("/prefs", { pref });
export const listReviews = () => call("/reviews");
export const addReview = (stars, text) => post("/reviews", { stars, text });
export const listQna = () => call("/qna");
export const addQna = (title, content) => post("/qna", { title, content });
export const deleteQna = (id) => post("/qna/delete", { id });

// 평가 참여 (평가 프로토콜 §5)
export const study = {
  start: (body) => post("/study/start", body),
  tape: (pid, tape) => post("/study/tape", { pid, tape }),
  photo: (pid, front, side) => post("/study/photo", { pid, front, ...(side ? { side } : {}) }),
  pair: (body) => post("/study/pair", body),
  answer: (body) => post("/study/answer", body),
  recommend: (body) => post("/study/recommend", body),
  survey: (body) => post("/study/survey", body),
};
