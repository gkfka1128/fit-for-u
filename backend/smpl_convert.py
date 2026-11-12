"""
SMPL pkl(파이썬2·chumpy 의존) → hmr2 가 읽는 SMPL_NEUTRAL.pkl (순수 numpy) 변환.  chumpy 는 py3.11 에 설치가 안 돼 스텁으로 대신한다.

  .\.venv\Scripts\python.exe smpl_convert.py    # data/basicModel_neutral_lbs_10_207_0_v1.0.0.pkl → ~/.cache/4DHumans/data/smpl/SMPL_NEUTRAL.pkl
"""
import os, sys, pickle, types
import numpy as np

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl")
DST = os.path.join(os.path.expanduser("~"), ".cache", "4DHumans", "data", "smpl", "SMPL_NEUTRAL.pkl")

class _Ch:                                    # chumpy.Ch 스텁: 상태 dict 만 보관
    def __setstate__(self, state): self.__dict__.update(state)
def _stub():
    for name in ("chumpy", "chumpy.ch", "chumpy.ch_ops", "chumpy.reordering"):
        m = types.ModuleType(name); sys.modules[name] = m
    sys.modules["chumpy"].Ch = _Ch; sys.modules["chumpy.ch"].Ch = _Ch
    for n in ("add", "sub", "mul", "div", "neg", "reshape", "transpose"): setattr(sys.modules["chumpy.ch_ops"], n, _Ch); setattr(sys.modules["chumpy.reordering"], n, _Ch)

def to_np(v):
    if isinstance(v, _Ch):
        for k in ("x", "_x", "r"):
            if k in v.__dict__: return np.asarray(v.__dict__[k])
        arrs = [a for a in v.__dict__.values() if isinstance(a, np.ndarray)]
        if arrs: return arrs[0]
        raise ValueError(f"chumpy 값 추출 실패: {list(v.__dict__)}")
    return v

def main():
    _stub()
    with open(SRC, "rb") as f: d = pickle.load(f, encoding="latin1")
    out = {k: to_np(v) for k, v in d.items()}
    for k, v in out.items(): print(f"  {k}: {type(v).__name__} {getattr(v, 'shape', '')}")
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "wb") as f: pickle.dump(out, f)
    print("saved", DST)

if __name__ == "__main__":
    main()
