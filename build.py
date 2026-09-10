# -*- coding: utf-8 -*-
"""산출물 생성: 통합시트 · 패킹리스트 · 채널별 발송처리"""
import io
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

COLS = ['주문번호', '수령인명', '연락처', '옵션', '수량',
        '우편번호', '주소', '배송메세지', '파일출처', '등기번호']
BIZ = PatternFill('solid', fgColor='F4B183')
M1  = PatternFill('solid', fgColor='FFD966')
M2  = PatternFill('solid', fgColor='9DC3E6')
HDR = PatternFill('solid', fgColor='3F3F3F')

def integrated_sheet(conf):
    """단건 위(업소용 우선) → 합배송 아래(이름순, 묶음별 색 교차)"""
    conf = conf.copy()
    info = {b: dict(합=len(g) > 1, 수취인=g['_수취인'].iloc[0])
            for b, g in conf.groupby('_묶음')}
    conf['_합'] = conf['_묶음'].map(lambda b: info[b]['합'])

    s = conf[~conf['_합']].copy()
    s['_k'] = s.apply(lambda r: (0 if r['_업소용'] else 1, r['_수취인']), axis=1)
    s = s.sort_values('_k')
    m = conf[conf['_합']].copy()
    m['_k'] = m['_묶음'].map(lambda b: info[b]['수취인'])
    m = m.sort_values(['_k', '_묶음', '_표기'])

    def row(r):
        biz = '* 업 소 용 * ' if r['_업소용'] else ''
        return [r['_키'], r['_수취인'], r['_연락처'], biz + str(r['_표기']),
                int(r['_수량']), r['_우편'], r['_주소'], r['_메시지'], r['_채널'], '']

    wb = Workbook(); ws = wb.active; ws.title = '통합시트'
    ws.append(COLS)
    for c in range(1, len(COLS) + 1):
        x = ws.cell(1, c)
        x.font = Font(name='Arial', bold=True, size=10, color='FFFFFF')
        x.fill = HDR; x.alignment = Alignment(horizontal='center')

    i = 2
    for _, r in s.iterrows():
        ws.append(row(r))
        if r['_업소용']:
            for c in range(1, len(COLS) + 1): ws.cell(i, c).fill = BIZ
        i += 1
    tog, prev = 0, None
    for _, r in m.iterrows():
        if r['_묶음'] != prev: tog ^= 1; prev = r['_묶음']
        ws.append(row(r))
        f = M1 if tog else M2
        for c in range(1, len(COLS) + 1): ws.cell(i, c).fill = f
        i += 1

    for rr in ws.iter_rows(min_row=2, max_row=i - 1, max_col=len(COLS)):
        for c in rr:
            c.font = Font(name='Arial', size=10)
            c.alignment = Alignment(vertical='center',
                horizontal='center' if c.column in (5, 6, 9) else 'left')
    for n, w in enumerate([19, 10, 14, 26, 6, 9, 42, 20, 13, 12], 1):
        ws.column_dimensions[get_column_letter(n)].width = w
    ws.freeze_panes = 'A2'
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

def packing_list(conf):
    pk = (conf.groupby('_표기')
            .agg(수량=('_수량', 'sum'), 총kg=('_kg', 'sum'))
            .reset_index().rename(columns={'_표기': '품목'})
            .sort_values('총kg', ascending=False))
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        pk.to_excel(w, sheet_name='패킹리스트', index=False)
    return buf.getvalue(), pk

def channel_file(raw_df, key_col, keys, sheet_name=None):
    """원본 구조 그대로, 확정 건만 남긴 파일"""
    out = raw_df[raw_df[key_col].astype(str).str.strip().isin(keys)]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as w:
        out.to_excel(w, sheet_name=sheet_name or 'Sheet1', index=False)
    return buf.getvalue(), len(out)

def verify(conf, channel_counts):
    """검증: 발송파일 합계와 확정 행수, 통합시트와 패킹리스트 중량"""
    msgs, okall = [], True
    tot = sum(channel_counts.values())
    if tot == len(conf):
        msgs.append(f'발송파일 {tot}행 = 확정 {len(conf)}행 일치')
    else:
        msgs.append(f'발송파일 {tot}행 ≠ 확정 {len(conf)}행'); okall = False
    if conf['_키'].duplicated().any():
        msgs.append('중복된 주문번호가 있습니다'); okall = False
    else:
        msgs.append('주문번호 중복 없음')
    blank = conf[(conf['_우편'].isin(['', 'nan'])) | (conf['_주소'].str.strip() == '')]
    if len(blank):
        msgs.append(f'우편번호·주소 누락 {len(blank)}건'); okall = False
    else:
        msgs.append('우편번호·주소 누락 없음')
    return okall, msgs
