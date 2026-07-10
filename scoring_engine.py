# -*- coding: utf-8 -*-
"""
scoring_engine.py
------------------
환자 체크리스트(지역/검진유형/필수장비/검사항목) 입력을 받아
1) 하드 필터(반드시 충족해야 하는 조건)로 후보 병원을 걸러내고
2) 소프트 스코어링(0~100점)으로 순위를 매기는 모듈.

하드 필터 vs 소프트 스코어링을 나눈 이유
- "PET-CT 있는 병원만 보고 싶다"는 요청은 있으면 좋은 게 아니라 없으면 안 되는
  조건이므로 하드 필터로 처리하는 것이 사용자 신뢰도 측면에서 맞습니다.
- 반면 "검사항목을 얼마나 많이 커버하는가", "가격이 저렴한가" 등은 상대적 우열이므로
  점수화해서 랭킹으로 보여주는 것이 적절합니다.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional


# 스코어링 가중치 (합계 100점). 운영하면서 A/B테스트로 조정 가능하도록 상수로 분리.
WEIGHT_REGION_PROXIMITY = 20      # 구/군까지 정확히 일치하는지
WEIGHT_EXAM_COVERAGE = 40         # 요청한 검사항목을 얼마나 커버하는지
WEIGHT_EQUIPMENT_RICHNESS = 15    # 필수장비 외에 추가로 보유한 고가장비 (진단 폭)
WEIGHT_CERTIFICATION = 10         # 인증/신뢰도
WEIGHT_PRICE_COMPETITIVENESS = 15 # 필터링된 후보군 내에서 가격 경쟁력 (상대평가)


@dataclass
class PatientRequest:
    region_si: str
    region_gu: Optional[str]                 # None이면 시/도 전체 대상
    checkup_type: str
    required_equipment: Set[str] = field(default_factory=set)
    required_exam_items: Set[str] = field(default_factory=set)


@dataclass
class HospitalScore:
    hospital: dict
    total_score: float
    breakdown: Dict[str, float]
    matched_exam_items: Set[str]
    missing_exam_items: Set[str]
    extra_equipment: Set[str]
    price_range: Optional[tuple]  # (min_price, max_price) for 요청 검진유형


def _hard_filter(hospitals: List[dict], req: PatientRequest) -> List[dict]:
    """반드시 충족해야 하는 조건으로 후보군 축소"""
    candidates = []
    for h in hospitals:
        if h["region_si"] != req.region_si:
            continue
        if req.region_gu and h["region_gu"] != req.region_gu:
            continue
        if req.checkup_type not in h["checkup_types"]:
            continue
        if req.required_equipment and not req.required_equipment.issubset(h["equipment_set"]):
            continue
        candidates.append(h)
    return candidates


def _score_price(hospitals: List[dict], req: PatientRequest) -> Dict[int, float]:
    """
    필터링된 후보군 내에서 상대적 가격 경쟁력 점수 계산.
    가장 저렴한 곳이 만점(WEIGHT_PRICE_COMPETITIVENESS), 가장 비싼 곳이 최저점.
    후보가 1곳뿐이면 만점 처리.
    """
    prices = {}
    for h in hospitals:
        detail = h["checkup_detail"].get(req.checkup_type)
        if detail and detail["max_price"] is not None:
            prices[h["id"]] = detail["max_price"]

    if not prices:
        return {h["id"]: WEIGHT_PRICE_COMPETITIVENESS * 0.5 for h in hospitals}

    min_p, max_p = min(prices.values()), max(prices.values())
    scores = {}
    for h in hospitals:
        if h["id"] not in prices:
            scores[h["id"]] = WEIGHT_PRICE_COMPETITIVENESS * 0.5
            continue
        if max_p == min_p:
            scores[h["id"]] = WEIGHT_PRICE_COMPETITIVENESS
        else:
            # 저렴할수록 높은 점수 (선형 역비례)
            ratio = 1 - (prices[h["id"]] - min_p) / (max_p - min_p)
            scores[h["id"]] = WEIGHT_PRICE_COMPETITIVENESS * ratio
    return scores


def recommend(
    hospitals: List[dict],
    req: PatientRequest,
    top_n: int = 5,
) -> List[HospitalScore]:
    """메인 추천 함수: 필터링 -> 스코어링 -> 정렬 -> 상위 N개 반환"""

    candidates = _hard_filter(hospitals, req)
    if not candidates:
        return []

    price_scores = _score_price(candidates, req)

    results = []
    for h in candidates:
        breakdown = {}

        # 1) 지역 근접성
        if req.region_gu:
            region_score = WEIGHT_REGION_PROXIMITY if h["region_gu"] == req.region_gu else WEIGHT_REGION_PROXIMITY * 0.6
        else:
            region_score = WEIGHT_REGION_PROXIMITY  # 구 미지정 시 만점 처리
        breakdown["지역 적합도"] = round(region_score, 1)

        # 2) 검사항목 커버리지
        matched_items = req.required_exam_items & h["exam_items"]
        missing_items = req.required_exam_items - h["exam_items"]
        if req.required_exam_items:
            coverage_ratio = len(matched_items) / len(req.required_exam_items)
        else:
            coverage_ratio = 1.0
        exam_score = WEIGHT_EXAM_COVERAGE * coverage_ratio
        breakdown["검사항목 커버리지"] = round(exam_score, 1)

        # 3) 장비 풍부도 (필수 장비 외 추가 보유)
        # 장비 종류가 CT/MRI/PET-CT 3가지뿐이므로, 선택하지 않은 나머지 장비를
        # 얼마나 보유하는지로 계산 (최대 2개 추가 보유 시 만점)
        extra_equipment = h["equipment_set"] - req.required_equipment
        equipment_richness_ratio = min(len(extra_equipment) / 2, 1.0)
        equipment_score = WEIGHT_EQUIPMENT_RICHNESS * equipment_richness_ratio
        breakdown["보유 장비 다양성"] = round(equipment_score, 1)

        # 4) 인증/신뢰도
        cert_count = len(h["certifications"])
        cert_score = WEIGHT_CERTIFICATION * min(cert_count / 2, 1.0)  # 인증 2개 이상이면 만점
        breakdown["인증/신뢰도"] = round(cert_score, 1)

        # 5) 가격 경쟁력
        price_score = price_scores.get(h["id"], WEIGHT_PRICE_COMPETITIVENESS * 0.5)
        breakdown["가격 경쟁력"] = round(price_score, 1)

        total = sum(breakdown.values())

        detail = h["checkup_detail"].get(req.checkup_type)
        price_range = (detail["min_price"], detail["max_price"]) if detail else None

        results.append(
            HospitalScore(
                hospital=h,
                total_score=round(total, 1),
                breakdown=breakdown,
                matched_exam_items=matched_items,
                missing_exam_items=missing_items,
                extra_equipment=extra_equipment,
                price_range=price_range,
            )
        )

    results.sort(key=lambda r: r.total_score, reverse=True)
    return results[:top_n]
