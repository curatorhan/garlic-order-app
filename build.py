# -*- coding: utf-8 -*-
"""산출물 생성: 통합시트 · 패킹리스트 · 채널별 발송처리"""
import io
import pandas as pd
from openpyxl import Workbook
from datetime import datetime
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
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

def _left_rows(conf):
    """좌측: 업소용(개수) → 깐마늘(kg 합산) → 다진마늘(kg 합산)"""
    rows = []
    # 벌크(10kg)만 별도 줄. 5kg은 1kg 5개이므로 아래 kg 합산에 포함된다.
    bulk = conf[conf['_업소용'] & (conf['_중량'] == 10)]
    if len(bulk):
        g = (bulk.groupby('_표기').agg(수량=('_수량', 'sum'))
               .reset_index().sort_values('_표기'))
        for _, r in g.iterrows():
            rows.append(('* 업 소 용 * ' + r['_표기'], int(r['수량']), True))
        rows.append((None, None, False))

    rest = conf[~(conf['_업소용'] & (conf['_중량'] == 10))]
    for pre in ['대서 ', '토종 ']:
        kkan = rest[rest['_sku'].str.startswith(pre) & ~rest['_sku'].str.contains('다진')]
        if len(kkan):
            g = kkan.groupby('_sku')['_kg'].sum().reset_index()
            g['_o'] = g['_sku'].map(lambda s: ('꼭지제거' in s, s))
            for _, r in g.sort_values('_o').iterrows():
                rows.append((r['_sku'], int(r['_kg']), False))
            rows.append((None, None, False))
    for pre in ['대서 다진마늘', '토종 다진마늘']:
        dj = rest[rest['_sku'].str.startswith(pre)]
        if len(dj):
            g = dj.groupby('_sku')['_kg'].sum().reset_index()
            for _, r in g.sort_values('_sku').iterrows():
                nm = r['_sku'].replace('다진마늘 ', '') + ' 다진마늘'
                rows.append((nm, int(r['_kg']), False))
            rows.append((None, None, False))
    while rows and rows[-1][0] is None:
        rows.pop()
    return rows


def _right_rows(conf):
    """우측: 통마늘(개수) → 마늘쫑(중량별 건수·kg)"""
    rows = []
    tong = conf[conf['_sku'].str.startswith('통마늘')]
    if len(tong):
        g = tong.groupby('_sku').agg(수량=('_수량', 'sum')).reset_index()
        order = {'통마늘 특대': 0, '통마늘 대': 1, '통마늘 중': 2, '통마늘 소': 3}
        for _, r in g.sort_values('_sku', key=lambda s: s.map(order)).iterrows():
            rows.append((r['_sku'], int(r['수량']), None))
        rows.append((None, None, None))

    jjong = conf[conf['_sku'] == '마늘쫑']
    if len(jjong):
        g = (jjong.groupby('_중량').agg(건수=('_수량', 'sum'), kg=('_kg', 'sum'))
               .reset_index().sort_values('_중량'))
        for _, r in g.iterrows():
            rows.append((f"마늘쫑 {int(r['_중량'])}kg", int(r['건수']), int(r['kg'])))
    while rows and rows[-1][0] is None:
        rows.pop()
    return rows


def packing_list(conf, title_date=None):
    """인쇄용 패킹리스트 (좌우 2단). 예측·보정 칸은 손으로 적도록 비워둔다."""
    L = _left_rows(conf)
    R = _right_rows(conf)

    wb = Workbook(); ws = wb.active; ws.title = '패킹리스트'
    thin = Side(style='thin', color='000000')
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    GREY = PatternFill('solid', fgColor='D9D9D9')
    BIZ = PatternFill('solid', fgColor='F4B183')
    F = lambda sz=11, b=True: Font(name='Arial', bold=b, size=sz)
    CEN = Alignment(horizontal='center', vertical='center')
    LEF = Alignment(horizontal='left', vertical='center')
    RIG = Alignment(horizontal='right', vertical='center')

    day = title_date or datetime.now().strftime('%-m월 %-d일')
    n = conf['_묶음'].nunique()
    ws.merge_cells('A1:H1')
    t = ws.cell(1, 1, f'{day} ( {n}건 )')
    t.font = F(16); t.alignment = CEN
    for c in range(1, 9):
        ws.cell(1, c).border = box
    ws.row_dimensions[1].height = 34

    heads = ['상품명', '예측', '보정', '수량', '상품명', '예측', '보정', '수량']
    for c, h in enumerate(heads, 1):
        x = ws.cell(2, c, h); x.font = F(11); x.fill = GREY
        x.border = box; x.alignment = CEN
    ws.row_dimensions[2].height = 24

    total = max(len(L), len(R)) + 2
    for i in range(total):
        r = 3 + i
        ws.row_dimensions[r].height = 26
        if i < len(L):
            nm, qty, is_biz = L[i]
            if nm:
                ws.cell(r, 1, nm).alignment = LEF
                ws.cell(r, 4, qty).alignment = RIG
                if is_biz:
                    for c in range(1, 5):
                        ws.cell(r, c).fill = BIZ
        if i < len(R):
            nm, a, b = R[i]
            if nm:
                ws.cell(r, 5, nm).alignment = LEF
                ws.cell(r, 8, b if b is not None else a).alignment = RIG
        for c in range(1, 9):
            cell = ws.cell(r, c)
            cell.font = F(12); cell.border = box
            if cell.alignment.horizontal is None:
                cell.alignment = CEN

    r = 2 + total

    for col, w in zip('ABCDEFGH', [34, 8, 8, 9, 26, 8, 8, 9]):
        ws.column_dimensions[col].width = w
    ws.print_area = f'A1:H{r}'
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    pk = (conf.groupby('_표기').agg(수량=('_수량', 'sum'), 총kg=('_kg', 'sum'))
            .reset_index().rename(columns={'_표기': '품목'})
            .sort_values('총kg', ascending=False))
    buf = io.BytesIO(); wb.save(buf)
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
