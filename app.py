# -*- coding: utf-8 -*-
"""
app.py
------
건강검진 AI 병원 추천 시스템 (환자용 웹앱)

플로우
1. 지역 / 검진유형 / 필수 장비 / 검사항목 체크리스트 입력
2. "AI 병원 추천" 버튼 클릭 -> 규칙기반 필터링+스코어링으로 후보 산출
3. 상위 후보 카드 표시 (개별 AI 추천 이유는 펼치기 형태로 지연 생성 - API 비용 절약)
4. 최대 3개 병원 선택 -> "AI 비교 분석" -> Gemini가 차별점 비교 총평 생성
"""

import streamlit as st
from pathlib import Path

from database import (
    get_connection,
    init_schema,
    load_exam_item_master,
    get_full_hospital_data,
    EQUIPMENT_TYPES,
    CHECKUP_TYPE_NAMES,
    EXAM_ITEM_MASTER,
)
from sample_data import populate_sample_data
from scoring_engine import PatientRequest, recommend, PRICE_BANDS
from korea_regions import REGION_MAP, SIDO_LIST
import ai_advisor


# ---------------------------------------------------------------------------
# 초기화
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="건강검진 AI 병원 추천",
    page_icon="🏥",
    layout="wide",
)

# 이 파일이 앱 코드와 같은 폴더(=git 리포지토리)에 존재하면, 샘플 데이터 대신
# 이 엑셀 내용으로 DB를 자동 구축합니다. 즉, "엑셀을 git에 올리기만 하면"
# 별도 터미널 작업 없이 Streamlit Cloud에서도 그대로 반영됩니다.
EXCEL_DATA_PATH = Path(__file__).parent / "병원데이터_템플릿.xlsx"


@st.cache_resource
def _bootstrap_db():
    """
    DB 초기화.
    - 엑셀 데이터 파일이 존재하면: 그 내용으로 DB를 새로 구축 (엑셀이 원본)
    - 없으면: 샘플 데이터로 데모 동작
    앱이 새로 시작될 때마다(캐시가 초기화될 때마다) 다시 실행되므로,
    엑셀 파일을 갱신하고 재배포하면 항상 최신 데이터로 반영됩니다.
    """
    if EXCEL_DATA_PATH.exists():
        from excel_to_db import load_excel_to_db
        result = load_excel_to_db(str(EXCEL_DATA_PATH))
        return {"source": "excel", "warnings": result["warnings"]}
    else:
        populate_sample_data()
        return {"source": "sample", "warnings": []}


@st.cache_data(ttl=60)
def _load_hospitals():
    conn = get_connection()
    init_schema(conn)
    load_exam_item_master(conn)
    data = get_full_hospital_data(conn)
    conn.close()
    return data


_bootstrap_result = _bootstrap_db()
all_hospitals = _load_hospitals()

# 검사항목 카테고리별 그룹핑
items_by_category = {}
for category, item_name in EXAM_ITEM_MASTER:
    items_by_category.setdefault(category, []).append(item_name)


# ---------------------------------------------------------------------------
# 세션 상태 초기화
# ---------------------------------------------------------------------------

if "results" not in st.session_state:
    st.session_state.results = None
if "patient_request" not in st.session_state:
    st.session_state.patient_request = None
if "ai_reasons" not in st.session_state:
    st.session_state.ai_reasons = {}  # hospital_id -> 추천이유 텍스트 캐시
if "compare_result_text" not in st.session_state:
    st.session_state.compare_result_text = None


# ---------------------------------------------------------------------------
# 헤더
# ---------------------------------------------------------------------------

st.title("🏥 건강검진 AI 병원 추천")
st.caption(
    "지역, 검진유형, 보유 장비, 검사항목을 체크하시면 AI가 조건에 맞는 "
    "건강검진기관을 비교·추천해드립니다."
)

gemini_ready = ai_advisor._get_api_key() is not None
if not gemini_ready:
    st.info(
        "ℹ️ 현재 Gemini API 키가 설정되지 않아 AI 추천 이유는 규칙기반 요약으로 대체됩니다. "
        "`.streamlit/secrets.toml`에 `GEMINI_API_KEY`를 등록하면 자연어 AI 설명이 활성화됩니다.",
        icon="ℹ️",
    )

if _bootstrap_result["source"] == "sample":
    st.caption("📎 현재 데모용 샘플 병원 데이터로 동작 중입니다. (병원데이터_템플릿.xlsx 파일이 없음)")
elif _bootstrap_result["warnings"]:
    with st.expander(f"⚠️ 엑셀 데이터 적재 경고 {len(_bootstrap_result['warnings'])}건 (클릭해서 확인)"):
        for w in _bootstrap_result["warnings"]:
            st.write("-", w)

st.divider()


# ---------------------------------------------------------------------------
# STEP 1~4: 체크리스트 입력 폼
# ---------------------------------------------------------------------------

# 지역 선택은 폼 밖에 배치합니다. st.form 안의 위젯은 제출 버튼을 누르기 전까지
# 화면이 다시 그려지지 않아서, 시/도를 바꿔도 시/군/구 목록이 즉시 갱신되지
# 않는 문제가 있었습니다. 폼 밖에 두면 시/도 선택 즉시 하위 목록이 갱신됩니다.
st.subheader("STEP 1. 희망 지역")
st.caption("전국 17개 시/도 및 소속 시/군/구를 모두 선택할 수 있습니다.")
col1, col2 = st.columns(2)
with col1:
    region_si = st.selectbox("시/도", options=SIDO_LIST, key="region_si_select")
with col2:
    gu_options = ["전체"] + REGION_MAP[region_si]
    region_gu_choice = st.selectbox("시/군/구 (선택)", options=gu_options, key="region_gu_select")
    region_gu = None if region_gu_choice == "전체" else region_gu_choice

st.divider()

# ---------------------------------------------------------------------------
# STEP 2~4: 체크리스트 입력 폼
# ---------------------------------------------------------------------------

with st.form("checklist_form"):
    st.subheader("STEP 2. 검진 유형")
    checkup_type = st.radio(
        "받고자 하는 검진 유형을 선택하세요.",
        options=CHECKUP_TYPE_NAMES,
        horizontal=True,
    )

    st.subheader("STEP 3. 예산대 (선택사항)")
    st.caption(
        "관심있는 가격대를 체크하세요. 여러 개 선택 가능하며, 아무것도 선택하지 "
        "않으면 가격과 무관하게 전체 결과를 확인할 수 있습니다."
    )
    price_cols = st.columns(4)
    price_bands = set()
    for i, (label, _lo, _hi) in enumerate(PRICE_BANDS):
        with price_cols[i % 4]:
            if st.checkbox(label, key=f"price_{label}"):
                price_bands.add(label)

    st.subheader("STEP 4. 보유 장비 (선택사항)")
    st.caption(
        "특정 장비가 꼭 필요하신 경우에만 체크하세요. 아무것도 선택하지 않아도 "
        "전체 병원 결과를 확인할 수 있습니다. (체크 시 해당 장비를 모두 보유한 병원만 표시됩니다)"
    )
    equipment_cols = st.columns(3)
    required_equipment = set()
    for i, eq in enumerate(EQUIPMENT_TYPES):
        with equipment_cols[i % 3]:
            if st.checkbox(eq, key=f"eq_{eq}"):
                required_equipment.add(eq)

    st.subheader("STEP 5. 세부 검사항목")
    st.caption("원하는 검사항목을 체크하세요. (많이 체크할수록 커버리지 기준 추천이 정교해집니다)")
    required_exam_items = set()
    for category, items in items_by_category.items():
        with st.expander(f"📋 {category}", expanded=False):
            item_cols = st.columns(2)
            for i, item in enumerate(items):
                with item_cols[i % 2]:
                    if st.checkbox(item, key=f"item_{item}"):
                        required_exam_items.add(item)

    submitted = st.form_submit_button("🔍 AI 병원 추천 받기", use_container_width=True, type="primary")

if submitted:
    req = PatientRequest(
        region_si=region_si,
        region_gu=region_gu,
        checkup_type=checkup_type,
        required_equipment=required_equipment,
        required_exam_items=required_exam_items,
        price_bands=price_bands,
    )
    with st.spinner("조건에 맞는 병원을 분석하는 중입니다..."):
        results = recommend(all_hospitals, req, top_n=5)

    st.session_state.results = results
    st.session_state.patient_request = req
    st.session_state.ai_reasons = {}
    st.session_state.compare_result_text = None


# ---------------------------------------------------------------------------
# 결과 표시
# ---------------------------------------------------------------------------

st.divider()

if st.session_state.results is not None:
    results = st.session_state.results
    req = st.session_state.patient_request

    if not results:
        st.warning(
            "조건에 맞는 병원이 없습니다. 필수 장비, 예산대 선택을 줄이거나 "
            "구/군 조건을 '전체'로 변경해서 다시 시도해보세요.",
            icon="⚠️",
        )
    else:
        st.subheader(f"📊 추천 결과 (총 {len(results)}곳)")

        # 비교용 선택 상자
        compare_targets = st.multiselect(
            "🔎 비교하고 싶은 병원을 최대 3곳 선택하세요.",
            options=[hs.hospital["name"] for hs in results],
            max_selections=3,
        )

        for rank, hs in enumerate(results, start=1):
            h = hs.hospital
            with st.container(border=True):
                top_col1, top_col2 = st.columns([3, 1])
                with top_col1:
                    st.markdown(f"### {rank}위. {h['name']}")
                    st.caption(f"📍 {h['address']}   |   📞 {h['phone']}")
                with top_col2:
                    st.metric("종합 적합도", f"{hs.total_score:.1f}점")

                # 점수 세부내역
                with st.expander("점수 세부내역 보기"):
                    for label, score in hs.breakdown.items():
                        st.write(f"- {label}: {score}점")

                badge_cols = st.columns(4)
                with badge_cols[0]:
                    st.write("**보유 장비**")
                    st.write(", ".join(sorted(h["equipment_set"])) or "정보 없음")
                with badge_cols[1]:
                    st.write("**인증**")
                    st.write(", ".join(h["certifications"]) or "없음")
                with badge_cols[2]:
                    price = hs.price_range
                    st.write(f"**{req.checkup_type} 가격대**")
                    st.write(f"{price[0]:,}원 ~ {price[1]:,}원" if price else "정보 없음")
                with badge_cols[3]:
                    st.write("**요청 항목 충족**")
                    total_req = len(req.required_exam_items) or 1
                    st.write(f"{len(hs.matched_exam_items)} / {len(req.required_exam_items)}개")

                if hs.missing_exam_items:
                    st.warning(
                        f"⚠️ 미충족 항목: {', '.join(sorted(hs.missing_exam_items))}",
                        icon="⚠️",
                    )

                # AI 추천 이유 (지연 생성 - 버튼 클릭 시에만 API 호출)
                reason_key = h["id"]
                if reason_key in st.session_state.ai_reasons:
                    st.info(f"🤖 **AI 추천 이유**: {st.session_state.ai_reasons[reason_key]}")
                else:
                    if st.button(f"🤖 AI 추천 이유 보기", key=f"reason_btn_{h['id']}"):
                        with st.spinner("AI가 분석 중입니다..."):
                            reason = ai_advisor.generate_single_reason(hs, req)
                        st.session_state.ai_reasons[reason_key] = reason
                        st.rerun()

        # -----------------------------------------------------------------
        # 병원 비교 분석
        # -----------------------------------------------------------------
        st.divider()
        st.subheader("⚖️ 선택 병원 AI 비교 분석")

        if len(compare_targets) < 2:
            st.caption("비교하려면 병원을 2곳 이상 선택하세요.")
        else:
            selected_scores = [hs for hs in results if hs.hospital["name"] in compare_targets]

            # 비교 테이블
            table_rows = []
            for hs in selected_scores:
                h = hs.hospital
                price = hs.price_range
                table_rows.append(
                    {
                        "병원명": h["name"],
                        "종합점수": hs.total_score,
                        "가격대": f"{price[0]:,}~{price[1]:,}원" if price else "-",
                        "보유장비 수": len(h["equipment_set"]),
                        "요청항목 충족": f"{len(hs.matched_exam_items)}/{len(req.required_exam_items) or 0}",
                        "인증": ", ".join(h["certifications"]) or "-",
                    }
                )
            st.table(table_rows)

            if st.button("🤖 AI 비교 총평 생성", type="primary"):
                with st.spinner("AI가 병원 간 차이를 분석 중입니다..."):
                    st.session_state.compare_result_text = ai_advisor.generate_comparison(
                        selected_scores, req
                    )

            if st.session_state.compare_result_text:
                st.success(st.session_state.compare_result_text)
else:
    st.caption("체크리스트를 입력하고 'AI 병원 추천 받기' 버튼을 눌러주세요.")


# ---------------------------------------------------------------------------
# 푸터 / 데이터 출처 안내 (실무 신뢰도용)
# ---------------------------------------------------------------------------
st.divider()
with st.expander("ℹ️ 데이터 안내"):
    st.write(
        """
        - 본 데모는 구조 검증을 위한 **샘플 데이터**로 동작합니다.
        - 실제 서비스 적용 시 국민건강보험공단 공공데이터포털의 '건강검진기관 지정 현황'
          데이터를 기초로 하고, 보유 장비/검사항목 커버리지는 병원 조사를 통해 검증된
          데이터로 교체하는 것을 권장합니다.
        - 표시되는 가격은 병원 정책에 따라 실시간으로 변동될 수 있으니, 실제 예약 전
          병원에 직접 확인하시기 바랍니다.
        """
    )
