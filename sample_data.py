# -*- coding: utf-8 -*-
"""
sample_data.py
--------------
데모/구조 검증용 샘플 병원 데이터. 전국 17개 시/도 중 대표 지역에
최소 1곳 이상의 병원을 배치해서, 어떤 지역을 선택해도 구조가 동작하는지
확인할 수 있도록 했습니다. (병원이 없는 세부 시/군/구를 선택하면 "결과 없음"이
뜨는 것이 정상이며, 실제 서비스 단계에서 데이터가 채워지면 자동으로 해결됩니다)

실서비스 전환 시:
1) 국민건강보험공단 공공데이터포털의 "건강검진기관 지정 현황" API로
   hospitals 테이블의 name/region/address/phone/checkup_types 기본값을 채우고
2) hospital_equipment, exam_item 커버리지는 병원 홈페이지/제휴 조사를 통해
   실측 데이터로 교체하는 것을 권장합니다.
"""

import random
from database import get_connection, init_schema, load_exam_item_master, EXAM_ITEM_MASTER

random.seed(42)

SAMPLE_HOSPITALS = [
    # (name, si, gu, address, phone, established_year, certifications)
    ("서울메디컬 종합검진센터", "서울", "강남구", "서울 강남구 테헤란로 123", "02-1234-5678", 2005,
     "국가건강검진기관,JCI인증"),
    ("강남프리미엄헬스케어", "서울", "강남구", "서울 강남구 논현로 45", "02-2345-6789", 2015,
     "국가건강검진기관"),
    ("송파하나검진의원", "서울", "송파구", "서울 송파구 올림픽로 88", "02-3456-7890", 2010,
     "국가건강검진기관"),
    ("종로중앙병원 건강증진센터", "서울", "종로구", "서울 종로구 종로 12", "02-4567-8901", 1998,
     "국가건강검진기관,우수기관인증"),
    ("성남종합메디컬센터", "경기", "성남시 분당구", "경기 성남시 분당구 판교로 200", "031-123-4567", 2012,
     "국가건강검진기관"),
    ("수원가족건강검진센터", "경기", "수원시 영통구", "경기 수원시 영통구 광교로 55", "031-234-5678", 2008,
     "국가건강검진기관"),
    ("대구수성프리미엄검진센터", "대구", "수성구", "대구 수성구 동대구로 77", "053-123-4567", 2011,
     "국가건강검진기관,JCI인증"),
    ("대구중앙메디컬 건강검진원", "대구", "중구", "대구 중구 중앙대로 30", "053-234-5678", 2001,
     "국가건강검진기관"),
    ("대구달서한마음검진센터", "대구", "달서구", "대구 달서구 성서로 15", "053-345-6789", 2016,
     "국가건강검진기관"),
    ("부산해운대종합검진병원", "부산", "해운대구", "부산 해운대구 센텀로 90", "051-123-4567", 2009,
     "국가건강검진기관,우수기관인증"),
    ("부산서면메디컬검진센터", "부산", "부산진구", "부산 부산진구 중앙대로 200", "051-234-5678", 2013,
     "국가건강검진기관"),
    ("인천송도글로벌검진센터", "인천", "연수구", "인천 연수구 송도국제대로 100", "032-123-4567", 2018,
     "국가건강검진기관,JCI인증"),
    ("광주하나로건강검진센터", "광주", "서구", "광주 서구 상무대로 60", "062-123-4567", 2007,
     "국가건강검진기관"),
    ("대전메디컬케어 검진센터", "대전", "서구", "대전 서구 둔산로 33", "042-123-4567", 2014,
     "국가건강검진기관"),
    ("서울강북프리미엄검진의원", "서울", "노원구", "서울 노원구 노해로 70", "02-5678-9012", 2019,
     "국가건강검진기관"),
    # --- 아래부터 지역 커버리지 확대를 위해 추가된 병원들 ---
    ("울산중앙건강검진센터", "울산", "중구", "울산 중구 성남로 20", "052-123-4567", 2010,
     "국가건강검진기관"),
    ("세종시티건강검진센터", "세종", "세종시", "세종특별자치시 한누리대로 300", "044-123-4567", 2020,
     "국가건강검진기관"),
    ("춘천한마음검진센터", "강원", "춘천시", "강원 춘천시 중앙로 50", "033-123-4567", 2012,
     "국가건강검진기관"),
    ("청주하나로검진센터", "충북", "청주시 흥덕구", "충북 청주시 흥덕구 오송로 40", "043-123-4567", 2011,
     "국가건강검진기관"),
    ("천안메디컬검진센터", "충남", "천안시 서북구", "충남 천안시 서북구 봉정로 25", "041-123-4567", 2013,
     "국가건강검진기관"),
    ("전주건강검진의원", "전북", "전주시 덕진구", "전북 전주시 덕진구 백제대로 400", "063-123-4567", 2009,
     "국가건강검진기관"),
    ("순천종합검진센터", "전남", "순천시", "전남 순천시 중앙로 88", "061-123-4567", 2015,
     "국가건강검진기관"),
    ("포항프리미엄검진센터", "경북", "포항시 남구", "경북 포항시 남구 대잠로 15", "054-123-4567", 2014,
     "국가건강검진기관,JCI인증"),
    ("창원중앙검진센터", "경남", "창원시 성산구", "경남 창원시 성산구 창이대로 60", "055-123-4567", 2010,
     "국가건강검진기관"),
    ("제주힐링건강검진센터", "제주", "제주시", "제주 제주시 노형로 12", "064-123-4567", 2017,
     "국가건강검진기관,우수기관인증"),
]

# 병원별 등급(tier) - 값이 높을수록 고가장비 보유 확률/항목 커버리지/가격이 높아짐
TIER_BY_INDEX = [
    3, 2, 1, 2, 2, 1, 3, 1, 1, 3, 2, 3, 1, 2, 2,  # 기존 15곳
    2, 1, 1, 2, 2, 1, 2, 3, 2, 3,                  # 추가된 10곳
]

# 요청사항 반영: 필수 장비는 CT / MRI / PET-CT 세 가지로 단순화
EQUIPMENT_BY_TIER = {
    1: ["CT"],
    2: ["CT", "MRI"],
    3: ["CT", "MRI", "PET-CT"],
}

# 요청사항 반영: 검진 유형은 종합검진 / 일반검진 두 가지로 단순화
CHECKUP_TYPES_BY_TIER = {
    1: [("일반검진", 0, 150000, 1.5), ("종합검진", 200000, 400000, 2.0)],
    2: [("일반검진", 0, 150000, 1.5), ("종합검진", 400000, 900000, 3.0)],
    3: [("일반검진", 0, 150000, 1.5), ("종합검진", 800000, 2000000, 4.5)],
}

# 카테고리별 항목 커버리지 비율 (tier가 높을수록 더 많은 항목 커버)
COVERAGE_RATIO_BY_TIER = {1: 0.5, 2: 0.75, 3: 1.0}

# 첨단영상 항목 중 실제로 해당 장비가 있어야만 제공 가능한 항목 연동
# (CT/MRI/PET-CT 세 장비 기준으로만 연동, 나머지 항목은 장비 제약 없이 커버리지 비율로 배정)
EQUIPMENT_LINKED_ITEMS = {
    "뇌 MRI/MRA": "MRI",
    "전신 PET-CT": "PET-CT",
    "관상동맥CT": "CT",
    "저선량 흉부CT(폐암검진)": "CT",
}


def populate_sample_data():
    conn = get_connection()
    init_schema(conn)
    load_exam_item_master(conn)

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM hospitals")
    if cur.fetchone()[0] > 0:
        conn.close()
        return  # 이미 데이터가 있으면 중복 삽입 방지

    all_items = cur.execute("SELECT id, item_name FROM exam_item_master").fetchall()
    item_id_by_name = {row["item_name"]: row["id"] for row in all_items}
    all_item_names = [name for _, name in EXAM_ITEM_MASTER]

    for idx, (name, si, gu, addr, phone, est_year, certs) in enumerate(SAMPLE_HOSPITALS):
        tier = TIER_BY_INDEX[idx]

        cur.execute(
            """INSERT INTO hospitals
               (name, region_si, region_gu, address, phone, homepage, established_year,
                certifications, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, si, gu, addr, phone,
                f"https://www.example-hospital-{idx+1}.co.kr",
                est_year, certs,
                f"{name}는 {si} {gu} 지역의 건강검진 전문 의료기관입니다.",
            ),
        )
        hospital_id = cur.lastrowid

        # 장비 등록
        equip_list = EQUIPMENT_BY_TIER[tier].copy()
        if tier < 3 and random.random() < 0.2:
            if "MRI" not in equip_list:
                equip_list.append("MRI")
        for eq in equip_list:
            spec = {
                "CT": random.choice(["64채널 CT", "128채널 CT", "256채널 CT"]),
                "MRI": random.choice(["1.5T MRI", "3.0T MRI"]),
                "PET-CT": "PET-CT (전신 촬영용)",
            }.get(eq, None)
            install_year = random.randint(max(est_year, 2010), 2025)
            cur.execute(
                """INSERT INTO hospital_equipment (hospital_id, equipment_type, spec, install_year)
                   VALUES (?, ?, ?, ?)""",
                (hospital_id, eq, spec, install_year),
            )

        # 검진유형/가격 등록
        for type_name, min_p, max_p, dur in CHECKUP_TYPES_BY_TIER[tier]:
            jitter = random.uniform(0.9, 1.1)
            cur.execute(
                """INSERT INTO checkup_types
                   (hospital_id, type_name, min_price, max_price, avg_duration_hours)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    hospital_id, type_name,
                    int(min_p * jitter) if min_p else 0,
                    int(max_p * jitter),
                    dur,
                ),
            )

        # 검사항목 커버리지 등록
        ratio = COVERAGE_RATIO_BY_TIER[tier]
        n_items = int(len(all_item_names) * ratio)
        chosen_items = set(random.sample(all_item_names, n_items))

        for item_name, required_eq in EQUIPMENT_LINKED_ITEMS.items():
            if required_eq not in equip_list and item_name in chosen_items:
                chosen_items.discard(item_name)

        for item_name in chosen_items:
            cur.execute(
                "INSERT INTO hospital_exam_items (hospital_id, item_id) VALUES (?, ?)",
                (hospital_id, item_id_by_name[item_name]),
            )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    populate_sample_data()
    print("샘플 데이터 삽입 완료")
