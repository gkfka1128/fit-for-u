# 촬영 안내 음성 파일 만들기 — edge-tts (Microsoft 신경망 음성). 안내 문장이 바뀌면 다시 돌린다.
#   pip install edge-tts   (프로젝트 venv 말고 따로 둔 환경 권장)
#   python scripts/gen_voice.py            → public/voice/<목소리>/<키>.mp3
# 문장은 src/analysis.jsx 의 VOICE_LINES 와 같아야 한다 (키 이름으로 연결).
import asyncio, json, os
import edge_tts

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "public", "voice")
VOICES = {"sunhi": "ko-KR-SunHiNeural"}   # 안내 목소리는 선희(여) 하나
FRONT, SIDE = "정면을 보고 편하게 서 주세요", "이번엔 옆으로 돌아서 주세요"
LINES = {
    "front": FRONT + ".",
    "side": SIDE + ".",
    "timer5": "5초 뒤에 찍을게요.",      # 짧게 — 5초 타이머의 "셋"에 끊기지 않게 (자세 안내는 카메라 켤 때 읽음)
    "timer10": "10초 뒤에 찍을게요.",
    "count3": "셋", "count2": "둘", "count1": "하나",
    "analyze": "좋아요. 분석해 볼게요.",
    "need_side": f"정면만으로는 조금 애매해요. {SIDE}.",
    "retake": "사진을 다시 한 번 찍어 주세요.",
}


async def main():
    for vk, vname in VOICES.items():
        d = os.path.join(OUT, vk); os.makedirs(d, exist_ok=True)
        for k, text in LINES.items():
            await edge_tts.Communicate(text, vname, rate="-4%").save(os.path.join(d, k + ".mp3"))
        print(vk, "ok")
    json.dump({"voices": list(VOICES), "lines": LINES}, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

asyncio.run(main())
