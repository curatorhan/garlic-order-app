# -*- coding: utf-8 -*-
import pandas as pd
import streamlit as st

from config import load_channels, STOCK_GROUPS, STOCK_SKUS, BAG_KG
from core import read_orders, check_unknown, allocate, top_priority
from build import integrated_sheet, packing_list, channel_file, verify

st.set_page_config(page_title='주문 처리', page_icon='🧄', layout='wide')

# 태블릿용 재고 전용 화면:  ...streamlit.app/?view=stock
VIEW = st.query_params.get('view', '')


def stock_inputs(prefix=''):
    """재고 입력 칸. 그룹별로 나눠서 그린다."""
    stock = {}
    cols = st.columns(len(STOCK_GROUPS))
    for gi, (gname, mode, items) in enumerate(STOCK_GROUPS):
        with cols[gi]:
            st.markdown(f'**{gname}**')
            st.caption('포대 · 잔여kg' if mode == 'bag' else '개수')
            for label, sku in items:
                if mode == 'bag':
                    c0, c1, c2 = st.columns([3, 2, 2])
                    c0.markdown(f"<div style='padding-top:8px;font-size:14px'>{label}</div>",
                                unsafe_allow_html=True)
                    b = c1.number_input('포대', 0, 999, 0, key=f'{prefix}b_{sku}',
                                        label_visibility='collapsed')
                    r = c2.number_input('kg', 0, BAG_KG - 1, 0, key=f'{prefix}r_{sku}',
                                        label_visibility='collapsed')
                    stock[sku] = b * BAG_KG + r
                else:
                    c0, c1 = st.columns([3, 2])
                    c0.markdown(f"<div style='padding-top:8px;font-size:14px'>{label}</div>",
                                unsafe_allow_html=True)
                    stock[sku] = c1.number_input('개수', 0, 9999, 0, key=f'{prefix}c_{sku}',
                                                 label_visibility='collapsed')
    return stock


# ============ 재고 전용 화면 (배송팀 태블릿) ============
if VIEW == 'stock':
    st.title('오늘의 재고')
    st.caption('포대 20kg 기준 · 없는 품목은 0으로 두세요')
    stock = stock_inputs('s_')
    st.metric('총 재고', f'{sum(stock.values()):,}kg')
    st.info('저장 기능은 다음 단계에서 붙습니다. 지금은 이 숫자를 CS에 알려주세요.')
    st.stop()


# ============ 메인 화면 ============
st.title('주문 처리')
try:
    CHANNELS = load_channels()
except Exception as e:
    st.error(f'설정 시트를 읽지 못했습니다. {e}')
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs(['일일 처리', '기록', '예측', '설정'])

# ---------------- 일일 처리 ----------------
with tab1:
    st.subheader('1. 재고 입력')
    st.caption('포대 20kg 기준 · 재고가 없는 품목은 0으로 두세요')
    stock = stock_inputs()
    st.metric('총 재고', f'{sum(stock.values()):,}kg')

    st.subheader('2. 주문 파일 업로드')
    files = st.file_uploader('여러 개를 한 번에 올리세요. 채널은 자동으로 판별합니다.',
                             type=['xlsx', 'xls'], accept_multiple_files=True)
    if not files:
        st.info('주문 파일을 올리면 결과가 나옵니다.')
        st.stop()

    frames, raws, errs = [], {}, []
    for f in files:
        d, ch, w = read_orders(f, CHANNELS)
        errs += w
        if d is None:
            errs.append(f'{f.name} · 읽지 못했습니다.')
            continue
        frames.append(d)
        f.seek(0)
        raws[ch['채널']] = (pd.read_excel(f, header=ch['헤더행'] - 1), ch)
        st.write(f"**{f.name}** → {ch['채널']} · {len(d)}행")
    for e in errs:
        st.error(e)
    if not frames:
        st.stop()

    df = pd.concat(frames, ignore_index=True)

    unknown = check_unknown(df)
    if not unknown.empty:
        st.error('해석하지 못한 옵션이 있습니다. 설정 시트를 확인한 뒤 다시 올려주세요.')
        st.dataframe(unknown, use_container_width=True, hide_index=True)
        st.stop()

    st.subheader('3. 결과')
    ok, held, remain = allocate(df, stock)
    conf = df[df['_키'].isin(ok)]
    pri = top_priority(held, 3)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('주문 묶음', df['_묶음'].nunique())
    c2.metric('출고 확정', conf['_묶음'].nunique())
    c3.metric('보류', len(held))
    c4.metric('확정 물량', f"{int(conf['_kg'].sum()):,}kg")

    st.markdown('**재고 현황**')
    need = df.groupby('_sku')['_kg'].sum()
    rows = []
    for gname, mode, items in STOCK_GROUPS:
        for label, sku in items:
            nd = float(need.get(sku, 0))
            if nd == 0 and stock[sku] == 0:
                continue
            rows.append({'구분': gname, '품목': label,
                         '포대': stock[sku] // BAG_KG if mode == 'bag' else '',
                         '잔여kg': stock[sku] % BAG_KG if mode == 'bag' else '',
                         '총 재고': stock[sku], '소요': int(nd),
                         '과부족': int(stock[sku] - nd)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if pri:
        st.markdown('**우선 생산 품목**')
        st.caption('앞 순위를 채운 상태에서 다음을 계산했습니다. 건수가 겹치지 않으니 그대로 더하시면 됩니다.')
        st.dataframe(pd.DataFrame([
            {'순위': p['순위'], '품목': p['sku'], '필요량': f"{p['필요kg']:.0f}kg",
             '해소 건수': f"{p['해소건수']}건"} for p in pri]),
            use_container_width=True, hide_index=True)

    if held:
        st.markdown('**보류**')
        st.caption('발송 처리를 하지 않으므로 내일 파일에 다시 나옵니다.')
        hc = pd.Series([o['채널'] for o in held]).value_counts().reset_index()
        hc.columns = ['채널', '보류 건수']
        st.dataframe(hc, use_container_width=True, hide_index=True)

    st.subheader('4. 내려받기')
    if conf.empty:
        st.warning('출고 확정 건이 없습니다. 재고를 확인해 주세요.')
        st.stop()

    counts, buffers = {}, {}
    for chan, (raw, cfg) in raws.items():
        keys = set(conf[conf['_채널'] == chan]['_키'])
        sheet = '발송처리' if chan == '스마트스토어' else None
        data, n = channel_file(raw, cfg['고유키'], keys, sheet)
        counts[chan], buffers[chan] = n, data

    okall, msgs = verify(conf, counts)
    (st.success if okall else st.error)(' · '.join(msgs))
    if not okall:
        st.warning('검증에 실패했습니다. 내려받기 전에 원인을 확인하세요.')

    pk_bytes, pk = packing_list(conf)
    d1, d2 = st.columns(2)
    d1.download_button('통합시트', integrated_sheet(conf), '통합시트.xlsx',
                       use_container_width=True)
    d2.download_button('패킹리스트', pk_bytes, '패킹리스트.xlsx',
                       use_container_width=True)
    dc = st.columns(max(len(buffers), 1))
    for i, (chan, data) in enumerate(buffers.items()):
        dc[i].download_button(f'{chan} 발송처리 ({counts[chan]}행)', data,
                              f'{chan}_발송처리.xlsx', use_container_width=True)

    with st.expander('패킹리스트 미리보기'):
        st.dataframe(pk, use_container_width=True, hide_index=True)

# ---------------- 기록 ----------------
with tab2:
    st.subheader('기록')
    st.info('출고·보류·재고 이력이 쌓이면 여기서 조회합니다. '
            '구글 시트 저장을 붙인 뒤 열립니다.')

# ---------------- 예측 ----------------
with tab3:
    st.subheader('예측')
    st.info('요일별 실출고 평균과 예측 대비 편차를 보여줍니다. '
            '기록이 4주 정도 쌓여야 의미 있는 숫자가 나옵니다.')

# ---------------- 설정 ----------------
with tab4:
    st.subheader('채널 설정')
    st.caption('구글 시트에서 읽어옵니다. 채널을 추가하거나 컬럼명이 바뀌면 시트를 고치세요.')
    st.dataframe(pd.DataFrame(CHANNELS), use_container_width=True, hide_index=True)

    st.subheader('재고 SKU')
    st.dataframe(pd.DataFrame([
        {'구분': g, '입력': '포대·잔여kg' if m == 'bag' else '개수',
         '품목': lb, '재고 SKU': sku}
        for g, m, items in STOCK_GROUPS for lb, sku in items]),
        use_container_width=True, hide_index=True)

    st.subheader('배송팀 재고 화면')
    st.caption('아래 주소를 태블릿 홈 화면에 바로가기로 걸어두세요.')
    st.code('현재 주소 뒤에 ?view=stock 을 붙이면 됩니다', language=None)
