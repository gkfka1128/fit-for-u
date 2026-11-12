// 코디 추천 — 민상님 recommend_page 화면에 우리 규칙 엔진(/web/recommend) 결과를 넣음
import { useEffect, useRef, useState } from "react";
import { API, addSaved, listSaved, recommend, sendFeedback, similar } from "./api.js";
import { bmiInfo } from "./analysis.jsx";

export const SITUATIONS = [["🎓 학교", "학교"], ["❤️ 데이트", "데이트"], ["💼 출근", "출근"], ["☕ 약속", "친구와 약속"], ["🏃 운동", "운동"], ["✈️ 여행", "여행"]];
const BUILDS = ["마름", "보통", "통통"];
const GROUP_OF = { 역삼각형: "상체형", 삼각형: "하체형" };   // 나머지는 균형 (ffu_web_bridge.BODY_TYPE)

// 유사 의상을 찾을 수 있는 카드인지 → 서버 fb 의 키 (신발·"셔츠 위에 겹쳐 입기" 니트는 없음)
const simKeyOf = (c) => (c.category === "OUTER" ? "outer" : c.category === "BOTTOM" ? "bottom" : c.category === "TOP" && !String(c.desc).startsWith("셔츠 위에 겹쳐") ? "top" : null);

export function ItemCard({ c, tall, onSimilar }) {
  return (
    <div className={"item-card" + (tall ? " tall" : "")}>
      <div className="item-image">{c.image ? <img src={API + c.image} alt={c.name} loading="lazy" /> : c.icon}</div>
      <div className="item-category">{c.icon} {c.category}</div>
      <div className="item-name">{c.name}</div>
      <div className="item-desc">{c.desc}</div>
      {onSimilar && simKeyOf(c) && <button type="button" className="btn sm item-sim" onClick={() => onSimilar(c)}>🔍 비슷한 옷 보기</button>}
    </div>
  );
}

const KINDS = ["체형", "날씨", "취향", "상황", "데이터"];

// 민상님 "왜 이 코디일까요?" 카드 형식 (01 · 체형 …) 에 엔진 이유를 종류별로
function Why({ why }) {
  const groups = KINDS.map((k) => [k, why.filter((x) => x.kind === k)]).filter(([, xs]) => xs.length);
  return (
    <div className="card-desc why">
      {groups.map(([k, xs], i) => (
        <div key={k} className="why-row">
          <b>{String(i + 1).padStart(2, "0")} · {k}</b>
          {xs.map((x, j) => <div key={j}>{x.text}</div>)}
        </div>
      ))}
    </div>
  );
}

// 상황별로 어디에 비중을 뒀는지 (10/27 중간발표 피드백: "데이트는 포멀, 운동은 스포츠" 처럼 설명) — 서버 situation_summary
function SituationCard({ s }) {
  if (!s) return null;
  return (
    <div className="card situation-card">
      <div className="card-label">SITUATION · {s.situation}</div>
      <div className="card-title">'{s.situation}' 상황이라 {s.focus}에 비중을 뒀어요.</div>
      <div className="card-desc"><b>우선한 스타일</b> {s.styles.join(" · ")}</div>
      {s.preferred?.length > 0 && <div className="card-desc"><b>우선한 아이템</b> {s.preferred.join(" · ")}</div>}
      {s.excluded.length > 0 &&<div className="card-desc"><b>아예 뺀 아이템</b> {s.excluded.join(", ")}</div>}
    </div>
  );
}

// 결과 비교 — 조건 하나(상황 또는 체격)만 바꿔 같은 번호 추천끼리 나란히 (10/27 중간발표 피드백: "결과를 비교해서 보여 주기")
function Compare({ req, base, pick, situation, build }) {
  const [mode, setMode] = useState(null);   // situation | build
  const [alt, setAlt] = useState(null);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const reqKey = JSON.stringify(req);
  useEffect(() => {
    if (!mode || !alt) return;
    let alive = true;
    setRes(null); setErr("");
    recommend(mode === "situation" ? { ...req, situation: alt } : { ...req, body: { ...req.body, build: alt } })
      .then((d) => alive && setRes(d)).catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [mode, alt, reqKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const cur = mode === "build" ? build : situation;
  const options = mode === "build" ? BUILDS : SITUATIONS.map(([, v]) => v);
  const choose = (m) => { setMode(m); setAlt(m === "build" ? (build === "통통" ? "마름" : "통통") : (situation === "운동" ? "데이트" : "운동")); };
  const kind = mode === "build" ? "체형" : "상황";
  const side = (tag, d) => {
    const o = d?.outfits[Math.min(pick, d.outfits.length - 1)];
    return (
      <div>
        <div className="ab-tag">{tag}</div>
        {!o ? <div className="caption">{err || "코디를 고르는 중…"}</div> : (
          <>
            {mode === "situation" && d.situation && <div className="caption cmp-focus">{d.situation.focus}에 비중</div>}
            {(o.why || []).filter((x) => x.kind === kind).map((x, i) => <div key={i} className="caption cmp-why">{x.text}</div>)}
            {o.items.map((c, j) => <ItemCard key={`${tag}-${j}-${c.category}`} c={c} />)}
          </>
        )}
      </div>
    );
  };
  return (
    <div className="compare">
      <div className="section-title">비교해 보기</div>
      <div className="section-desc">조건을 하나만 바꾸면 추천이 어떻게 달라지는지 나란히 보여드려요.</div>
      <div className="chips">
        <button className={"chip" + (mode === "situation" ? " on" : "")} onClick={() => choose("situation")}>상황 바꿔 보기</button>
        <button className={"chip" + (mode === "build" ? " on" : "")} onClick={() => choose("build")}>체격 바꿔 보기</button>
      </div>
      {mode && (
        <>
          <div className="chips"><span className="caption">{mode === "build" ? "비교할 체격" : "비교할 상황"}</span>
            {options.filter((v) => v !== cur).map((v) => <button key={v} className={"chip" + (alt === v ? " on" : "")} onClick={() => setAlt(v)}>{v}</button>)}
          </div>
          <div className="grid2 ab cmp">
            {side(`지금 · ${cur}`, base)}
            {side(`바꾸면 · ${alt}`, res)}
          </div>
          <div className="caption">추천 {Math.min(pick + 1, base.outfits.length)}끼리 비교합니다. 나머지 조건(날씨 · 취향 · {mode === "build" ? "상황" : "체형"})은 그대로예요.</div>
        </>
      )}
    </div>
  );
}

export function Recommend({ ctx }) {
  const { user, analysis, weather: w, situation, go, pref, savePref, guard } = ctx;
  const [res, setRes] = useState(null);
  const [pick, setPick] = useState(0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [savedKeys, setSavedKeys] = useState(new Set());           // 이미 저장한 코디 (아이템 이름 묶음)
  const [fbMsg, setFbMsg] = useState("");
  const [fbBusy, setFbBusy] = useState(false);
  const [votes, setVotes] = useState({});
  const [sim, setSim] = useState(null);                              // 비슷한 옷 패널 {name, loading|data|err}
  const initPick = useRef((() => { try { return Number(JSON.parse(sessionStorage.getItem("ffu_pick"))) || 0; } catch { return 0; } })());   // 다시 불러와도 보던 추천 탭
  useEffect(() => { try { sessionStorage.setItem("ffu_pick", JSON.stringify(pick)); } catch { /* 무시 */ } }, [pick]);                          // 코디별 👍👎 선택 상태

  const profile = { gender: user.gender, height: user.height, weight: user.weight, style: user.style, fit: user.fit,
    like_colors: user.like_colors || [], avoid_colors: user.avoid_colors || [], personal_color: user.personal_color || "", hair: user.hair || "" };
  const key = JSON.stringify([profile, analysis?.label, analysis?.bodyType, situation, w.feels_like, w.precip_prob, pref?.weights]);
  useEffect(() => {
    if (!analysis) return;
    let alive = true;
    setBusy(true); setErr("");
    recommend({
      profile, situation, body_type: analysis.bodyType || "균형형", body: analysis.body,
      weather: { feels_like: w.feels_like, precip_prob: w.precip_prob }, pref: pref || undefined,
    }).then((d) => {
      if (!alive) return;
      setRes(d); setPick(Math.min(initPick.current, d.outfits.length - 1)); initPick.current = 0;
      // 추천 2·3 탭 사진을 미리 받아 둔다 — 탭을 바꿨을 때 이전 옷 사진이 남아 보이지 않게
      d.outfits.forEach((x) => x.items.forEach((c) => { if (c.image) new Image().src = API + c.image; }));
    }).catch((e) => alive && setErr(e.message)).finally(() => alive && setBusy(false));
    return () => { alive = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setSim(null); }, [pick, res]);                  // 다른 추천 탭·새 추천이면 비슷한 옷 패널은 닫는다
  const keysOf = (list) => new Set(list.map((x) => x.key));
  useEffect(() => { listSaved().then((d) => setSavedKeys(keysOf(d.saved))).catch(() => {}); }, []);

  if (!analysis) return (
    <>
      <div className="hero-title">체형 분석이<br />먼저 필요해요.</div>
      <div className="hero-desc">체형 분석을 완료하면 맞춤 코디를 추천받을 수 있습니다.</div>
      <button className="btn primary" style={{ marginTop: 20 }} onClick={() => go("analysis")}>📷 체형 분석하기</button>
    </>
  );

  const o = res?.outfits[pick];
  // 비교용 요청 — 체격을 바꿔 보려면 body 가 꼭 있어야 해서, 직접 선택(manual)이면 체형 이름·BMI 로 만든다
  const build = bmiInfo(user.height, user.weight)?.build || "보통";
  const cmpReq = {
    profile, situation, body_type: analysis.bodyType || "균형형",
    body: analysis.body ? { ...analysis.body, build: analysis.body.build || build }
      : { sex: user.gender === "여성" ? "F" : "M", group: GROUP_OF[analysis.bodyType] || "균형", build, leg: "보통" },
    weather: { feels_like: w.feels_like, precip_prob: w.precip_prob }, pref: pref || undefined,
  };
  // 누적 횟수는 서버가 따로 센다(history 는 최근 30건만 남아서 숫자가 서로 영향을 줬다). 예전 기록이면 history 로 센다
  const hist = pref?.history || [], likes = pref?.n_like ?? hist.filter((h) => h[0]).length, dislikes = pref?.n_dislike ?? hist.filter((h) => !h[0]).length;
  const oKey = o ? JSON.stringify(o.items.map((c) => c.name)) : "";
  const myVote = votes[oKey];                                      // 이 코디에 이미 누른 것 (true=👍, false=👎, undefined=아직)
  async function vote(like) {
    if (myVote !== undefined) return;                              // 같은 코디는 한 번만 — 연타로 숫자가 부풀지 않게
    setFbBusy(true); setFbMsg("");
    try {
      const d = await sendFeedback({ pref: pref || undefined, outfit: o.fb, like });
      setVotes((v) => ({ ...v, [oKey]: like }));
      await savePref({ weights: d.weights, history: d.history, n_like: d.n_like, n_dislike: d.n_dislike });   // 서버에 저장 → 추천 다시 불러옴 (key 에 pref 포함)
      setFbMsg(like ? "👍 반영했어요. 비슷한 옷이 더 자주 나와요." : "👎 반영했어요. 비슷한 옷은 덜 나오게 새 추천을 골랐어요.");
    } catch (e) { setFbMsg(e.message); }
    setFbBusy(false);
  }
  async function showSimilar(c) {
    const k = simKeyOf(c);
    if (!k || !o.fb[k]) return;
    setSim({ name: c.name, loading: true });
    try { setSim({ name: c.name, data: await similar({ ...cmpReq, key: k, item_id: o.fb[k].id, color: c.color || undefined }) }); }
    catch (e) { setSim({ name: c.name, err: e.message }); }
    setTimeout(() => document.querySelector(".sim-panel")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);   // 패널이 코디 아래쪽에 있어서 결과가 뜨면 그 위치로
  }
  function resetPref() { savePref(null).then(() => setFbMsg("취향 기록을 지웠어요."), (e) => setFbMsg(e.message)); }
  const saved = o && savedKeys.has(JSON.stringify(o.items.map((c) => c.name)));
  async function save() {
    try {
      const d = await addSaved({ outfit: o, situation, style: user.style, fit: user.fit, body: analysis.label,
        feels_like: w.feels_like, precip_prob: w.precip_prob, region: w.wx?.region || (w.wx ? "현재 위치" : "직접 입력") }).catch(guard);
      setSavedKeys(keysOf(d.saved));
    } catch (e) { setFbMsg(e.message); }
  }

  return (
    <>
      <div className="hero-title">{user.name}님의<br />오늘의 OOTD.</div>
      <div className="hero-desc">체형 · 날씨 · 취향 · 상황을 함께 고려한 추천입니다.</div>
      <div className="weather-card">
        <div className="weather-title">TODAY'S FIT</div>
        <div className="weather-desc">{analysis.label} · {w.temp}°C {w.sky} (체감 {w.feels_like}°, 강수 {w.precip_prob}%) · {user.style} · {user.fit} · {situation}</div>
        {!w.wx && <div className="caption">기상청 날씨를 불러오지 못해 홈에서 직접 입력한 날씨로 추천했어요.</div>}
      </div>
      {err && <div className="notice warn">추천을 불러오지 못했어요: {err}</div>}
      {busy && !res && <div className="caption" style={{ marginTop: 20 }}>코디를 고르는 중…</div>}
      {o && (
        <>
          <div className="section-title">추천 아이템</div>
          <div className="section-desc">오늘의 조건을 바탕으로 선택한 아이템입니다.</div>
          {res.outfits.length > 1 && (
            <div className="tabs">{res.outfits.map((_, i) => <button key={i} className={"tab" + (pick === i ? " on" : "")} onClick={() => setPick(i)}>추천 {i + 1}</button>)}</div>
          )}
          <div className="outfit">
            {/* key 에 탭 번호를 넣어 탭마다 카드를 새로 그린다 (같은 <img> 를 재사용하면 새 사진이 뜰 때까지 이전 사진이 남음) */}
            <ItemCard key={`${pick}-main`} c={o.items[0]} tall onSimilar={showSimilar} />
            <div className="right">{o.items.slice(1).map((c, j) => <ItemCard key={`${pick}-${j}-${c.category}`} c={c} onSimilar={showSimilar} />)}</div>
          </div>
          {sim && (
            <div className="card sim-panel">
              <div className="card-label">SIMILAR</div>
              <div className="card-title">'{sim.name}'와 비슷한 옷</div>
              {sim.loading && <div className="caption">비슷한 옷을 찾는 중…</div>}
              {sim.err && <div className="notice warn">비슷한 옷을 불러오지 못했어요: {sim.err}</div>}
              {sim.data && (sim.data.items.length ? (
                <>
                  <div className="section-desc">같은 종류에서 핏 · 기장 · 소재가 가까운 순이에요. 날씨 · 상황 · 취향은 그대로 반영했어요.</div>
                  <div className="sim-grid">
                    {sim.data.items.map((c, i) => (
                      <div key={i} className="sim-item">
                        <ItemCard c={c} />
                        <div className="caption">같은 점 · {c.shared.length ? c.shared.join(" · ") : "같은 종류"}</div>
                        <a className="btn sm block" href={c.link} target="_blank" rel="noreferrer">🔎 무신사에서 보기</a>
                      </div>
                    ))}
                  </div>
                </>
              ) : <div className="caption">조건에 맞는 비슷한 옷이 더 없어요.</div>)}
              <button type="button" className="linkbtn" onClick={() => setSim(null)}>닫기</button>
            </div>
          )}
          <div style={{ marginTop: 14 }}>
            <button className="btn primary block" onClick={save} disabled={saved}>{saved ? "♥ 저장됨" : "♡ 이 코디 저장"}</button>
            <div className="caption">옷 정보와 추천 조건을 저장합니다. 저장한 코디에서 개별 삭제할 수 있어요.</div>
          </div>
          <div className="feedback">
            <span>이 코디 어때요?</span>
            <button className={"btn sm" + (myVote === true ? " primary" : "")} onClick={() => vote(true)} disabled={fbBusy || busy || myVote !== undefined}>👍 좋아요</button>
            <button className={"btn sm" + (myVote === false ? " primary" : "")} onClick={() => vote(false)} disabled={fbBusy || busy || myVote !== undefined}>👎 별로예요</button>
            {(likes + dislikes > 0) && <span className="caption">취향 반영 중 · 👍 {likes} · 👎 {dislikes} <button className="linkbtn" onClick={resetPref}>초기화</button></span>}
          </div>
          {fbMsg && <div className="caption">{fbMsg}</div>}
          <div className="section-title">왜 이 코디일까요?</div>
          <div className="card">
            <div className="card-title">체형 · 날씨 · 취향 · 상황을 함께 고려했어요.</div>
            {o.why ? <Why why={o.why} /> : <ul className="card-desc reasons">{o.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
            <div className="links">{o.links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noreferrer">🔎 {l.query}</a>)}</div>
          </div>
          <SituationCard s={res.situation} />
          <Compare req={cmpReq} base={res} pick={pick} situation={situation} build={cmpReq.body.build} />
          <div style={{ marginTop: 24 }}><button className="btn block" onClick={() => go("home")}>🏠 홈으로</button></div>
        </>
      )}
    </>
  );
}
