// 체형 분석 — 민상님 analysis_page / analysis_result 흐름에 승민님 체형 모델(/body/photo, /body/classify) 을 연결
import { useEffect, useRef, useState } from "react";
import { classifyBody, classifyPhoto } from "./api.js";

const BODY_TYPES = ["역삼각형", "삼각형", "직사각형", "모래시계형", "균형형"];
// 모델은 서버가 자동 선택 (preset "auto"): 정면 → 3군집, 애매하면 측면을 요청 → 5군집
const GROUP_DESC = { 상체형: "어깨·가슴 너비가 엉덩이보다 넓은 편", 하체형: "엉덩이 너비가 어깨·가슴보다 넓은 편", 균형: "어깨·가슴과 엉덩이 너비가 비슷한 편" };
// 체격(마름·보통·통통)은 사진 군집이 실측과 맞지 않아(runs/cluster_val.md) 프로필 키·몸무게 BMI 로 정한다 (기준은 ffu_web_bridge.engine_body 와 같음).
// 10/27 중간발표 피드백: BMI 가 자동 계산되는 걸 화면에 보여 주기 — 프로필 입력칸·분석 결과에 표시
export const bmiInfo = (h, w) => {
  const b = Number(w) / (Number(h) / 100) ** 2;
  return !(b > 0 && isFinite(b)) ? null : { bmi: b.toFixed(1), build: b < 18.5 ? "마름" : b < 23 ? "보통" : "통통" };
};
const bmiBuild = (h, w) => bmiInfo(h, w)?.build ?? null;
// 촬영 때 입은 옷 — 몸선을 가리는 옷이면 어깨·허리·엉덩이 위치를 못 찾아 정확도가 떨어진다 (10/27 피드백: "몸이 드러나는 옷이면 정확도가 오른다")
const ATTIRE = [["fitted", "몸에 붙는 옷"], ["regular", "보통 핏"], ["loose", "헐렁한 옷 · 아우터"]];

// 휴대폰 원본(수 MB)을 그대로 보내지 않고 긴 변 1600px JPEG 로 줄여 보낸다 — 전송·분석이 빨라지고 MediaPipe 정확도엔 충분
const MAX_SIDE = 1600;
function toJpeg(src, w, h) {
  const k = Math.min(1, MAX_SIDE / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.round(w * k); c.height = Math.round(h * k);
  c.getContext("2d").drawImage(src, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.9);
}
async function fileToJpeg(file) {
  const bmp = await createImageBitmap(file, { imageOrientation: "from-image" }); // 휴대폰 사진 회전 정보 반영
  try { return toJpeg(bmp, bmp.width, bmp.height); } finally { bmp.close(); }
}

// 노트북/휴대폰 카메라 — 혼자 2m 떨어져 전신을 찍을 수 있게 타이머(카운트다운)와 화면·음성 안내.
// 찍은 사진은 브라우저 메모리에만 두고 분석 요청에만 보낸다
const POSE_GUIDE = {
  front: ["정면을 보고 편하게 서 주세요", "머리부터 발끝까지 점선 안에 · 팔은 몸에서 주먹 두 개만큼 벌리기"],
  side: ["이번엔 옆으로 돌아서 주세요", "점선 안에 전신 · 팔은 몸통 앞쪽 · 허리·엉덩이 선 보이게"],
};

// 촬영 가이드 오버레이 — 점선 틀(머리 위·발끝 아래 여백) + 자세 예시 실루엣 + 체크 포인트. 실루엣은 자세 예시일 뿐 체형 굵기는 맞추지 않음
const GC = "#5EF0FF";
function Tag({ x, y, children, anchor = "start", size = 11 }) {
  return <text x={x} y={y} textAnchor={anchor} fontSize={size} fill={GC} stroke="rgba(0,0,0,.65)" strokeWidth="3" paintOrder="stroke" fontWeight="700">{children}</text>;
}
function VArrow({ x, y1, y2 }) {
  return <g stroke={GC} strokeWidth="1.5"><line x1={x} y1={y1 + 4} x2={x} y2={y2 - 4} /><path d={`M${x - 4} ${y1 + 8} L${x} ${y1 + 2} L${x + 4} ${y1 + 8} M${x - 4} ${y2 - 8} L${x} ${y2 - 2} L${x + 4} ${y2 - 8}`} fill="none" /></g>;
}
function PoseGuide({ pose }) {
  const dash = { fill: "none", stroke: GC, strokeWidth: 1.6, strokeDasharray: "6 4" };
  const limb = { stroke: "#CFFBFF", strokeLinecap: "round", fill: "none" };
  const front = pose === "front";
  return (
    <svg className="cam-guide" viewBox="0 0 300 480" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      {/* 틀과 여백 */}
      <rect x="18" y="4" width="264" height="472" {...dash} strokeWidth="2" />
      <line x1="18" y1="40" x2="282" y2="40" {...dash} />
      <line x1="18" y1="440" x2="282" y2="440" {...dash} />
      <VArrow x={34} y1={4} y2={40} /><Tag x={44} y={26}>머리 위 여백</Tag>
      <VArrow x={34} y1={440} y2={476} /><Tag x={44} y={462}>발끝 아래 여백</Tag>
      <line x1={front ? 150 : 140} y1="4" x2={front ? 150 : 140} y2="476" {...dash} strokeWidth="1" opacity=".7" />
      <rect x="28" y="50" width={front ? 34 : 54} height="20" fill="rgba(0,0,0,.35)" stroke={GC} strokeWidth="1.4" />
      <Tag x={front ? 45 : 55} y={64} anchor="middle">{front ? "정면" : "옆으로 서기"}</Tag>

      {front ? (
        <>
          {/* 자세 예시 실루엣 (A 자세) — 그룹 투명도로 겹친 부분이 진해지지 않게 */}
          <g opacity=".32" fill="#CFFBFF">
            <ellipse cx="150" cy="66" rx="14" ry="18" />
            <path d="M143 82 h14 v14 h-14z" />
            <path d="M116 104 Q150 94 184 104 L181 160 Q173 190 177 214 L180 246 L120 246 L123 214 Q127 190 119 160 Z" />
            <g {...limb}>
              <path d="M119 108 L90 172 L62 228" strokeWidth="15" /><path d="M181 108 L210 172 L238 228" strokeWidth="15" />
              <path d="M137 240 L134 340 L133 428" strokeWidth="25" /><path d="M163 240 L166 340 L167 428" strokeWidth="25" />
            </g>
            <ellipse cx="131" cy="433" rx="10" ry="6" /><ellipse cx="169" cy="433" rx="10" ry="6" />
          </g>
          {/* 어깨 수평 */}
          <line x1="104" y1="104" x2="214" y2="104" {...dash} /><Tag x={218} y={108}>수평</Tag>
          {/* 팔과 몸통 사이 틈 */}
          <path d="M117 124 L121 222 L78 204 Z" {...dash} strokeWidth="1.2" fill="rgba(94,240,255,.14)" />
          <path d="M183 124 L179 222 L222 204 Z" {...dash} strokeWidth="1.2" fill="rgba(94,240,255,.14)" />
          <g stroke={GC} strokeWidth="1.5" fill="none"><path d="M90 200 L116 200 M94 196 L90 200 L94 204 M112 196 L116 200 L112 204" /><path d="M184 200 L210 200 M188 196 L184 200 L188 204 M206 196 L210 200 L206 204" /></g>
          <Tag x={28} y={286}>주먹 두 개</Tag><Tag x={28} y={300}>만큼 틈</Tag><path d="M58 274 L96 214" stroke={GC} strokeWidth="1.2" />
          <Tag x={272} y={286} anchor="end">주먹 두 개</Tag><Tag x={272} y={300} anchor="end">만큼 틈</Tag><path d="M242 274 L204 214" stroke={GC} strokeWidth="1.2" />
          {/* 발 위치 */}
          <rect x="117" y="421" width="28" height="22" {...dash} strokeWidth="1.2" /><rect x="155" y="421" width="28" height="22" {...dash} strokeWidth="1.2" />
        </>
      ) : (
        <>
          {/* 옆모습 실루엣 — 오른쪽을 보고 섬, 팔은 몸통 앞쪽 */}
          <g opacity=".32" fill="#CFFBFF">
            <ellipse cx="142" cy="66" rx="15" ry="18" />
            <path d="M136 82 h12 v16 h-12z" />
            <path d="M128 100 Q152 96 162 112 Q166 150 158 182 Q154 200 160 222 Q162 240 152 250 L134 250 Q124 238 128 222 Q132 200 128 182 Q122 150 128 100 Z" />
            <g {...limb}>
              <path d="M146 112 L150 176 L184 186" strokeWidth="14" />
              <path d="M140 240 L143 340 L144 428" strokeWidth="26" />
            </g>
            <ellipse cx="152" cy="433" rx="18" ry="6" />
          </g>
          {/* 바라보는 방향 */}
          <path d="M168 66 L214 66" {...dash} /><path d="M208 60 L216 66 L208 72" fill="none" stroke={GC} strokeWidth="1.6" />
          {/* 팔 위치 */}
          <ellipse cx="180" cy="184" rx="24" ry="14" {...dash} strokeWidth="1.3" fill="rgba(94,240,255,.12)" />
          <path d="M196 172 L212 150" stroke={GC} strokeWidth="1.2" /><Tag x={214} y={148}>팔은 몸통 앞쪽</Tag>
          {/* 허리·엉덩이 윤곽이 가려지지 않게 */}
          <rect x="120" y="186" width="9" height="26" {...dash} strokeWidth="1.2" />
          <rect x="118" y="222" width="9" height="26" {...dash} strokeWidth="1.2" />
          <path d="M129 198 L168 214" stroke={GC} strokeWidth="1.2" /><Tag x={170} y={218}>허리 선 가림 없이</Tag>
          <path d="M127 236 L168 254" stroke={GC} strokeWidth="1.2" /><Tag x={170} y={258}>엉덩이 선 가림 없이</Tag>
        </>
      )}
    </svg>
  );
}
// 안내 음성 — 미리 만든 신경망 음성 파일(public/voice/<목소리>/<키>.mp3, scripts/gen_voice.py)을 재생.
// 파일을 못 틀면 기기 TTS 로 같은 문장을 읽는다. 문장을 바꾸면 gen_voice.py 의 LINES 도 같이 바꾸고 다시 생성.
const FRONT = "정면을 보고 편하게 서 주세요", SIDE = "이번엔 옆으로 돌아서 주세요";
const VOICE_LINES = {
  front: FRONT + ".", side: SIDE + ".",
  timer5: "5초 뒤에 찍을게요.", timer10: "10초 뒤에 찍을게요.",   // 짧게 — "셋"에 끊기지 않게
  count3: "셋", count2: "둘", count1: "하나",
  analyze: "좋아요. 분석해 볼게요.", need_side: `정면만으로는 조금 애매해요. ${SIDE}.`,
  retake: "사진을 다시 한 번 찍어 주세요.",
};
const VOICE_DIR = `${import.meta.env.BASE_URL}voice/sunhi/`;   // 안내 목소리는 선희(여) 하나로 고정
const player = typeof Audio !== "undefined" ? new Audio() : null;
// iOS 는 사용자가 누른 순간에만 소리를 열어 준다 → 버튼 누를 때 같은 플레이어를 한 번 무음 재생해 열어 둠
function unlockAudio() {
  if (!player || player.dataset.unlocked) return;
  player.dataset.unlocked = "1"; player.muted = true; player.src = `${VOICE_DIR}count1.mp3`;
  player.play().then(() => { player.pause(); player.muted = false; }).catch(() => { player.muted = false; });
}

// 기기 TTS (음성 파일을 못 틀 때) — 신경망 음성 우선
const VOICE_RANK = [/natural|neural/i, /online/i, /premium|enhanced|향상/i, /google/i, /yuna|sunhi|injoon|hyunsu/i];
let koVoice = null;
function pickVoice() {
  const vs = window.speechSynthesis?.getVoices().filter((v) => /^ko/i.test(v.lang)) || [];
  const rank = (v) => { const i = VOICE_RANK.findIndex((re) => re.test(v.name)); return i < 0 ? VOICE_RANK.length : i; };
  koVoice = vs.sort((a, b) => rank(a) - rank(b))[0] || null;
}
if (window.speechSynthesis) { pickVoice(); window.speechSynthesis.addEventListener?.("voiceschanged", pickVoice); }
function speak(text) {
  if (!window.speechSynthesis) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ko-KR"; if (koVoice) u.voice = koVoice; u.rate = 0.95; u.pitch = 1.05;
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(u);
  } catch { /* 음성 없음 */ }
}
const speaking = () => (player && !player.paused && !player.ended) || !!window.speechSynthesis?.speaking;
function say(key, on) {
  if (!on) return;
  const text = VOICE_LINES[key]; if (!text) return;
  window.speechSynthesis?.cancel();
  if (!player) return speak(text);
  try {
    player.pause(); player.muted = false;
    player.src = `${VOICE_DIR}${key}.mp3`;
    player.play().catch(() => speak(text));
  } catch { speak(text); }
}
// 셔터 소리 — "찰칵"을 읽는 대신 짧은 효과음 (음원 파일 없이 Web Audio 로)
function shutter(on) {
  if (!on) return;
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const n = Math.floor(ac.sampleRate * 0.09), buf = ac.createBuffer(1, n, ac.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) { const t = i / n; d[i] = (Math.random() * 2 - 1) * Math.exp(-t * 18) * (i < n * 0.45 || i > n * 0.55 ? 1 : 0.2); }
    const s = ac.createBufferSource(), g = ac.createGain(); g.gain.value = 0.35;
    s.buffer = buf; s.connect(g).connect(ac.destination); s.start(); s.onended = () => ac.close();
  } catch { /* 소리 없음 */ }
}

export function Camera({ onShot, pose = "front", autoStart = false }) {
  const video = useRef(null);
  const timer = useRef(null);
  const [stream, setStream] = useState(null);
  const [err, setErr] = useState("");
  const [facing, setFacing] = useState("user");   // user 전면 · environment 후면 (휴대폰으로 남이 찍어줄 때)
  const [delay, setDelay] = useState(5);          // 촬영 타이머(초)
  const [voice, setVoice] = useState(true);
  const [count, setCount] = useState(0);          // 카운트다운 남은 초 (0 = 대기)
  const [head, sub] = POSE_GUIDE[pose];
  useEffect(() => {
    if (stream && video.current) video.current.srcObject = stream;
    return () => stream?.getTracks().forEach((t) => t.stop());   // 페이지를 떠나면 카메라 끔
  }, [stream]);
  useEffect(() => () => clearInterval(timer.current), []);
  useEffect(() => { if (autoStart) start(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  async function start(f = facing, announce = true) {
    unlockAudio();
    setErr("");
    if (!navigator.mediaDevices?.getUserMedia) return setErr("이 브라우저에서는 카메라를 쓸 수 없어요. 사진 불러오기를 이용해 주세요.");
    try {
      stream?.getTracks().forEach((t) => t.stop());
      const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: f, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
      setFacing(f); setStream(s);
      if (announce && !(pose === "side" && speaking())) say(pose, voice);   // 측면 요청 안내가 나오는 중이면 끊지 않음
    } catch (e) { setErr(e.name === "NotAllowedError" ? "카메라 권한이 거부됐어요 (주소창 자물쇠 → 카메라 허용)" : "카메라를 켤 수 없어요"); }
  }
  function capture() {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    onShot(toJpeg(v, v.videoWidth, v.videoHeight));
    shutter(voice); setTimeout(() => say("analyze", voice), 250);
    stream.getTracks().forEach((t) => t.stop()); setStream(null);
  }
  function shoot() {
    unlockAudio();
    if (!delay) return capture();
    let n = delay; setCount(n); say(`timer${n}`, voice);
    timer.current = setInterval(() => {
      n -= 1;
      if (n <= 0) { clearInterval(timer.current); setCount(0); capture(); return; }
      setCount(n); if (n <= 3) say(`count${n}`, voice);
    }, 1000);
  }
  function cancel() { clearInterval(timer.current); setCount(0); window.speechSynthesis?.cancel(); player?.pause(); }
  return (
    <div className="drop">
      {stream ? (
        <>
          <div className="cam">
            <video ref={video} autoPlay playsInline muted style={{ transform: facing === "user" ? "scaleX(-1)" : "none" }} />
            <PoseGuide pose={pose} />
            <div className="cam-msg"><b>{head}</b><span>{sub}</span></div>
            {count > 0 && <div className="cam-count">{count}</div>}
          </div>
          <div className="cam-bar">
            {count > 0
              ? <button className="btn block" onClick={cancel}>✋ 촬영 취소</button>
              : <button className="btn primary" onClick={shoot}>📸 {delay ? `${delay}초 뒤 촬영` : "바로 촬영"}</button>}
            {count === 0 && <>
              <select value={delay} onChange={(e) => setDelay(Number(e.target.value))} aria-label="타이머">
                <option value={0}>타이머 없음</option><option value={5}>5초</option><option value={10}>10초</option>
              </select>
              <button className="btn" onClick={() => setVoice(!voice)} aria-label="음성 안내">{voice ? "🔊" : "🔇"}</button>
              <button className="btn" onClick={() => start(facing === "user" ? "environment" : "user", false)} aria-label="카메라 전환">
                🔄 {facing === "user" ? "후면" : "전면"}
              </button>
            </>}
          </div>
        </>
      ) : <button className="btn block" onClick={() => start()}>📷 카메라 켜기 ({pose === "front" ? "정면" : "측면"})</button>}
      {err && <div className="err">{err}</div>}
    </div>
  );
}

// 사진 분석 단계 표시 — 교수님 요청: 시연 시나리오가 화면 메시지로 분명히 보이게
function Steps({ now, needSide }) {
  const steps = [["front", "정면 촬영"], ["analyze", "분석"], ...(needSide ? [["side", "측면 촬영"]] : []), ["done", "결과"]];
  const at = steps.findIndex(([k]) => k === now);
  return (
    <ol className="steps">
      {steps.map(([k, n], i) => <li key={k} className={i < at ? "done" : i === at ? "on" : ""}>{i < at ? "✓ " : `${i + 1}. `}{n}</li>)}
    </ol>
  );
}

// 상·하체 형태는 사진·키·몸무게 어느 것으로도 실측과 맞지 않아(code/runs/photo_calib.md) 본인 응답을 우선한다 — 평가 프로토콜 B단계의 1문항
const SHAPE_Q = [["상체형", "어깨·가슴 쪽"], ["균형", "비슷해요"], ["하체형", "골반·엉덩이 쪽"]];
function ShapeQuestion({ a, onGroup }) {
  const photo = a.res?.body?.group;
  return (
    <div className="shape-q">
      <div className="section-title">한 가지만 알려 주세요</div>
      <p className="caption">어깨·가슴과 골반·엉덩이 중 어느 쪽이 더 넓은 편인가요? 답해 주시면 사진 분석보다 우선해서 추천에 반영해요.</p>
      <div className="chips">
        {SHAPE_Q.map(([g, n]) => <button key={g} className={"chip" + (a.groupBy === "answer" && a.body.group === g ? " on" : "")} onClick={() => onGroup(g, "answer")}>{n}</button>)}
        <button className={"chip" + (a.groupBy !== "answer" ? " on" : "")} onClick={() => onGroup(photo, "photo")}>잘 모르겠어요</button>
      </div>
      {a.groupBy === "answer" && photo && photo !== a.body.group && <div className="caption">사진 분석 결과: {photo} · 응답을 기준으로 추천합니다.</div>}
    </div>
  );
}

function Result({ a, user, onRetake, onGroup, go }) {
  const r = a.res;
  const bi = bmiInfo(user.height, user.weight);
  return (
    <>
      {a.source !== "manual" && <div className="notice warn">사진 체형 분석은 시험 기능이에요. 상·하체 균형은 실측 보정 전 실험값이고, 체격은 프로필의 키·몸무게로 판단해 추천에 반영합니다.</div>}
      {a.source === "photo" && a.attire === "loose" && <div className="notice warn">헐렁한 옷이나 아우터를 입고 찍으면 몸선이 가려져 정확도가 떨어져요. 몸에 붙는 옷으로 다시 찍거나, 아래 질문에 직접 답해 주세요.</div>}
      <div className="hero-title">분석이 완료됐어요.</div>
      <div className="hero-desc">{a.source === "manual" ? "직접 선택한 체형으로 추천합니다." : a.source === "photo" ? "전신 사진을 기준으로 확인한 체형 분석 결과입니다." : "입력한 측정값으로 확인한 체형 분석 결과입니다."}</div>
      <div className="result-card">
        <div className="result-label">MY BODY TYPE</div>
        <div className="result-type">{a.label}</div>
        {a.body && <div className="result-desc">{GROUP_DESC[a.body.group]}{a.groupBy === "answer" ? "이라고 답해 주셨어요." : "으로 분석되었습니다."}</div>}
        {bi && <div className="result-desc">체격 <b>{bi.build}</b> · BMI {bi.bmi} — 프로필의 키 {user.height}cm · 몸무게 {user.weight}kg로 자동 계산</div>}
      </div>
      {a.body && (
        <>
          <div className="section-title">신체 특징</div>
          <div className="grid2">
            <div className="metric"><div className="k">상·하체 균형</div><div className="v">{a.body.group}</div></div>
            {bi && <div className="metric"><div className="k">체격</div><div className="v">{bi.build}</div></div>}
          </div>
        </>
      )}
      {a.body && a.source !== "manual" && <ShapeQuestion a={a} onGroup={onGroup} />}
      <div className="grid2" style={{ marginTop: 28, gridTemplateColumns: "minmax(0, 1fr) auto" }}>
        <button className="btn primary" onClick={() => go("recommend")}>✨ 내 코디 추천받기</button>
        <button className="btn" style={{ whiteSpace: "nowrap" }} onClick={onRetake}>📷 다시 분석</button>
      </div>
    </>
  );
}

export function Analysis({ ctx }) {
  const { user, analysis, setAnalysis, go } = ctx;
  const [mode, setMode] = useState("camera");      // camera | upload | measure | manual
  const [needSide, setNeedSide] = useState(false); // 3군집이 정면만으로 애매 → 측면 받아 5군집으로
  const [front, setFront] = useState(null);        // dataURL
  const [side, setSide] = useState(null);
  const [m, setM] = useState({ upper: "", waist: "", hip: "", stature: "", waist_depth: "", hip_depth: "" });
  const [bodyType, setBodyType] = useState("균형형");
  const [attire, setAttire] = useState(null);      // 촬영 때 입은 옷 (ATTIRE) — 고르지 않아도 분석은 됨
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const male = user.gender === "남성";
  const sex = male ? "M" : "F";

  const onGroup = (g, by) => setAnalysis({ ...analysis, groupBy: by, body: { ...analysis.body, group: g }, label: g });
  if (analysis) return <Result a={analysis} user={user} go={go} onGroup={onGroup} onRetake={() => { setAnalysis(null); setFront(null); setSide(null); setNeedSide(false); setMsg(""); }} />;

  const done = (res, source) => {
    const body = { ...res.body, build: bmiBuild(user.height, user.weight) || res.body.build };
    setAnalysis({ source, res, body, label: res.body.group, ...(source === "photo" ? { attire } : {}) });
  };

  async function runPhoto(f = front, sd = needSide ? side : null) {
    setMsg(""); if (!f) return setMsg("정면 사진을 먼저 찍거나 골라 주세요.");
    setBusy(true);
    try {
      const res = await classifyPhoto({ sex, front: f, ...(sd ? { side: sd } : {}) });
      if (res.status === "ok") done(res, "photo");
      else {
        if (res.status === "need_side") { setNeedSide(true); setSide(null); say("need_side", true); }
        else say("retake", true);
        setMsg(res.message);
      }
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  }
  // 카메라 모드: 찍자마자 분석 → 애매하면 측면 카메라가 바로 이어서 켜짐
  const shotFront = (v) => { newFront(v); runPhoto(v, null); };
  const shotSide = (v) => { setSide(v); runPhoto(front, v); };
  const step = busy ? "analyze" : needSide && !side ? "side" : "front";
  async function runMeasure() {
    setMsg("");
    const num = (v) => (v === "" ? undefined : Number(v));
    const measures = { [male ? "chest_width" : "bust_width"]: num(m.upper), waist_width: num(m.waist), hip_width: num(m.hip), stature: num(m.stature),
      ...(needSide ? { waist_depth: num(m.waist_depth), hip_depth: num(m.hip_depth) } : {}) };
    setBusy(true);
    try {
      const res = await classifyBody({ sex, measures });
      if (res.status === "ok") done(res, "measure");
      else { if (res.status === "need_side") setNeedSide(true); setMsg(res.message); }
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  }
  const newFront = (v) => { setFront(v); setSide(null); setNeedSide(false); setMsg(""); }; // 정면을 바꾸면 처음부터
  const pickFile = (set) => async (e) => {
    const f = e.target.files[0];
    if (!f) return set(null);
    try { set(await fileToJpeg(f)); } catch { setMsg("이 사진 파일을 열 수 없어요. JPG나 PNG로 다시 골라 주세요."); }
  };

  return (
    <>
      <div className="ff-page-eyebrow">FIT-FOR-U / AI BODY PROFILE</div>
      <div className="hero-title">전신 사진을<br />촬영해주세요.</div>
      <div className="hero-desc">정확한 분석을 위해 아래 촬영 가이드를 확인해주세요.</div>
      <div className="grid3" style={{ marginTop: 28 }}>
        <div className="card"><div className="card-icon">🧍</div><div className="card-label">STEP 01</div><div className="card-title">정면 촬영</div><div className="card-desc">몸을 비틀지 말고 카메라를 정면으로 바라봐주세요.</div></div>
        <div className="card"><div className="card-icon">📐</div><div className="card-label">STEP 02</div><div className="card-title">전신 확인</div><div className="card-desc">머리부터 발끝까지 사진 안에 들어오게 해주세요.</div></div>
        <div className="card"><div className="card-icon">🙆</div><div className="card-label">STEP 03</div><div className="card-title">자연스러운 자세</div><div className="card-desc">다리는 어깨너비로, 팔은 몸에서 주먹 두 개만큼 벌려 주세요.</div></div>
      </div>
      <p style={{ marginTop: 24 }}><b>촬영 기준:</b> 정면으로 서기 · 머리부터 발끝까지 보이기 · 팔을 몸통에서 주먹 두 개만큼 벌리기 · 몸에 붙는 옷 · 한 사람만</p>
      {(mode === "camera" || mode === "upload") && (
        <div className="notice attire">
          <b>👕 몸에 붙는 옷을 입고 찍어 주세요.</b> 패딩 · 코트 · 박시한 후드처럼 몸선을 가리는 옷은 어깨 · 허리 · 엉덩이 위치를 정확히 찾지 못해 결과가 틀어져요.
          <div className="chips"><span className="caption">지금 입은 옷</span>
            {ATTIRE.map(([k, n]) => <button key={k} className={"chip" + (attire === k ? " on" : "")} onClick={() => setAttire(k)}>{n}</button>)}
          </div>
          {attire === "loose" && <div className="caption">헐렁한 옷이면 정확도가 떨어질 수 있어요. 가능하면 아우터를 벗고 찍어 주세요.</div>}
        </div>
      )}

      <div className="mode">
        {[["camera", "카메라 촬영"], ["upload", "사진 불러오기"], ["measure", "측정값 입력"], ["manual", "체형 직접 선택"]].map(([k, n]) => (
          <label key={k}><input type="radio" name="mode" checked={mode === k} onChange={() => { setMode(k); setMsg(""); setNeedSide(false); setSide(null); }} />{n}</label>
        ))}
      </div>

      {mode === "camera" && (
        <div className="photo-grid">
          <div>
            <Steps now={step} needSide={needSide} />
            {msg && <div className={"cam-status" + (needSide && !side ? " side" : "")}>{msg}</div>}
            {busy ? <div className="drop analyzing">🔎 사진에서 몸의 주요 위치를 찾고 있어요…<div className="caption">처음 분석은 모델을 불러오느라 10초 정도 걸릴 수 있어요.</div></div>
              : needSide && !side ? <Camera key="side" pose="side" onShot={shotSide} autoStart />
              : <Camera key="front" pose="front" onShot={shotFront} />}
          </div>
          <div>
            <div className="photo-preview">
              {front ? <img src={front} alt="정면 사진" /> : <span className="caption">찍은 사진이 여기에 보여요</span>}
              {side && <img src={side} alt="측면 사진" style={{ maxWidth: "40%" }} />}
            </div>
            <div className="caption">찍으면 바로 분석해요. 정면만으로 애매하면 측면 사진을 한 장 더 부탁드려요. 사진은 분석에만 쓰고 서버에 저장하지 않습니다 · 사진 비율은 실측 보정 전 실험값입니다.</div>
          </div>
        </div>
      )}

      {mode === "upload" && (
        <div className="photo-grid">
          <div>
            <div className="drop">
              <div className="k">정면 사진 (필수) — 카메라로 찍거나 앨범에서 고를 수 있어요</div>
              <input type="file" accept="image/*" onChange={pickFile(newFront)} />
            </div>
            {needSide && <div className="drop">
              <div className="k">측면 사진 (추가 요청) — 옆으로 서서 전신이 나오게 찍어 주세요</div>
              <input type="file" accept="image/*" onChange={pickFile(setSide)} />
            </div>}
          </div>
          <div>
            <div className="photo-preview">
              {front ? <img src={front} alt="정면 사진" /> : <span className="caption">정면 사진이 여기에 보여요</span>}
              {side && <img src={side} alt="측면 사진" style={{ maxWidth: "40%" }} />}
            </div>
            <ul className="checklist">
              <li>{front ? "✓" : "○"} 정면 사진 {front ? "준비됨" : "필요"}</li>
              {needSide && <li>{side ? "✓" : "○"} 측면 사진 {side ? "준비됨" : "필요 (더 정확한 분석을 위해)"}</li>}
              <li>○ 전신·자세 적합성은 분석할 때 자동으로 확인합니다</li>
            </ul>
            <button className="btn primary block" onClick={() => runPhoto()} disabled={busy || !front || (needSide && !side)}>{busy ? "분석 중…" : needSide ? "✨ 측면 사진까지 분석하기" : "✨ 이 사진 분석하기"}</button>
            {busy && <div className="caption">사진에서 몸의 주요 위치를 찾고 있어요. 처음 분석은 모델을 불러오느라 10초 정도 걸릴 수 있어요.</div>}
            <div className="caption">사진은 분석에만 쓰고 서버에 저장하지 않습니다. 사진 비율은 실측 보정 전 실험값입니다.</div>
          </div>
        </div>
      )}

      {mode === "measure" && (
        <div className="center" style={{ maxWidth: 640, margin: 0 }}>
          <div className="notice warn" style={{ marginBottom: 12 }}><b>둘레가 아니라 '단면 너비'예요.</b> 줄자로 몸을 한 바퀴 두른 길이(둘레)가 아니라, 정면에서 봤을 때 몸의 좌우 폭을 직선으로 잰 값이에요. 둘레만 알고 계시면 '체형 직접 선택'을 이용해 주세요.</div>
          <div className="caption" style={{ marginBottom: 12 }}>모든 칸을 같은 단위(예: mm)로 입력해 주세요.{needSide && " 정면 값만으로 애매해 측면 값(두께)이 더 필요해요."}</div>
          <div className="grid2">
            {[["upper", "가슴 너비 (단면)", "가슴이 가장 나온 높이에서 몸의 좌우 폭"], ["waist", "허리 너비 (단면)", "가장 잘록한 곳의 좌우 폭"], ["hip", "엉덩이 너비 (단면)", "엉덩이가 가장 나온 곳의 좌우 폭"], ["stature", "키", "머리끝부터 발바닥까지"],
              ...(needSide ? [["waist_depth", "허리 두께 (옆면)", "옆에서 본 허리의 앞뒤 두께"], ["hip_depth", "엉덩이 두께 (옆면)", "옆에서 본 엉덩이의 앞뒤 두께"]] : [])].map(([k, n, h]) => (
              <label className="field" key={k}>{n}<span className="caption" style={{ display: "block", fontWeight: 400, margin: "2px 0 4px" }}>{h}</span><input type="number" inputMode="decimal" value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })} /></label>
            ))}
          </div>
          <button className="btn primary block" onClick={runMeasure} disabled={busy}>{busy ? "분석 중…" : "측정값으로 분석하기"}</button>
        </div>
      )}

      {mode === "manual" && (
        <div style={{ maxWidth: 420 }}>
          <label className="field">체형<select value={bodyType} onChange={(e) => setBodyType(e.target.value)}>{BODY_TYPES.map((b) => <option key={b}>{b}</option>)}</select></label>
          <button className="btn primary block" onClick={() => setAnalysis({ source: "manual", bodyType, label: bodyType })}>이 체형으로 추천받기</button>
        </div>
      )}
      {msg && mode !== "camera" && <div className="notice warn">{msg}</div>}
    </>
  );
}
