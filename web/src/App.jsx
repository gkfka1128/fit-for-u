// 화면 구성·문구·디자인은 민상님 fit-for-u.py(Streamlit) 를 그대로 옮기고, 속 기능은 우리 API(규칙 엔진·기상청·승민님 체형 모델) 로 연결.
import { useEffect, useRef, useState } from "react";
import * as api from "./api.js";
import { Guide, Home, Login, Profile, Qna, Reviews, Saved } from "./pages.jsx";
import { Analysis } from "./analysis.jsx";
import { Recommend } from "./recommend.jsx";
import { Study } from "./study.jsx";

const PAGES = ["home", "analysis", "recommend", "saved", "reviews", "qna", "guide", "profile", "study"];
const MENU = [["home", "🏠 홈"], ["guide", "❓ 이용 안내"], ["analysis", "📷 체형 분석"], ["recommend", "✨ 코디 추천"], ["saved", "♡ 저장한 코디"],
  ["profile", "👤 마이페이지"], ["reviews", "📝 후기"], ["qna", "Q&A 게시판"], ["study", "🧪 평가 참여"]];
// 새로고침해도 체형 분석 결과·상황은 유지 (탭을 닫으면 사라짐). 사진은 결과에 들어 있지 않다.
const keep = {
  get: (k, d) => { try { return JSON.parse(sessionStorage.getItem("ffu_" + k)) ?? d; } catch { return d; } },
  set: (k, v) => { try { if (v == null) sessionStorage.removeItem("ffu_" + k); else sessionStorage.setItem("ffu_" + k, JSON.stringify(v)); } catch { /* 무시 */ } },
};
const pageFromHash = () => { const p = location.hash.slice(1); return PAGES.includes(p) ? p : "home"; };

export function Footer() {
  return <div className="footer-box">Fit-For-U · AI Personal Styling Service<br />Body · Weather · Preference · OOTD</div>;
}

export default function App() {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState(null);          // 서버 DB 의 회원 정보 (id 포함)
  const [pref, setPrefState] = useState(null);     // 👍👎 취향 — 서버에 회원별로 저장
  const userId = user?.id || "";
  const [page, setPage] = useState(pageFromHash);
  const [menuOpen, setMenuOpen] = useState(false);
  const [situation, setSituation] = useState(() => keep.get("situation", "학교"));
  // 날씨 — 로그인하면 서울을 먼저 불러온다. 실패하면 직접 입력값을 쓴다.
  const [regions, setRegions] = useState({});
  const [region, setRegion] = useState(() => keep.get("region", "서울"));
  const [wx, setWx] = useState(null);
  const [wxErr, setWxErr] = useState("");
  const [wxBusy, setWxBusy] = useState(false);
  const [manualWx, setManualWx] = useState(() => keep.get("manualWx", { feels_like: 15, precip_prob: 10 }));
  // 체형 — { source: "photo"|"measure"|"manual", label, body?, bodyType?, res? } 가 있으면 분석 완료
  const [analysis, setAnalysis] = useState(() => keep.get("analysis", null));
  useEffect(() => keep.set("analysis", analysis), [analysis]);
  useEffect(() => keep.set("situation", situation), [situation]);
  useEffect(() => keep.set("region", region), [region]);
  useEffect(() => keep.set("manualWx", manualWx), [manualWx]);
  // 다른 앱을 보고 돌아와 화면이 다시 불러와져도 보던 위치로 — 쓰는 화면별 스크롤 위치를 기억했다가 처음 한 번만 복원
  const scrollDone = useRef(false);
  useEffect(() => {
    let t; const save = () => keep.set("scroll_" + pageFromHash(), scrollY);
    const onScroll = () => { clearTimeout(t); t = setTimeout(save, 150); };
    const onHide = () => { if (document.hidden) save(); };
    addEventListener("scroll", onScroll, { passive: true }); document.addEventListener("visibilitychange", onHide); addEventListener("pagehide", save);
    return () => { removeEventListener("scroll", onScroll); document.removeEventListener("visibilitychange", onHide); removeEventListener("pagehide", save); clearTimeout(t); };
  }, []);

  useEffect(() => {
    try { localStorage.removeItem("ffu_demo_v1"); } catch { /* 예전 시연 버전이 브라우저에 남긴 회원 정보는 지운다 */ }
    (api.token.get() ? api.getMe().then((d) => setUser(d.user)).catch(() => api.token.set("")) : Promise.resolve()).finally(() => setReady(true));
    const onHash = () => setPage(pageFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!userId) return;
    api.getRegions().then((d) => setRegions(d.regions)).catch(() => {});
    api.getPref().then((d) => setPrefState(d.pref)).catch(() => {});
    loadWeather({ region: "서울" });
  }, [userId]);

  useEffect(() => {   // 화면이 다시 불러와졌을 때: 로그인 확인이 끝나면 보던 위치로 (내용이 늦게 채워지므로 잠깐 반복 시도)
    if (!ready || !userId || scrollDone.current) return;
    scrollDone.current = true;
    const y = keep.get("scroll_" + pageFromHash(), 0); if (!(y > 0)) return;
    let n = 0; const t = setInterval(() => { scrollTo(0, y); if (Math.abs(scrollY - y) < 5 || ++n > 25) clearInterval(t); }, 120);
  }, [ready, userId]);

  const go = (p) => { setMenuOpen(false); location.hash = p; setPage(p); scrollTo(0, 0); };

  async function loadWeather(params) {
    setWxBusy(true); setWxErr("");
    try { setWx(await api.getWeather(params)); } catch (e) { setWx(null); setWxErr(e.message); }
    setWxBusy(false);
  }
  function loadGeo() {
    if (!navigator.geolocation) return setWxErr("이 브라우저는 위치를 지원하지 않아요");
    setWxBusy(true); setWxErr("");
    navigator.geolocation.getCurrentPosition(
      (p) => loadWeather({ lat: p.coords.latitude, lon: p.coords.longitude }), // 좌표는 격자 계산에만 쓰고 저장하지 않음
      (e) => { setWxBusy(false); setWxErr(e.code === 1 ? "위치 권한이 거부됐어요 (주소창 자물쇠 → 위치 허용)" : "위치를 가져오지 못했어요"); },
      { timeout: 10000, maximumAge: 600000 },
    );
  }

  function onLogin(tok, u) { api.token.set(tok); setUser(u); go("home"); }
  function signedOut() { api.token.set(""); setUser(null); setPrefState(null); setAnalysis(null); setWx(null); go("home"); }
  function logout() { api.logout().catch(() => {}).finally(signedOut); }
  // 요청 중 로그인이 풀리면(토큰 만료 등) 로그인 화면으로
  const guard = (e) => { if (e instanceof api.AuthError) signedOut(); throw e; };
  async function saveProfile(p) { const d = await api.updateMe(p).catch(guard); setUser(d.user); }
  async function savePref(p) { setPrefState(p); await api.setPref(p).catch(guard); }

  if (!ready) return null;
  if (!userId) return <div className="wrap"><Login onLogin={onLogin} /></div>;

  const weather = {
    wx, wxErr, wxBusy, regions, region, setRegion: (r) => { setRegion(r); loadWeather({ region: r }); }, loadRegion: () => loadWeather({ region }), loadGeo, manualWx, setManualWx,
    feels_like: wx ? wx.weather.feels_like : manualWx.feels_like,
    precip_prob: wx ? wx.weather.precip_prob : manualWx.precip_prob,
    temp: wx ? (wx.forecast.temp ?? wx.weather.feels_like) : manualWx.feels_like,
    sky: wx ? (wx.forecast.sky || "-") : "직접 입력",
    humidity: wx?.forecast.humidity,
  };
  const ctx = { userId, user, go, situation, setSituation, weather, analysis, setAnalysis, saveProfile, logout, pref, savePref, guard };
  const View = { home: Home, analysis: Analysis, recommend: Recommend, saved: Saved, reviews: Reviews, qna: Qna, guide: Guide, profile: Profile, study: Study }[page];

  return (
    <div className="wrap">
      <div className="header">
        <button className="btn" onClick={() => setMenuOpen(!menuOpen)} aria-label="메뉴">☰</button>
        <button className="brand" onClick={() => go("home")}>Fit-For-<span>U</span></button>
        <button className="btn" onClick={() => go("profile")}>MY PAGE</button>
      </div>
      {menuOpen && (
        <>
          <div className="menu-box"><div className="menu-title">MENU</div><div className="menu-sub">{user.name}님, 원하는 메뉴를 선택해주세요.</div></div>
          <div className="menu-grid">{MENU.map(([p, n]) => <button key={p} className={"btn" + (page === p ? " primary" : "")} onClick={() => go(p)}>{n}</button>)}</div>
        </>
      )}
      <View ctx={ctx} />
      <Footer />
    </div>
  );
}
