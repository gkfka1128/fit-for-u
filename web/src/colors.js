// 색 선택 칩용 — 이름은 서버(members.COLORS · tpo.ALL_COLORS)와 같아야 한다. 색값은 화면 표시용(tint.py 의 실제 옷 톤과 맞춤)
export const COLOR_HEX = {
  블랙: "#232326", 화이트: "#f4f3ee", 그레이: "#8c8e92", 실버: "#c0c2c6", 네이비: "#26345c", 블루: "#506c94", 스카이블루: "#9bb7d0", 민트: "#a5cbbc",
  그린: "#54735a", 카키: "#6e7046", 베이지: "#d7c4a5", 브라운: "#6e4b32", 레드: "#9e3438", 와인: "#6e1e2d", 핑크: "#daacb4", 라벤더: "#b6aacc",
  퍼플: "#644c7c", 옐로우: "#dec676", 오렌지: "#c88052", 골드: "#bca062", 네온: "#c4de78",
};
export const COLOR_NAMES = Object.keys(COLOR_HEX);
export const PERSONALS = ["모름", "봄웜", "여름쿨", "가을웜", "겨울쿨"];   // "모름" = 서버에는 빈 문자열
export const HAIRS = ["선택 안 함", "짧은 머리", "단발·중간", "긴 머리"];
