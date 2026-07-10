# -*- coding: utf-8 -*-
"""
database.py
-----------
건강검진 병원 추천 시스템의 DB 스키마 정의 및 초기화 모듈.

설계 원칙
- 지금은 SQLite(파일 기반)로 시작하지만, 스키마는 추후 Supabase(PostgreSQL) 이전을
  염두에 두고 설계했습니다. (테이블명/컬럼명을 그대로 옮겨도 동작하도록 표준 SQL만 사용)
- 실제 서비스 단계에서는 hospitals 테이블에 국민건강보험공단 공공데이터(건강검진기관
  지정 현황)를 매핑하고, hospital_equipment / checkup_types / hospital_exam_items는
  컨설턴트가 직접 조사하거나 병원 제휴를 통해 채워 넣는 구조를 권장합니다.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "health_checkup.db"

# ---------------------------------------------------------------------------
# 표준 마스터 데이터 (전국 공통으로 고정되는 값들)
# ---------------------------------------------------------------------------

EQUIPMENT_TYPES = [
    "CT",
    "MRI",
    "PET-CT",
]

# 일반 환자 기준으로 이해하기 쉬운 두 가지 큰 틀만 제공.
# (암검진/여성검진/남성검진 등 세부 분류는 상담 단계에서 안내하는 것으로 단순화)
CHECKUP_TYPE_NAMES = [
    "종합검진",
    "일반검진",
]

# 검사항목 마스터: (카테고리, 항목명)
# 환자가 이해하기 쉬운 카테고리만 남김 (기본계측/안과이비인후과는 환자 체감도가
# 낮고 대부분 검진에 기본 포함되는 항목이라 체크리스트에서 제외)
EXAM_ITEM_MASTER = [
    # 혈액검사
    ("혈액검사", "일반혈액검사(CBC)"),
    ("혈액검사", "간기능검사"),
    ("혈액검사", "신장기능검사"),
    ("혈액검사", "지질검사(콜레스테롤)"),
    ("혈액검사", "공복혈당/당화혈색소"),
    ("혈액검사", "갑상선기능검사"),
    ("혈액검사", "종양표지자검사"),
    ("혈액검사", "B형/C형간염검사"),
    # 영상검사 (골밀도검사 포함)
    ("영상검사", "흉부X-ray"),
    ("영상검사", "복부초음파"),
    ("영상검사", "갑상선초음파"),
    ("영상검사", "유방촬영술"),
    ("영상검사", "경동맥초음파"),
    ("영상검사", "심장초음파"),
    ("영상검사", "골밀도검사(DEXA)"),
    # 내시경
    ("내시경", "위내시경"),
    ("내시경", "대장내시경"),
    ("내시경", "수면내시경(위/대장)"),
    # 첨단영상(고가장비)
    ("첨단영상", "뇌 MRI/MRA"),
    ("첨단영상", "전신 PET-CT"),
    ("첨단영상", "관상동맥CT"),
    ("첨단영상", "저선량 흉부CT(폐암검진)"),
]


def get_connection():
    """SQLite 커넥션 반환 (foreign key 제약 활성화)"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection):
    """테이블이 없으면 생성"""
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS hospitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            region_si TEXT NOT NULL,        -- 시/도 (예: 서울, 대구, 경기)
            region_gu TEXT NOT NULL,        -- 구/군 (예: 강남구, 수성구)
            address TEXT,
            phone TEXT,
            homepage TEXT,
            established_year INTEGER,
            certifications TEXT,            -- 콤마구분: "국가건강검진기관,JCI인증"
            description TEXT
        );

        CREATE TABLE IF NOT EXISTS hospital_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_id INTEGER NOT NULL REFERENCES hospitals(id) ON DELETE CASCADE,
            equipment_type TEXT NOT NULL,
            spec TEXT,                      -- 예: "128채널 CT", "3.0T MRI"
            install_year INTEGER
        );

        CREATE TABLE IF NOT EXISTS checkup_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_id INTEGER NOT NULL REFERENCES hospitals(id) ON DELETE CASCADE,
            type_name TEXT NOT NULL,
            min_price INTEGER,
            max_price INTEGER,
            avg_duration_hours REAL
        );

        CREATE TABLE IF NOT EXISTS exam_item_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            item_name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS hospital_exam_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hospital_id INTEGER NOT NULL REFERENCES hospitals(id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES exam_item_master(id) ON DELETE CASCADE,
            UNIQUE(hospital_id, item_id)
        );

        CREATE INDEX IF NOT EXISTS idx_hospital_region ON hospitals(region_si, region_gu);
        CREATE INDEX IF NOT EXISTS idx_equipment_hospital ON hospital_equipment(hospital_id);
        CREATE INDEX IF NOT EXISTS idx_checkup_hospital ON checkup_types(hospital_id);
        CREATE INDEX IF NOT EXISTS idx_examitem_hospital ON hospital_exam_items(hospital_id);
        """
    )
    conn.commit()


def load_exam_item_master(conn: sqlite3.Connection):
    """exam_item_master 마스터 데이터 삽입 (없을 때만)"""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM exam_item_master")
    if cur.fetchone()[0] > 0:
        return
    cur.executemany(
        "INSERT INTO exam_item_master (category, item_name) VALUES (?, ?)",
        EXAM_ITEM_MASTER,
    )
    conn.commit()


def get_full_hospital_data(conn: sqlite3.Connection):
    """
    각 병원의 모든 정보를 하나의 dict로 묶어서 리스트로 반환.
    scoring_engine에서 바로 사용할 수 있는 형태.
    """
    cur = conn.cursor()
    hospitals = cur.execute("SELECT * FROM hospitals").fetchall()

    result = []
    for h in hospitals:
        hid = h["id"]

        equipment_rows = cur.execute(
            "SELECT equipment_type, spec, install_year FROM hospital_equipment WHERE hospital_id=?",
            (hid,),
        ).fetchall()
        equipment_set = {row["equipment_type"] for row in equipment_rows}
        equipment_detail = {
            row["equipment_type"]: {"spec": row["spec"], "install_year": row["install_year"]}
            for row in equipment_rows
        }

        checkup_rows = cur.execute(
            "SELECT type_name, min_price, max_price, avg_duration_hours FROM checkup_types WHERE hospital_id=?",
            (hid,),
        ).fetchall()
        checkup_types = {row["type_name"] for row in checkup_rows}
        checkup_detail = {
            row["type_name"]: {
                "min_price": row["min_price"],
                "max_price": row["max_price"],
                "avg_duration_hours": row["avg_duration_hours"],
            }
            for row in checkup_rows
        }

        item_rows = cur.execute(
            """
            SELECT eim.item_name, eim.category
            FROM hospital_exam_items hei
            JOIN exam_item_master eim ON hei.item_id = eim.id
            WHERE hei.hospital_id=?
            """,
            (hid,),
        ).fetchall()
        exam_items = {row["item_name"] for row in item_rows}

        result.append(
            {
                "id": hid,
                "name": h["name"],
                "region_si": h["region_si"],
                "region_gu": h["region_gu"],
                "address": h["address"],
                "phone": h["phone"],
                "homepage": h["homepage"],
                "established_year": h["established_year"],
                "certifications": [c.strip() for c in (h["certifications"] or "").split(",") if c.strip()],
                "description": h["description"],
                "equipment_set": equipment_set,
                "equipment_detail": equipment_detail,
                "checkup_types": checkup_types,
                "checkup_detail": checkup_detail,
                "exam_items": exam_items,
            }
        )
    return result


def get_region_list(conn: sqlite3.Connection):
    """DB에 존재하는 시/도 -> 구/군 목록 매핑 반환"""
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT DISTINCT region_si, region_gu FROM hospitals ORDER BY region_si, region_gu"
    ).fetchall()
    mapping = {}
    for row in rows:
        mapping.setdefault(row["region_si"], []).append(row["region_gu"])
    return mapping
