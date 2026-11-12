import { useEffect, useState } from "react";
import * as api from "./api.js";
import { ItemCard, SITUATIONS } from "./recommend.jsx";
import { bmiInfo } from "./analysis.jsx";
import { COLOR_HEX, COLOR_NAMES, HAIRS, PERSONALS } from "./colors.js";

const STYLES = ["캐주얼", "미니멀", "스트릿", "스포티", "댄디"];
const FITS = ["오버핏", "레귤러핏", "슬림핏"];

function weatherMessage(t) {
  if (t == null) return "지역 설정과 API 연결을 확인해주세요.";
  if (t <= 5) return "기온이 낮아요. 보온성이 높은 아우터를 추천해요.";
  if (t <= 15) return "쌀쌀한 날씨예요. 재킷이나 가벼운 아우터가 좋아요.";
  if (t <= 22) return "선선한 날씨예요. 가볍게 레이어드하기 좋아요.";
  return "더운 날씨예요. 통기성이 좋은 가벼운 옷을 추천해요.";
}

const Field = ({ label, children }) => <label className="field">{label}{children}</label>;
const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)}>{options.map((o) => <option key={o}>{o}</option>)}</select>
);
// 숫자 입력칸: 다 지우면 칸은 빈 채로 두고(예전엔 "0" 이 남아 "05" 처럼 보였다), 부모에게는 이전처럼 숫자(빈 칸=0)를 넘긴다
function Num({ value, onChange, min, max, placeholder }) {
  const [txt, setTxt] = useState(String(value ?? ""));
  useEffect(() => { setTxt((t) => (Number(t) === Number(value) ? t : String(value ?? ""))); }, [value]);   // 밖에서 값이 바뀌면(프로필 불러오기 등) 칸도 따라간다
  return <input type="number" min={min} max={max} placeholder={placeholder} value={txt} onChange={(e) => { setTxt(e.target.value); onChange(Number(e.target.value)); }} />;
}

// 좋아하는/피하고 싶은 색 고르기 (칩, 최대 3개). 한쪽에서 고른 색은 반대쪽에서 못 고르게 막는다 (서버도 겹치면 거절)
const MAX_PICK = 3;
function ColorPick({ label, value, other, onChange }) {
  const toggle = (c) => onChange(value.includes(c) ? value.filter((x) => x !== c) : value.length >= MAX_PICK ? value : [...value, c]);
  return (
    <div className="color-pick">
      <div className="caption"><b>{label}</b> <span>{value.length}/{MAX_PICK}</span></div>
      <div className="chips">
        {COLOR_NAMES.map((c) => (
          <button type="button" key={c} className={"chip color" + (value.includes(c) ? " on" : "")} aria-pressed={value.includes(c)}
                  disabled={other.includes(c) || (!value.includes(c) && value.length >= MAX_PICK)} onClick={() => toggle(c)}>
            <span className="swatch" style={{ background: COLOR_HEX[c] }} />{c}
          </button>
        ))}
      </div>
    </div>
  );
}

function ProfileFields({ p, set }) {
  const f = (k) => (v) => set({ ...p, [k]: v });
  const bi = bmiInfo(p.height, p.weight);
  return (
    <>
      <div className="grid3">
        <Field label="성별"><Select value={p.gender} onChange={f("gender")} options={["남성", "여성"]} /></Field>
        <Field label="키(cm)"><Num value={p.height} onChange={f("height")} min={120} max={220} placeholder="예: 170" /></Field>
        <Field label="몸무게(kg)"><Num value={p.weight} onChange={f("weight")} min={30} max={200} placeholder="예: 65" /></Field>
      </div>
      {/* 키·몸무게를 고치는 대로 다시 계산 — 이 체격(마름·보통·통통)이 추천에 들어간다 */}
      <div className="bmi-line">{bi ? <>BMI <b>{bi.bmi}</b> · 체격 <b>{bi.build}</b> <span className="caption">키·몸무게로 자동 계산해 추천에 반영해요</span></> : <span className="caption">키와 몸무게를 넣으면 BMI를 자동으로 계산해요</span>}</div>
      <div className="grid2">
        <Field label="선호 스타일"><Select value={p.style} onChange={f("style")} options={STYLES} /></Field>
        <Field label="선호 핏"><Select value={p.fit} onChange={f("fit")} options={FITS} /></Field>
      </div>
      {/* 선택 정보 — 비워 두면 지금까지와 똑같이 추천해요 */}
      <details className="exp" open={!!(p.like_colors?.length || p.avoid_colors?.length || p.personal_color || p.hair)}>
        <summary>🎨 더 내 취향에 맞추기 (선택) — 좋아하는 색 · 피하고 싶은 색 · 퍼스널 컬러 · 머리 길이</summary>
        <ColorPick label="좋아하는 색" value={p.like_colors || []} other={p.avoid_colors || []} onChange={f("like_colors")} />
        <ColorPick label="피하고 싶은 색" value={p.avoid_colors || []} other={p.like_colors || []} onChange={f("avoid_colors")} />
        <div className="grid2" style={{ marginTop: 14 }}>
          <Field label="퍼스널 컬러"><Select value={p.personal_color || "모름"} onChange={(v) => f("personal_color")(v === "모름" ? "" : v)} options={PERSONALS} /></Field>
          <Field label="머리 길이"><Select value={p.hair || "선택 안 함"} onChange={(v) => f("hair")(v === "선택 안 함" ? "" : v)} options={HAIRS} /></Field>
        </div>
        <div className="caption">퍼스널 컬러와 머리 길이는 직접 고른 값만 써요. 사진으로 피부톤을 추정하지는 않아요. 일반적인 스타일링 가이드를 가볍게 반영하는 참고값이라, 맞지 않으면 '모름'으로 두셔도 돼요.</div>
      </details>
    </>
  );
}

// ───────── 로그인 / 회원가입
export function Login({ onLogin }) {
  const [tab, setTab] = useState("login");
  const [id, setId] = useState(""); const [pw, setPw] = useState("");
  const [msg, setMsg] = useState(""); const [ok, setOk] = useState("");
  const [s, setS] = useState({ name: "", id: "", pw: "", pw2: "", email: "", phone: "", gender: "남성", height: "", weight: "", style: "캐주얼", fit: "오버핏", like_colors: [], avoid_colors: [], personal_color: "", hair: "", privacy: false });

  async function doLogin() {
    setMsg("");
    try { const d = await api.login(id.trim(), pw); onLogin(d.token, d.user); }
    catch (e) { setMsg(e instanceof api.AuthError ? "아이디 또는 비밀번호를 확인해주세요." : e.message); }
  }
  async function doSignup() {
    setMsg(""); setOk("");
    if (!s.name.trim() || !s.id.trim() || !s.pw || !s.email.trim()) return setMsg("필수 정보를 모두 입력해주세요.");
    if (!/^[A-Za-z0-9_]{3,20}$/.test(s.id.trim())) return setMsg("아이디는 영문·숫자·_ 3~20자로 정해주세요.");
    if (s.pw.length < 8) return setMsg("비밀번호는 8자 이상으로 정해주세요.");
    if (s.pw !== s.pw2) return setMsg("비밀번호가 일치하지 않습니다.");
    if (!s.email.includes("@")) return setMsg("이메일 형식을 확인해주세요.");
    if (!(s.height >= 120 && s.height <= 220)) return setMsg("키는 120~220cm 사이로 입력해주세요.");
    if (!(s.weight >= 30 && s.weight <= 200)) return setMsg("몸무게는 30~200kg 사이로 입력해주세요.");
    if (!s.privacy) return setMsg("개인정보 수집 및 이용에 동의해주세요.");
    const { id: sid, pw: spw, pw2: _pw2, privacy: _privacy, ...profile } = s;
    try { await api.signup(sid.trim(), spw, profile); setOk("회원가입 완료! 로그인해주세요."); setTab("login"); setId(sid.trim()); setPw(""); }
    catch (e) { setMsg(e.message); }
  }
  const ss = (k) => (e) => setS({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  return (
    <>
      <div className="ff-login-top">FIT-FOR-U &nbsp; / &nbsp; PERSONAL FASHION PLATFORM</div>
      <div className="center">
        <div className="login-logo"><div className="login-title">Fit-For-U</div><div className="login-sub">YOUR BODY. YOUR WEATHER. YOUR STYLE.</div></div>
        <div className="ff-login-headline">나다운 스타일의 시작.</div>
        <div className="ff-login-note">체형 분석부터 오늘의 코디까지, 당신만의 패션을 발견하세요.</div>
        <div className="tabs">
          <button className={"tab" + (tab === "login" ? " on" : "")} onClick={() => { setTab("login"); setMsg(""); }}>로그인</button>
          <button className={"tab" + (tab === "signup" ? " on" : "")} onClick={() => { setTab("signup"); setMsg(""); setOk(""); }}>회원가입</button>
        </div>
        {tab === "login" ? (
          <form onSubmit={(e) => { e.preventDefault(); doLogin(); }}>
            <Field label="아이디"><input value={id} onChange={(e) => setId(e.target.value)} placeholder="아이디를 입력하세요" autoComplete="username" /></Field>
            <Field label="비밀번호"><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="비밀번호를 입력하세요" autoComplete="current-password" /></Field>
            <button className="btn primary block">Fit-For-U 시작하기</button>
            {ok && <div className="notice">{ok}</div>}
            {msg && <div className="err">{msg}</div>}
            <div className="ff-login-footer">FIT-FOR-U &nbsp; © 2026 &nbsp; / &nbsp; PERSONAL STYLING SERVICE</div>
          </form>
        ) : (
          <form onSubmit={(e) => { e.preventDefault(); doSignup(); }}>
            <Field label="이름"><input value={s.name} onChange={ss("name")} /></Field>
            <Field label="아이디"><input value={s.id} onChange={ss("id")} autoComplete="username" /></Field>
            <Field label="비밀번호 (8자 이상)"><input type="password" value={s.pw} onChange={ss("pw")} autoComplete="new-password" /></Field>
            <Field label="비밀번호 확인"><input type="password" value={s.pw2} onChange={ss("pw2")} autoComplete="new-password" /></Field>
            <Field label="이메일"><input value={s.email} onChange={ss("email")} /></Field>
            <Field label="전화번호 (선택)"><input value={s.phone} onChange={ss("phone")} /></Field>
            <ProfileFields p={s} set={setS} />
            <label className="check"><input type="checkbox" checked={s.privacy} onChange={ss("privacy")} />개인정보 수집 및 이용에 동의합니다.</label>
            <button className="btn primary block">회원가입</button>
            {msg && <div className="err">{msg}</div>}
            <div className="caption">회원 정보는 다른 용도로 사용되지 않고 테스트 기간이 끝나면 삭제합니다.</div>
          </form>
        )}
      </div>
    </>
  );
}

// ───────── 홈
function WeatherCard({ w }) {
  const f = w.wx?.forecast;
  return (
    <div className="weather-card">
      <div className="weather-title">☁️ {w.temp}°C · {w.sky}</div>
      <div className="weather-desc">
        {w.wx ? <>{w.wx.region ? `${w.wx.region} 부근` : "현재 위치"} · 체감 {w.feels_like}° · 최고 {f.tmx ?? "-"}° / 최저 {f.tmn ?? "-"}° · 강수확률 {w.precip_prob}%{w.humidity != null && ` · 습도 ${w.humidity}%`}<br /></> : null}
        {weatherMessage(w.temp)}
        {w.wx && <div className="caption">기상청 단기예보 · 발표 {f.base.slice(5, 16).replace("T", " ")}</div>}
      </div>
      <div className="weather-tools">
        <Field label="지역"><Select value={w.region} onChange={w.setRegion} options={Object.keys(w.regions).length ? Object.keys(w.regions) : ["서울"]} /></Field>
        <button className="btn" onClick={w.loadRegion} disabled={w.wxBusy}>{w.wxBusy ? "불러오는 중…" : "날씨 새로고침"}</button>
        <button className="btn" onClick={w.loadGeo} disabled={w.wxBusy}>📍 현재 위치</button>
      </div>
      {w.wxErr && <div className="err">날씨를 불러오지 못했어요: {w.wxErr}</div>}
      {!w.wx && (
        <div className="grid2" style={{ marginTop: 14 }}>
          <Field label="체감온도(°C) 직접 입력"><Num value={w.manualWx.feels_like} onChange={(v) => w.setManualWx({ ...w.manualWx, feels_like: v })} /></Field>
          <Field label="강수확률(%) 직접 입력"><Num value={w.manualWx.precip_prob} min={0} max={100} onChange={(v) => w.setManualWx({ ...w.manualWx, precip_prob: v })} /></Field>
        </div>
      )}
    </div>
  );
}

export function Home({ ctx }) {
  const { user, weather: w, situation, setSituation, analysis, go, setAnalysis } = ctx;
  return (
    <>
      <div className="eyebrow">FIT-FOR-U / THE STYLE EDIT</div>
      <div className="editorial-hero">
        <div className="editorial-hero-copy">
          <span className="editorial-pill">PERSONAL FASHION CURATION</span>
          <h1>나에게 맞는<br />스타일을 찾다.</h1>
          <p>{user.name}님을 위한 스타일 큐레이션.<br />체형부터 오늘의 날씨까지.<br />나에게 어울리는 스타일을 추천받아 보세요.</p>
        </div>
        <div className="editorial-hero-photo" role="img" aria-label="패션 스타일링 화보" />
      </div>
      <button className="btn block" style={{ marginBottom: 14 }} onClick={() => go("guide")}>❓ 처음이세요? 이용 안내 보기</button>
      <div className="feature-strip">
        <div><strong>01 / BODY PROFILE</strong>카메라로 시작하는 개인 체형 분석</div>
        <div><strong>02 / WEATHER FIT</strong>오늘의 날씨를 반영한 스타일</div>
        <div><strong>03 / CURATED LOOKS</strong>취향과 상황에 맞는 데일리 코디</div>
      </div>
      <div className="banner">
        <div className="banner-label">WEATHER FIT · TODAY</div>
        <div className="banner-title">오늘의 날씨를<br />스타일로 바꿔보세요.</div>
        <div className="banner-desc">현재 {w.temp}°C · {w.sky}<br />{weatherMessage(w.temp)}</div>
      </div>
      <WeatherCard w={w} />
      <div className="section-title">오늘 어디에 가세요?</div>
      <div className="section-desc">상황까지 선택하면 더 자연스러운 코디를 추천해드려요.</div>
      <div className="grid6">
        {SITUATIONS.map(([label, v]) => <button key={v} className={"btn" + (situation === v ? " primary" : "")} onClick={() => setSituation(v)}>{label}</button>)}
      </div>
      {!analysis ? (
        <>
          <div className="ai-card">
            <div className="ai-icon">✨</div><div className="ai-label">AI PERSONAL STYLING</div>
            <div className="ai-title">내 스타일을 찾아볼까요?</div>
            <div className="ai-desc">전신 사진 한 장으로 체형을 분석하고<br />날씨와 취향까지 반영한 코디를 추천받아보세요.</div>
          </div>
          <div className="center" style={{ marginTop: 16 }}><button className="btn primary block" onClick={() => go("analysis")}>📷 내 스타일 찾기</button></div>
        </>
      ) : (
        <>
          <div className="section-title">최근 분석</div>
          <div className="section-desc">내 체형을 바탕으로 오늘의 추천을 확인해보세요.</div>
          <div className="recent-card">
            <div className="recent-label">MY BODY PROFILE</div>
            <div className="recent-title">{analysis.label}</div>
            <div className="recent-desc">{user.style} · {user.fit} · {w.temp}°C · {situation}</div>
          </div>
          <div className="grid2" style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={() => go("recommend")}>✨ 오늘의 코디 보기</button>
            <button className="btn" onClick={() => { setAnalysis(null); go("analysis"); }}>📷 다시 분석하기</button>
          </div>
        </>
      )}
    </>
  );
}

// ───────── 저장한 코디
export function Saved({ ctx }) {
  const [list, setList] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api.listSaved().then((d) => setList(d.saved)).catch((e) => { setErr(e.message); ctx.guard(e); }).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function remove(id) {
    try { setList((await api.deleteSaved(id)).saved); } catch (e) { setErr(e.message); }
  }
  if (!list) return <div className="caption">{err || "불러오는 중…"}</div>;
  return (
    <>
      <div className="hero-title">저장한 코디.</div>
      <div className="hero-desc">저장 당시의 옷 정보와 추천 조건을 다시 확인해보세요.</div>
      <p>총 {list.length}개의 코디</p>
      {!list.length && (<><div className="notice">아직 저장한 코디가 없습니다.</div><button className="btn primary" onClick={() => ctx.go("recommend")}>✨ 코디 추천받기</button></>)}
      {list.map((s) => (
        <details className="exp" key={s.id}>
          <summary>{new Date(s.at).toLocaleString("ko-KR")} · {s.situation} · {s.style} · {s.fit}</summary>
          <div>
            <div className="grid4">{s.outfit.items.map((c, j) => <ItemCard key={`${j}-${c.category}`} c={c} />)}</div>
            <dl className="kv">
              <dt>상황</dt><dd>{s.situation}</dd><dt>스타일 · 핏</dt><dd>{s.style} · {s.fit}</dd>
              <dt>체형</dt><dd>{s.body}</dd><dt>체감온도</dt><dd>{s.feels_like}°C</dd><dt>강수확률</dt><dd>{s.precip_prob}%</dd>
              {s.region && (<><dt>지역</dt><dd>{s.region}</dd></>)}
            </dl>
            <button className="btn sm" onClick={() => remove(s.id)}>이 코디 삭제</button>
          </div>
        </details>
      ))}
      {err && <div className="err">{err}</div>}
      <div className="caption">저장한 코디는 내 계정에 남아서 다른 기기에서 로그인해도 볼 수 있어요.</div>
    </>
  );
}

// ───────── 후기
export function Reviews({ ctx }) {
  const [stars, setStars] = useState(5);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState("");
  const [list, setList] = useState([]);
  useEffect(() => { api.listReviews().then((d) => setList(d.reviews)).catch((e) => { setMsg(e.message); ctx.guard(e); }).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function submit() {
    if (!text.trim()) return setMsg("후기 내용을 입력해주세요.");
    try { setList((await api.addReview(stars, text.trim())).reviews); setText(""); setMsg("후기가 등록되었습니다."); }
    catch (e) { setMsg(e.message); }
  }
  return (
    <>
      <div className="hero-title">사용자 후기.</div>
      <div className="hero-desc">Fit-For-U를 사용한 경험을 공유해주세요.</div>
      <div className="section-title">후기 작성</div>
      <div className="field">만족도</div>
      <div className="stars">{[1, 2, 3, 4, 5].map((n) => <button key={n} onClick={() => setStars(n)} aria-label={`${n}점`}>{n <= stars ? "★" : "☆"}</button>)}</div>
      <Field label="후기"><textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Fit-For-U를 사용해보니 어땠나요?" /></Field>
      <button className="btn primary" onClick={submit}>후기 등록</button>
      {msg && <div className="caption">{msg}</div>}
      <div className="section-title">최근 후기</div>
      {!list.length && <div className="notice">아직 작성된 후기가 없습니다.</div>}
      {list.map((r) => (
        <div className="review-card" key={r.id}>
          <div className="review-star">{"★".repeat(r.stars)}{"☆".repeat(5 - r.stars)}</div>
          <div className="review-user">{r.user}</div>
          <div className="review-text">{r.text}</div>
        </div>
      ))}
    </>
  );
}

// ───────── 이용 안내
export function Guide() {
  return (
    <>
      <div className="hero-title">사진 한 장에서<br />오늘의 코디까지.</div>
      <div className="hero-desc">Fit-For-U의 추천 과정을 확인해보세요.</div>
      <div className="grid3" style={{ marginTop: 28 }}>
        <div className="card"><div className="card-icon">📷</div><div className="card-label">STEP 01</div><div className="card-title">전신 사진 촬영</div><div className="card-desc">정면 전신 사진을 촬영하고 신체 분석을 위한 이미지를 준비합니다.</div></div>
        <div className="card"><div className="card-icon">📊</div><div className="card-label">STEP 02</div><div className="card-title">체형 분석</div><div className="card-desc">MediaPipe로 신체 비율을 계산해 상체형·하체형·균형으로 체형을 분류합니다.</div></div>
        <div className="card"><div className="card-icon">👕</div><div className="card-label">STEP 03</div><div className="card-title">OOTD 추천</div><div className="card-desc">체형, 날씨, 취향, 상황과 패션 데이터를 조합해 오늘의 코디를 추천합니다.</div></div>
      </div>
      <div className="section-title">Fit-For-U 추천 구조</div>
      <div className="section-desc">최종적으로 아래 정보가 하나의 추천 과정에 연결됩니다.</div>
      <div className="grid4">
        <div className="info-box"><b>🧍 체형</b>MediaPipe 기반 신체 비율 분석</div>
        <div className="info-box"><b>☁️ 날씨</b>기상청 단기예보</div>
        <div className="info-box"><b>❤️ 취향</b>사용자 프로필</div>
        <div className="info-box"><b>👕 의류</b>K-Fashion 규칙 엔진</div>
      </div>
    </>
  );
}

// ───────── 마이페이지
export function Profile({ ctx }) {
  const { user, analysis, go, saveProfile, logout } = ctx;
  const [tab, setTab] = useState("info");
  const [p, setP] = useState(user);
  const [msg, setMsg] = useState("");
  return (
    <>
      <div className="hero-title">마이페이지.</div>
      <div className="hero-desc">나의 정보와 스타일 취향을 관리하세요.</div>
      <div className="profile-card"><div className="profile-name">👤 {user.name}</div><div className="profile-email">{user.email}</div></div>
      <div className="tabs" style={{ marginTop: 24 }}>
        <button className={"tab" + (tab === "info" ? " on" : "")} onClick={() => setTab("info")}>내 정보</button>
        <button className={"tab" + (tab === "style" ? " on" : "")} onClick={() => setTab("style")}>나의 스타일</button>
      </div>
      {tab === "info" ? (
        <>
          <Field label="이름"><input value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} /></Field>
          <Field label="이메일"><input value={p.email} onChange={(e) => setP({ ...p, email: e.target.value })} /></Field>
          <Field label="전화번호"><input value={p.phone} onChange={(e) => setP({ ...p, phone: e.target.value })} /></Field>
          <ProfileFields p={p} set={setP} />
          <button className="btn primary block" onClick={() => {
            if (!(p.height >= 120 && p.height <= 220)) return setMsg("키는 120~220cm 사이로 입력해주세요.");
            if (!(p.weight >= 30 && p.weight <= 200)) return setMsg("몸무게는 30~200kg 사이로 입력해주세요.");
            saveProfile(p).then(() => setMsg("정보가 저장되었습니다."), (e) => setMsg(e.message));
          }}>변경사항 저장</button>
          {msg && <div className="caption">{msg}</div>}
        </>
      ) : (
        <>
          <div className="grid3">
            <div className="metric"><div className="k">나의 체형</div><div className="v">{analysis ? analysis.label : "분석 전"}</div></div>
            <div className="metric"><div className="k">선호 스타일</div><div className="v">{user.style}</div></div>
            <div className="metric"><div className="k">선호 핏</div><div className="v">{user.fit}</div></div>
          </div>
          <div className="caption" style={{ marginTop: 12 }}>
            좋아하는 색 {user.like_colors?.length ? user.like_colors.join(" · ") : "없음"} · 피하고 싶은 색 {user.avoid_colors?.length ? user.avoid_colors.join(" · ") : "없음"} ·
            퍼스널 컬러 {user.personal_color || "모름"} · 머리 길이 {user.hair || "선택 안 함"} <span>('내 정보'에서 바꿀 수 있어요)</span>
          </div>
          <div style={{ marginTop: 16 }}>
            {analysis ? <button className="btn primary block" onClick={() => go("recommend")}>✨ 내 추천 코디 보기</button>
              : <button className="btn primary block" onClick={() => go("analysis")}>📷 체형 분석 시작하기</button>}
          </div>
        </>
      )}
      <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "28px 0" }} />
      <button className="btn block" onClick={logout}>🚪 로그아웃</button>
    </>
  );
}

// ───────── Q&A
export function Qna({ ctx }) {
  const [title, setTitle] = useState(""); const [content, setContent] = useState(""); const [msg, setMsg] = useState("");
  const [posts, setPosts] = useState([]);
  useEffect(() => { api.listQna().then((d) => setPosts(d.qna)).catch((e) => { setMsg(e.message); ctx.guard(e); }).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function submit(e) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return setMsg("제목과 내용을 모두 입력해 주세요.");
    try { setPosts((await api.addQna(title.trim(), content.trim())).qna); setTitle(""); setContent(""); setMsg("질문이 등록되었습니다."); }
    catch (err) { setMsg(err.message); }
  }
  async function remove(id) {
    try { setPosts((await api.deleteQna(id)).qna); } catch (err) { setMsg(err.message); }
  }
  return (
    <>
      <div className="ff-page-eyebrow">FIT-FOR-U / COMMUNITY</div>
      <div className="hero-title">Q&A 게시판.</div>
      <div className="caption">서비스에 관한 질문을 남겨 주세요.</div>
      <details className="exp" style={{ marginTop: 20 }}>
        <summary>+ 새 질문 작성</summary>
        <form onSubmit={submit}>
          <Field label="제목"><input maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="질문 제목을 입력해 주세요" /></Field>
          <Field label="질문 내용"><textarea maxLength={3000} value={content} onChange={(e) => setContent(e.target.value)} placeholder="궁금한 내용을 자세히 적어 주세요" /></Field>
          <button className="btn primary block">질문 등록</button>
          {msg && <div className="caption">{msg}</div>}
        </form>
      </details>
      <h3>전체 질문 ({posts.length})</h3>
      {!posts.length && <div className="notice">아직 등록된 질문이 없어요. 첫 질문을 남겨 주세요!</div>}
      {posts.map((p) => (
        <details className="exp" key={p.id}>
          <summary>[{p.answer ? "답변 완료" : "답변 대기"}] {p.title} · {p.username} · {p.at.slice(0, 10)}</summary>
          <div>
            <p style={{ whiteSpace: "pre-wrap" }}>{p.content}</p>
            {p.answer ? <div className="info-box"><b>답변</b>{p.answer}</div> : <div className="caption">아직 답변이 등록되지 않았습니다.</div>}
            {p.username === ctx.userId && <button className="btn sm" style={{ marginTop: 10 }} onClick={() => remove(p.id)}>내 질문 삭제</button>}
          </div>
        </details>
      ))}
      <div className="caption">관리자 답변 기능은 관리자 권한을 만든 뒤 연결할 예정입니다.</div>
    </>
  );
}
