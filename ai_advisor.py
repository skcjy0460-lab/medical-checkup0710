# -*- coding: utf-8 -*-
"""
ai_advisor.py
-------------
Gemini API(google-genai SDK)를 이용해
1) 개별 병원에 대한 "AI 추천 이유"
2) 상위 후보 병원들 간의 "AI 비교 총평/차별점"
을 생성하는 모듈.

API 키는 Streamlit secrets(st.secrets["GEMINI_API_KEY"]) 또는
환경변수 GEMINI_API_KEY에서 읽습니다. 키가 없으면 예외를 던지지 않고
app.py 쪽에서 안내 메시지를 보여줄 수 있도록 None을 반환합니다.
"""

import os
import json
from typing import List, Optional

MODEL_NAME = "gemini-2.5-flash"


def _get_api_key() -> Optional[str]:
    try:
        import streamlit as st
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY")


def _get_client():
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception:
        return None


def generate_single_reason(hospital_score, patient_request) -> str:
    """
    개별 병원에 대한 2~3문장짜리 추천 이유 생성.
    hospital_score: scoring_engine.HospitalScore
    patient_request: scoring_engine.PatientRequest
    """
    client = _get_client()
    if client is None:
        return _fallback_single_reason(hospital_score)

    h = hospital_score.hospital
    prompt = f"""
당신은 건강검진 병원 추천 전문가입니다. 아래 데이터를 참고해서 환자에게
이 병원을 추천하는 이유를 자연스러운 한국어 2~3문장으로 작성하세요.
과장하지 말고, 데이터에 근거한 사실만 언급하세요. 마케팅 문구처럼 쓰지 마세요.

[환자 요청]
- 지역: {patient_request.region_si} {patient_request.region_gu or ''}
- 검진유형: {patient_request.checkup_type}
- 필수 장비: {', '.join(patient_request.required_equipment) or '없음'}
- 요청 검사항목 수: {len(patient_request.required_exam_items)}개

[병원 정보]
- 이름: {h['name']}
- 위치: {h['region_si']} {h['region_gu']}
- 설립연도: {h['established_year']}
- 인증: {', '.join(h['certifications']) or '없음'}
- 보유 장비: {', '.join(sorted(h['equipment_set']))}
- 요청 항목 중 충족: {len(hospital_score.matched_exam_items)}개 / 미충족: {len(hospital_score.missing_exam_items)}개
- 종합 점수: {hospital_score.total_score}/100
- 점수 세부내역: {json.dumps(hospital_score.breakdown, ensure_ascii=False)}

출력은 설명 문장만 작성하고, 제목이나 불릿포인트는 넣지 마세요.
"""
    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = (response.text or "").strip()
        return text if text else _fallback_single_reason(hospital_score)
    except Exception:
        return _fallback_single_reason(hospital_score)


def generate_comparison(hospital_scores: List, patient_request) -> str:
    """
    상위 후보 병원들(최대 5개) 간의 차이점을 비교하는 총평 생성.
    표 형태가 아닌, 핵심 차별점을 짚어주는 서술형으로 작성.
    """
    client = _get_client()
    if client is None:
        return _fallback_comparison(hospital_scores)

    hospital_summaries = []
    for hs in hospital_scores:
        h = hs.hospital
        hospital_summaries.append(
            {
                "이름": h["name"],
                "위치": f"{h['region_si']} {h['region_gu']}",
                "점수": hs.total_score,
                "보유장비": sorted(h["equipment_set"]),
                "가격범위": hs.price_range,
                "인증": h["certifications"],
                "미충족항목수": len(hs.missing_exam_items),
            }
        )

    prompt = f"""
당신은 건강검진 병원 비교 전문가입니다. 아래 병원 데이터를 비교해서
환자가 병원 간 차이를 한눈에 이해할 수 있도록 한국어로 비교 총평을 작성하세요.

작성 규칙:
- 4~6문장 정도의 서술형으로 작성 (표나 불릿 금지)
- 가격, 보유장비의 폭, 검사항목 충족도, 인증 여부 등 실질적 차이를 근거로 설명
- 특정 병원이 무조건 낫다고 단정하지 말고, "이런 조건을 중요하게 생각한다면 A가,
  다른 조건을 중요하게 생각한다면 B가 적합하다"는 식으로 균형있게 서술
- 과장된 마케팅 표현 금지

[환자 요청 조건]
- 검진유형: {patient_request.checkup_type}
- 필수 장비: {', '.join(patient_request.required_equipment) or '없음'}

[비교 대상 병원 데이터]
{json.dumps(hospital_summaries, ensure_ascii=False, indent=2)}
"""
    try:
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        text = (response.text or "").strip()
        return text if text else _fallback_comparison(hospital_scores)
    except Exception:
        return _fallback_comparison(hospital_scores)


# ---------------------------------------------------------------------------
# Gemini API 키가 없거나 호출 실패 시 사용할 규칙기반 폴백 (앱이 죽지 않도록)
# ---------------------------------------------------------------------------

def _fallback_single_reason(hospital_score) -> str:
    h = hospital_score.hospital
    return (
        f"{h['name']}은(는) 요청하신 검사항목 중 {len(hospital_score.matched_exam_items)}개를 충족하며, "
        f"종합 적합도 {hospital_score.total_score}점으로 평가되었습니다. "
        f"보유 장비: {', '.join(sorted(h['equipment_set'])) or '정보 없음'}. "
        f"(AI 설명 생성을 사용하려면 Gemini API 키를 설정해주세요.)"
    )


def _fallback_comparison(hospital_scores: List) -> str:
    lines = []
    for hs in hospital_scores:
        h = hs.hospital
        price = hs.price_range
        price_str = f"{price[0]:,}~{price[1]:,}원" if price else "가격정보 없음"
        lines.append(f"- {h['name']}: 점수 {hs.total_score}점, 가격 {price_str}")
    return (
        "AI 비교 설명을 사용하려면 Gemini API 키를 설정해주세요. "
        "아래는 규칙기반 요약입니다.\n" + "\n".join(lines)
    )
