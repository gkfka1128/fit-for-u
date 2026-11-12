// 평가 참여 — 평가 프로토콜 §5 (md파일/평가_프로토콜.md). 운영자 휴대폰 한 대로 참가자를 차례로 받는다.
// 기록은 익명 참가자 번호로만 서버 DB 에 남고(회원 계정과 연결하지 않음), 사진은 저장하지 않고 분석 숫자만 남긴다. 분석: code/eval_study.py
import { useEffect, useState } from "react";
import { study, AuthError } from "./api.js";
import { Camera } from "./analysis.jsx";
import { ItemCard } from "./recommend.jsx";

const AGES = ["20대", "30대", "40대", "50대 이상"];
const SHAPE = [["상체", "어깨·가슴 쪽"], ["균형", "비슷해요"], ["하체", "골반·엉덩이 쪽"], ["모름", "잘 모르겠어요"]];
const TAPE = [["chest", "가슴둘레", "겨드랑이 아래, 가슴이 가장 나온 곳을 수평으로"], ["waist", "허리둘레", "가장 잘록한 곳 (남성은 배꼽 높이)"],
  ["hip", "엉덩이둘레", "엉덩이가 가장 나온 곳을 수평으로"], ["shoulder", "어깨너비", "양쪽 어깨 끝 뼈(견봉) 사이 직선"]];
const SITUATIONS = ["학교", "데이트", "출근", "친구와 약속", "운동", "여행"];
const ROUNDS = 3;
const STEPS = ["동의", "기본 정보", "줄자 실측", "사진", "A/B 비교", "설문", "완료"];

const shuffle = (xs) => xs.map((x) => [Math.random(), x]).sort((a, b) => a[0] - b[0]).map(([, x]) => x);

function Scale({ value, onChange, label }) {
  return (
    <div className="field">{label}
      <div className="scale">{[1, 2, 3, 4, 5].map((n) => (
        <button key={n} type="button" className={"chip" + (value === n ? " on" : "")} onClick={() => onChange(n)}>{n}</button>
      ))}</div>
      <div className="scale-ends caption"><span>전혀 아니다</span><span>매우 그렇다</span></div>
    </div>
  );
}

function StepBar({ now }) {
  return <ol className="steps">{STEPS.map((s, i) => <li key={s} className={i === now ? "on" : i < now ? "done" : ""}>{s}</li>)}</ol>;
}

export function Study({ ctx }) {
  const { weather: w, guard } = ctx;
  const [step, setStep] = useState(0);
  const [consent, setConsent] = useState(false);
  const [p, setP] = useState({ sex: "M", age: "20대", height: "", weight: "", answer: "" });
  const [tape, setTape] = useState({ chest: "", waist: "", hip: "", shoulder: "" });
  const [pid, setPid] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [photoMsg, setPhotoMsg] = useState("");
  const [needSide, setNeedSide] = useState(false);
  const [front, setFront] = useState(null);
  const [sits, setSits] = useState(() => shuffle(SITUATIONS).slice(0, ROUNDS));
  const [round, setRound] = useState(1);
  const [pair, setPair] = useState(null);
  const [ab, setAb] = useState({ choice: "", a: 0, b: 0 });
  const [rec, setRec] = useState(null);
  const [pick, setPick] = useState(0);
  const [sv, setSv] = useState({ wear: 0, shoes: 0, understand: 0, negative: null, comment: "" });
  const [tries, setTries] = useState(0);   // A/B·추천 불러오기 실패 시 '다시 시도' → 아래 effect 재실행
  const weather = { feels_like: w.feels_like, precip_prob: w.precip_prob };

  async function run(fn) {
    setBusy(true); setMsg("");
    try { await fn(); } catch (e) { setMsg(e.message); if (e instanceof AuthError) guard(e); }
    setBusy(false);
  }

  // 기본 정보 → 참가 시작 (형태 문항은 줄자로 재기 전에 묻는다 — 잰 값을 보고 답이 바뀌지 않게)
  const start = () => run(async () => {
    if (!p.height || !p.weight || !p.answer) throw new Error("키·몸무게와 형태 문항을 모두 입력해 주세요.");
    const d = await study.start({ consent: true, profile: { ...p, height: Number(p.height), weight: Number(p.weight) } });
    setPid(d.pid); setStep(2);
  });
  const saveTape = () => run(async () => {
    const t = Object.fromEntries(Object.entries(tape).filter(([, v]) => v !== "").map(([k, v]) => [k, Number(v)]));
    if (!Object.keys(t).length) throw new Error("값을 하나 이상 넣거나 '건너뛰기'를 눌러 주세요.");
    await study.tape(pid, t); setStep(3);
  });
  async function shot(img) {
    const isSide = needSide;
    if (!isSide) setFront(img);
    setBusy(true); setPhotoMsg("");
    try {
      const r = await study.photo(pid, isSide ? front : img, isSide ? img : null);
      if (r.status === "ok") { setPhotoMsg("분석 완료 — 결과는 실측과 비교하는 데만 씁니다."); setNeedSide(false); setTimeout(() => setStep(4), 900); }
      else if (r.status === "need_side") { setNeedSide(true); setPhotoMsg(r.message); }
      else setPhotoMsg(r.message + " 다시 찍거나 건너뛸 수 있어요.");
    } catch (e) { setPhotoMsg(e.message); }
    setBusy(false);
  }

  // A/B 한 회차 불러오기 (두 코디가 같으면 서버가 identical 로 기록 → 화면에서 바로 다음 회차)
  useEffect(() => {
    if (step !== 4 || pair) return;
    run(async () => {
      const d = await study.pair({ pid, round, situation: sits[round - 1], weather });
      setPair(d); setAb({ choice: "", a: 0, b: 0 });
    });
  }, [step, round, pair, tries]); // eslint-disable-line react-hooks/exhaustive-deps
  const nextRound = () => { if (round >= ROUNDS) { setStep(5); setPair(null); } else { setRound(round + 1); setPair(null); } };
  const answer = () => run(async () => {
    if (!ab.choice || !ab.a || !ab.b) throw new Error("어느 쪽이 더 어울리는지와 두 코디 만족도를 모두 골라 주세요.");
    await study.answer({ pid, pair_id: pair.pair_id, choice: ab.choice, score_a: ab.a, score_b: ab.b });
    nextRound();
  });

  useEffect(() => {
    if (step !== 5 || rec) return;
    run(async () => setRec(await study.recommend({ pid, situation: sits[0], weather })));
  }, [step, tries]); // eslint-disable-line react-hooks/exhaustive-deps
  const retry = !busy && msg && ((step === 4 && !pair) || (step === 5 && !rec))
    ? <button className="btn block" onClick={() => setTries((t) => t + 1)}>다시 시도</button> : null;
  const submitSurvey = () => run(async () => {
    if (!sv.wear || !sv.shoes || !sv.understand || sv.negative === null) throw new Error("모든 문항에 답해 주세요.");
    await study.survey({ pid, ...sv, comment: sv.comment.trim() }); setStep(6);
  });

  function reset() {
    setStep(0); setConsent(false); setP({ sex: "M", age: "20대", height: "", weight: "", answer: "" }); setTape({ chest: "", waist: "", hip: "", shoulder: "" });
    setPid(""); setMsg(""); setPhotoMsg(""); setNeedSide(false); setFront(null); setSits(shuffle(SITUATIONS).slice(0, ROUNDS));
    setRound(1); setPair(null); setRec(null); setPick(0); setSv({ wear: 0, shoes: 0, understand: 0, negative: null, comment: "" }); scrollTo(0, 0);
  }

  return (
    <>
      <div className="ff-page-eyebrow">FIT-FOR-U / EVALUATION</div>
      <div className="hero-title">평가 참여.</div>
      <div className="hero-desc">추천과 체형 판정이 실제로 맞는지 확인하는 테스트예요. 5~10분 걸립니다.</div>
      <StepBar now={step} />
      {pid && step < 6 && <div className="caption">참가자 번호 {pid}</div>}

      {step === 0 && (
        <div className="card">
          <div className="card-title">시작 전에 확인해 주세요</div>
          <ul className="card-desc reasons">
            <li>목적: Fit-For-U 의 체형 판정과 코디 추천이 실제로 맞는지 검증 (인공지능 과목 프로젝트)</li>
            <li>남는 것: 익명 참가자 번호, 성별·나이대·키·몸무게, 형태 문항 답, 줄자 실측값(선택), 사진 분석 숫자(선택), 응답</li>
            <li>남지 않는 것: 이름·연락처·사진 — 사진은 분석에만 쓰고 바로 버립니다</li>
            <li>원하면 언제든 그만둘 수 있고, 참가자 번호를 알려 주면 기록을 지워 드립니다</li>
          </ul>
          <label className="check"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />위 내용을 이해했고 참여에 동의합니다.</label>
          <button className="btn primary block" disabled={!consent} onClick={() => setStep(1)}>다음</button>
        </div>
      )}

      {step === 1 && (
        <>
          <div className="grid2">
            <label className="field">성별<select value={p.sex} onChange={(e) => setP({ ...p, sex: e.target.value })}><option value="M">남성</option><option value="F">여성</option></select></label>
            <label className="field">나이대<select value={p.age} onChange={(e) => setP({ ...p, age: e.target.value })}>{AGES.map((a) => <option key={a}>{a}</option>)}</select></label>
            <label className="field">키(cm)<input type="number" inputMode="decimal" value={p.height} onChange={(e) => setP({ ...p, height: e.target.value })} /></label>
            <label className="field">몸무게(kg)<input type="number" inputMode="decimal" value={p.weight} onChange={(e) => setP({ ...p, weight: e.target.value })} /></label>
          </div>
          <div className="section-title">어깨·가슴과 골반·엉덩이 중 어느 쪽이 더 넓은 편인가요?</div>
          <div className="caption">줄자로 재기 전에, 평소 느끼는 대로 골라 주세요.</div>
          <div className="chips">{SHAPE.map(([k, n]) => <button key={k} className={"chip" + (p.answer === k ? " on" : "")} onClick={() => setP((x) => ({ ...x, answer: k }))}>{n}</button>)}</div>
          <button className="btn primary block" style={{ marginTop: 20 }} disabled={busy} onClick={start}>{busy ? "시작하는 중…" : "다음"}</button>
        </>
      )}

      {step === 2 && (
        <>
          <div className="caption">줄자로 재서 cm 로 넣어 주세요. 얇은 옷 위에서, 줄자를 너무 조이지 않게. 줄자가 없으면 건너뛰어도 돼요.</div>
          <div className="grid2">
            {TAPE.map(([k, n, how]) => (
              <label className="field" key={k}>{n} (cm)<input type="number" inputMode="decimal" value={tape[k]} onChange={(e) => setTape({ ...tape, [k]: e.target.value })} />
                <span className="caption">{how}</span></label>
            ))}
          </div>
          <div className="grid2" style={{ marginTop: 16 }}>
            <button className="btn primary" disabled={busy} onClick={saveTape}>저장하고 다음</button>
            <button className="btn" onClick={() => setStep(3)}>건너뛰기</button>
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <div className="caption">앱과 같은 방법으로 정면 사진을 한 장 찍어요. 사진 판정이 실측과 맞는지 비교하는 용도이고, 사진은 저장하지 않습니다.</div>
          {busy ? <div className="drop analyzing">🔎 분석 중…</div>
            : needSide ? <Camera key="side" pose="side" onShot={shot} autoStart /> : <Camera key="front" pose="front" onShot={shot} />}
          {photoMsg && <div className="notice">{photoMsg}</div>}
          <button className="btn block" style={{ marginTop: 12 }} onClick={() => setStep(4)}>사진 건너뛰기</button>
        </>
      )}

      {step === 4 && (
        <>
          <div className="section-title">{round} / {ROUNDS}회차 · {sits[round - 1]} · 체감 {w.feels_like}°</div>
          <div className="caption">두 코디 중 하나만 체형을 고려했어요 (어느 쪽인지는 숨김). 내 체형에 더 잘 어울리는 쪽을 골라 주세요.</div>
          {!pair ? (retry || <div className="caption">코디를 고르는 중…</div>) : pair.identical ? (
            <>
              <div className="notice">이번 조건에서는 두 코디가 같았어요 (체형 규칙이 결과를 바꾸지 않음). 기록했어요.</div>
              <button className="btn primary block" onClick={nextRound}>다음</button>
            </>
          ) : (
            <>
              <div className="grid2 ab">
                {[["A", pair.A], ["B", pair.B]].map(([tag, items]) => (
                  <div key={tag}><div className="ab-tag">코디 {tag}</div>{items.map((c, j) => <ItemCard key={`${pair.pair_id}-${tag}-${j}-${c.category}`} c={c} />)}</div>
                ))}
              </div>
              <div className="field">내 체형에 더 잘 어울리는 쪽은?</div>
              <div className="chips">{[["A", "A"], ["same", "비슷해요"], ["B", "B"]].map(([k, n]) => (
                <button key={k} className={"chip" + (ab.choice === k ? " on" : "")} onClick={() => setAb((x) => ({ ...x, choice: k }))}>{n}</button>
              ))}</div>
              <Scale label="코디 A 만족도" value={ab.a} onChange={(v) => setAb((x) => ({ ...x, a: v }))} />
              <Scale label="코디 B 만족도" value={ab.b} onChange={(v) => setAb((x) => ({ ...x, b: v }))} />
              <button className="btn primary block" disabled={busy} onClick={answer}>{round >= ROUNDS ? "제출하고 설문으로" : "제출하고 다음 회차"}</button>
            </>
          )}
        </>
      )}

      {step === 5 && (
        <>
          <div className="section-title">평소처럼 추천받은 코디 3안</div>
          <div className="caption">{sits[0]} · 체감 {w.feels_like}° 기준이에요. 세 코디를 넘겨 본 뒤 답해 주세요.</div>
          {!rec && retry}
          {rec && (
            <>
              <div className="tabs">{rec.outfits.map((_, i) => <button key={i} className={"tab" + (pick === i ? " on" : "")} onClick={() => setPick(i)}>추천 {i + 1}</button>)}</div>
              <div className="grid4">{rec.outfits[pick].items.map((c, j) => <ItemCard key={`${pick}-${j}-${c.category}`} c={c} />)}</div>
              <ul className="card-desc reasons">{(rec.outfits[pick].why || []).map((x, i) => <li key={i}>{x.text}</li>)}</ul>
            </>
          )}
          <Scale label="오늘 이 추천을 입겠다" value={sv.wear} onChange={(v) => setSv((x) => ({ ...x, wear: v }))} />
          <Scale label="추천 신발을 신겠다" value={sv.shoes} onChange={(v) => setSv((x) => ({ ...x, shoes: v }))} />
          <Scale label="왜 이 추천인지 이해됐다" value={sv.understand} onChange={(v) => setSv((x) => ({ ...x, understand: v }))} />
          <div className="field">결과를 보고 기분이 나빴던 부분이 있었나요?</div>
          <div className="chips">{[[false, "아니요"], [true, "예"]].map(([k, n]) => (
            <button key={n} className={"chip" + (sv.negative === k ? " on" : "")} onClick={() => setSv((x) => ({ ...x, negative: k }))}>{n}</button>
          ))}</div>
          <label className="field">자유 의견 (선택)<textarea maxLength={300} value={sv.comment} onChange={(e) => setSv((x) => ({ ...x, comment: e.target.value }))} placeholder="좋았던 점, 이상했던 점" /></label>
          <button className="btn primary block" disabled={busy} onClick={submitSurvey}>제출</button>
        </>
      )}

      {step === 6 && (
        <div className="card">
          <div className="card-title">참여해 주셔서 감사합니다 🙏</div>
          <div className="card-desc">참가자 번호 <b>{pid}</b> — 기록 삭제를 원하면 이 번호를 알려 주세요.</div>
          <button className="btn primary block" style={{ marginTop: 16 }} onClick={reset}>다음 참가자 시작</button>
        </div>
      )}
      {msg && <div className="err">{msg}</div>}
    </>
  );
}
