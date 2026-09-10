# -*- coding: utf-8 -*-
"""설정: 구글 시트에서 채널 정의를 읽어온다"""
import pandas as pd

SHEET_URL = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vTuDYja9bY-L8x_"
             "KmFRAYYuzll0fb_cPHz8E79HxRzK4w5pGQ1F1mrQInfI5LMh3i--LCi9BrS6PvN_"
             "/pub?gid=0&single=true&output=csv")

# 재고 입력 그룹: (그룹명, 입력방식, [(표시라벨, 재고SKU), ...])
#   입력방식 'bag'   → 포대 + 잔여kg 두 칸
#   입력방식 'count' → 개수 한 칸 (1kg 단위)
STOCK_GROUPS = [
    ('대서 깐마늘', 'bag', [('대', '대서 대'), ('중', '대서 중'), ('소', '대서 소'),
                          ('대 꼭지제거', '대서 대 꼭지제거'), ('중 꼭지제거', '대서 중 꼭지제거')]),
    ('토종 깐마늘', 'bag', [('대', '토종 대'), ('중', '토종 중'), ('소', '토종 소'),
                          ('대 꼭지제거', '토종 대 꼭지제거'), ('중 꼭지제거', '토종 중 꼭지제거')]),
    ('다진마늘', 'bag', [('대서 통째로', '대서 다진마늘 통째로'),
                        ('대서 꼭지제거', '대서 다진마늘 꼭지제거'),
                        ('토종 통째로', '토종 다진마늘 통째로'),
                        ('토종 꼭지제거', '토종 다진마늘 꼭지제거')]),
    ('통마늘 · 마늘쫑', 'count', [('통마늘 특대', '통마늘 특대'), ('통마늘 대', '통마늘 대'),
                                ('통마늘 중', '통마늘 중'), ('통마늘 소', '통마늘 소'),
                                ('마늘쫑', '마늘쫑')]),
]
STOCK_SKUS = [sku for _, _, items in STOCK_GROUPS for _, sku in items]
KNOWN_SKUS = STOCK_SKUS
BAG_KG = 20

REQUIRED = ['채널', '사용', '헤더행', '판별컬럼', '고유키', '합배송키', '옵션',
            '수량', '수취인', '연락처', '우편번호', '주소', '주문일시',
            '옵션구분자', '배정순위']

def load_channels(url=SHEET_URL):
    """설정 시트를 읽어 사용중인 채널만 반환. 실패 시 예외를 올린다."""
    df = pd.read_csv(url, dtype=str).fillna('')
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"설정 시트에 필요한 컬럼이 없습니다: {', '.join(missing)}")
    df = df[df['사용'].str.upper() == 'Y'].copy()
    if df.empty:
        raise ValueError("사용 중인 채널이 없습니다. 설정 시트의 '사용' 칸을 확인하세요.")
    df['헤더행'] = pd.to_numeric(df['헤더행'], errors='coerce').fillna(1).astype(int)
    df['배정순위'] = pd.to_numeric(df['배정순위'], errors='coerce').fillna(99).astype(int)
    return df.to_dict('records')
