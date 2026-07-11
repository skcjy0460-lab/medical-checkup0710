# -*- coding: utf-8 -*-
"""
excel_to_db.py
--------------
'병원데이터_템플릿.xlsx' (또는 동일한 시트 구조를 가진 엑셀 파일)를 읽어서
health_checkup.db (SQLite)에 적재하는 변환 스크립트.

엑셀은 어디까지나 "입력/관리용" 포맷이고, 실제 앱은 항상 DB만 조회합니다.
이 스크립트를 실행할 때마다 기존 DB 데이터를 지우고 엑셀 내용으로 새로 채웁니다
(엑셀이 최신 원본이라는 원칙 - Single Source of Truth).

실행:
    python excel_to_db.py [엑셀파일경로]
    (경로 생략 시 기본값: 병원데이터_템플릿.xlsx)

검증 규칙:
    - 병원ID가 비어있는 행은 예시/빈 행으로 간주하고 건너뜁니다.
    - 드롭다운 값(시도/장비종류/검진유형/검사항목명)이 마스터 목록에 없으면
      해당 행을 건너뛰고 경고를 출력합니다. (오타 방지)
    - 2~4번 시트에서 참조하는 병원ID가 1번 시트(병원마스터)에 없으면 건너뜁니다.
"""

import sys
import pandas as pd

from database import (
    get_connection,
    init_schema,
    load_exam_item_master,
    EQUIPMENT_TYPES,
    CHECKUP_TYPE_NAMES,
)
from korea_regions import SIDO_LIST

DEFAULT_PATH = "병원데이터_템플릿.xlsx"


def _clean_int(value, default=None):
    try:
        if pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_str(value, default=""):
    if pd.isna(value):
        return default
    return str(value).strip()


def load_excel_to_db(path: str = DEFAULT_PATH, replace_existing: bool = True):
    warnings = []

    hosp_df = pd.read_excel(path, sheet_name="1_병원마스터")
    equip_df = pd.read_excel(path, sheet_name="2_보유장비")
    checkup_df = pd.read_excel(path, sheet_name="3_검진유형가격")
    item_df = pd.read_excel(path, sheet_name="4_검사항목")

    conn = get_connection()
    init_schema(conn)
    load_exam_item_master(conn)
    cur = conn.cursor()

    if replace_existing:
        cur.execute("DELETE FROM hospital_exam_items")
        cur.execute("DELETE FROM checkup_types")
        cur.execute("DELETE FROM hospital_equipment")
        cur.execute("DELETE FROM hospitals")
        conn.commit()

    item_id_by_name = {
        row["item_name"]: row["id"]
        for row in cur.execute("SELECT id, item_name FROM exam_item_master").fetchall()
    }

    # ------------------------------------------------------------------
    # 1. 병원마스터
    # ------------------------------------------------------------------
    excel_id_to_db_id = {}
    hospital_count = 0
    for _, row in hosp_df.iterrows():
        excel_id = _clean_int(row.get("병원ID"))
        if excel_id is None:
            continue  # 빈 행/예시 안내행 스킵

        name = _clean_str(row.get("병원명"))
        si = _clean_str(row.get("시도"))
        gu = _clean_str(row.get("시군구"))

        if not name:
            warnings.append(f"[병원마스터] 병원ID {excel_id}: 병원명이 비어있어 건너뜁니다.")
            continue
        if si not in SIDO_LIST:
            warnings.append(
                f"[병원마스터] 병원ID {excel_id} '{name}': 시도 값 '{si}'가 유효하지 않아 건너뜁니다. "
                f"(허용값: {', '.join(SIDO_LIST)})"
            )
            continue
        if excel_id in excel_id_to_db_id:
            warnings.append(f"[병원마스터] 병원ID {excel_id}가 중복되어 이후 항목은 무시합니다.")
            continue

        cur.execute(
            """INSERT INTO hospitals
               (name, region_si, region_gu, address, phone, homepage, established_year,
                certifications, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name, si, gu,
                _clean_str(row.get("주소")),
                _clean_str(row.get("전화번호")),
                _clean_str(row.get("홈페이지")),
                _clean_int(row.get("설립연도")),
                _clean_str(row.get("인증(콤마구분)")),
                _clean_str(row.get("소개")),
            ),
        )
        excel_id_to_db_id[excel_id] = cur.lastrowid
        hospital_count += 1

    conn.commit()

    # ------------------------------------------------------------------
    # 2. 보유장비
    # ------------------------------------------------------------------
    equipment_count = 0
    for _, row in equip_df.iterrows():
        excel_id = _clean_int(row.get("병원ID"))
        equipment_type = _clean_str(row.get("장비종류"))
        if excel_id is None or not equipment_type:
            continue
        if excel_id not in excel_id_to_db_id:
            warnings.append(f"[보유장비] 병원ID {excel_id}: 병원마스터에 존재하지 않아 건너뜁니다.")
            continue
        if equipment_type not in EQUIPMENT_TYPES:
            warnings.append(
                f"[보유장비] 병원ID {excel_id}: 장비종류 '{equipment_type}'가 유효하지 않아 건너뜁니다. "
                f"(허용값: {', '.join(EQUIPMENT_TYPES)})"
            )
            continue

        cur.execute(
            """INSERT INTO hospital_equipment (hospital_id, equipment_type, spec, install_year)
               VALUES (?, ?, ?, ?)""",
            (
                excel_id_to_db_id[excel_id], equipment_type,
                _clean_str(row.get("스펙(선택)"), default=None) or None,
                _clean_int(row.get("도입연도(선택)")),
            ),
        )
        equipment_count += 1

    conn.commit()

    # ------------------------------------------------------------------
    # 3. 검진유형가격
    # ------------------------------------------------------------------
    checkup_count = 0
    for _, row in checkup_df.iterrows():
        excel_id = _clean_int(row.get("병원ID"))
        type_name = _clean_str(row.get("검진유형"))
        if excel_id is None or not type_name:
            continue
        if excel_id not in excel_id_to_db_id:
            warnings.append(f"[검진유형가격] 병원ID {excel_id}: 병원마스터에 존재하지 않아 건너뜁니다.")
            continue
        if type_name not in CHECKUP_TYPE_NAMES:
            warnings.append(
                f"[검진유형가격] 병원ID {excel_id}: 검진유형 '{type_name}'가 유효하지 않아 건너뜁니다. "
                f"(허용값: {', '.join(CHECKUP_TYPE_NAMES)})"
            )
            continue

        min_price = _clean_int(row.get("최소가격(원)"), default=0)
        max_price = _clean_int(row.get("최대가격(원)"), default=0)
        if max_price < min_price:
            warnings.append(
                f"[검진유형가격] 병원ID {excel_id} '{type_name}': 최대가격이 최소가격보다 "
                f"작아 건너뜁니다. (최소 {min_price}, 최대 {max_price})"
            )
            continue

        try:
            duration = float(row.get("평균소요시간(시간)"))
        except (TypeError, ValueError):
            duration = None

        cur.execute(
            """INSERT INTO checkup_types
               (hospital_id, type_name, min_price, max_price, avg_duration_hours)
               VALUES (?, ?, ?, ?, ?)""",
            (excel_id_to_db_id[excel_id], type_name, min_price, max_price, duration),
        )
        checkup_count += 1

    conn.commit()

    # ------------------------------------------------------------------
    # 4. 검사항목
    # ------------------------------------------------------------------
    item_link_count = 0
    for _, row in item_df.iterrows():
        excel_id = _clean_int(row.get("병원ID"))
        item_name = _clean_str(row.get("검사항목명"))
        if excel_id is None or not item_name:
            continue
        if excel_id not in excel_id_to_db_id:
            warnings.append(f"[검사항목] 병원ID {excel_id}: 병원마스터에 존재하지 않아 건너뜁니다.")
            continue
        if item_name not in item_id_by_name:
            warnings.append(
                f"[검사항목] 병원ID {excel_id}: 검사항목명 '{item_name}'이 마스터 목록에 없어 건너뜁니다."
            )
            continue

        cur.execute(
            """INSERT OR IGNORE INTO hospital_exam_items (hospital_id, item_id)
               VALUES (?, ?)""",
            (excel_id_to_db_id[excel_id], item_id_by_name[item_name]),
        )
        item_link_count += 1

    conn.commit()
    conn.close()

    # ------------------------------------------------------------------
    # 결과 리포트
    # ------------------------------------------------------------------
    print(f"✅ 병원 {hospital_count}곳 / 장비 {equipment_count}건 / "
          f"검진유형·가격 {checkup_count}건 / 검사항목 매핑 {item_link_count}건 적재 완료")

    if warnings:
        print(f"\n⚠️  경고 {len(warnings)}건 (아래 항목은 건너뛰었습니다):")
        for w in warnings:
            print("  -", w)
    else:
        print("경고 없음 - 모든 행이 정상적으로 처리되었습니다.")

    return {
        "hospital_count": hospital_count,
        "equipment_count": equipment_count,
        "checkup_count": checkup_count,
        "item_link_count": item_link_count,
        "warnings": warnings,
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    load_excel_to_db(path)
