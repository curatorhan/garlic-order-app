# -*- coding: utf-8 -*-
import io
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st

from config import load_channels, STOCK_GROUPS, STOCK_SKUS, BAG_KG
from core import read_orders, check_unknown, allocate, top_priority
from build import integrated_sheet, packing_list, channel_file, verify
import sheets

st.set_page_config(page_title='주문 처리', page_icon='🧄', layout='wide')

# 태블릿용 재고 전용 화면:  ...streamlit.app/?view=stock
VIEW = st.query_params.get('view', '')


GROUP_COLORS = ['#4F7A45', '#9A6B2F', '#6B5B95', '#3F6E82']


def section_header(num, title, sub, color, bg):
    st.markdown(
        f"<div style='background:{bg};border-left:5px solid {color};"
        f"border-radius:6px;padding:10px 16px;margin:6px 0 14px'>"
        f"<span style='font-size:18px;font-weight:600;color:{color}'>{num}. {title}</span>"
        f"<span style='font-size:13px;color:#6b6b6b;margin-left:12px'>{sub}</span></div>",
        unsafe_allow_html=True)


def stock_inputs(prefix=''):
    """재고 입력 칸. 종류별로 테두리를 둘러 구분한다."""
    stock = {}
    cols = st.columns(len(STOCK_GROUPS))
    for gi, (gname, mode, items) in enumerate(STOCK_GROUPS):
        color = GROUP_COLORS[gi % len(GROUP_COLORS)]
        with cols[gi]:
            with st.container(border=True):
                st.markdown(
                    f"<div style='border-bottom:2px solid {color};padding-bottom:6px;"
                    f"margin-bottom:10px'>"
                    f"<span style='font-size:15px;font-weight:600;color:{color}'>{gname}</span>"
                    f"<span style='font-size:12px;color:#8a8a8a;float:right;padding-top:3px'>"
                    f"{'포대 · 잔여kg' if mode == 'bag' else '개수'}</span></div>",
                    unsafe_allow_html=True)
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
                        stock[sku] = c1.number_input('개수', 0, 9999, 0,
                                                     key=f'{prefix}c_{sku}',
                                                     label_visibility='collapsed')
    return stock


# ============ 재고 전용 화면 (배송팀 태블릿) ============
if VIEW == 'stock':
    st.title('오늘의 재고')
    st.caption('포대 20kg 기준 · 없는 품목은 0으로 두세요')

    if not sheets.enabled():
        stock_inputs('s_')
        st.info('저장 설정이 아직 없습니다. 이 숫자를 CS에 알려주세요.')
        st.stop()

    prev, saved_at, err = sheets.read_stock()
    if saved_at:
        st.caption(f'마지막 저장 · {saved_at}')

    # 폼으로 묶어 칸마다 화면이 다시 그려지지 않게 한다
    with st.form('stock_form', border=False):
        stock = stock_inputs('s_')
        submitted = st.form_submit_button('저장', type='primary',
                                          use_container_width=True)

    if submitted:
        items = []
        for _g, mode, _items in STOCK_GROUPS:
            for _lb, sku in _items:
                kg = stock[sku]
                items.append({'sku': sku,
                              'bag': kg // BAG_KG if mode == 'bag' else 0,
                              'rest': kg % BAG_KG if mode == 'bag' else 0,
                              'kg': kg})
        at, e2 = sheets.save_stock(items)
        if e2:
            st.error(e2)
        else:
            sheets.clear_cache()
            st.success(f'저장했습니다 · {at} · 총 {sum(stock.values()):,}kg')
    st.stop()


# ============ 메인 화면 ============
st.title('주문 처리')
try:
    CHANNELS = load_channels()
except Exception as e:
    st.error(f'설정 시트를 읽지 못했습니다. {e}')
    st.stop()

st.caption('사용 채널 · ' + ' / '.join(c['채널'] for c in CHANNELS))

# ---------------- 일일 처리 ----------------
def daily_tab():
    skip = st.checkbox('재고 없이 진행 — 올린 파일 전체를 확정합니다',
                       key='skip_stock')

    if skip:
        st.markdown(
            "<div style='background:#FDF1EC;border-left:5px solid #A8442A;"
            "border-radius:6px;padding:10px 16px;margin:6px 0 14px;font-size:14px;"
            "color:#A8442A'>재고를 확인하지 않습니다. 업소용·긴급건 전용으로만 쓰세요."
            "</div>", unsafe_allow_html=True)
        stock = None
    elif sheets.enabled():
        section_header(1, '재고', '배송팀이 저장한 값입니다', '#3F6B46', '#EDF5EE')
        prev, saved_at, err = sheets.read_stock()
        if err:
            st.error(err)
            return
        stock = {sku: prev['kg'].get(sku, 0)
                 for _g, _m, its in STOCK_GROUPS for _lb, sku in its}
        if sum(stock.values()) == 0:
            st.warning('재고 입력을 기다리는 중입니다. 배송팀이 저장하면 여기에 나옵니다.')
            return
        c_a, c_b = st.columns([5, 1])
        c_a.caption(f'{saved_at} 기준' if saved_at else '')
        if c_b.button('새로고침', use_container_width=True):
            sheets.clear_cache()
            st.rerun()
        cols = st.columns(len(STOCK_GROUPS))
        for gi, (gname, mode, items) in enumerate(STOCK_GROUPS):
            color = GROUP_COLORS[gi % len(GROUP_COLORS)]
            with cols[gi]:
                with st.container(border=True):
                    st.markdown(
                        f"<div style='border-bottom:2px solid {color};padding-bottom:6px;"
                        f"margin-bottom:8px'><span style='font-size:15px;font-weight:600;"
                        f"color:{color}'>{gname}</span></div>", unsafe_allow_html=True)
                    for label, sku in items:
                        kg = stock[sku]
                        sub = (f"{kg // BAG_KG}포대 {kg % BAG_KG}kg"
                               if mode == 'bag' else f'{kg}개')
                        st.markdown(
                            f"<div style='display:flex;justify-content:space-between;"
                            f"font-size:14px;padding:3px 0'><span>{label}</span>"
                            f"<span style='font-weight:600'>{sub}</span></div>",
                            unsafe_allow_html=True)
        st.metric('총 재고', f'{sum(stock.values()):,}kg')
    else:
        section_header(1, '재고 입력', '포대 20kg 기준 · 재고가 없는 품목은 0으로 두세요',
                       '#3F6B46', '#EDF5EE')
        stock = stock_inputs()
        st.metric('총 재고', f'{sum(stock.values()):,}kg')

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
    section_header(2, '주문 파일 업로드', '여러 개를 한 번에 올리세요. 채널은 자동으로 판별합니다.',
                   '#2F6FA8', '#EDF3FA')
    files = st.file_uploader('주문 파일', type=['xlsx', 'xls'],
                             accept_multiple_files=True, label_visibility='collapsed')
    if not files:
        st.info('주문 파일을 올리면 결과가 나옵니다.')
        return

    frames, raws, errs = [], [], []
    for f in files:
        d, ch, w = read_orders(f, CHANNELS)
        errs += w
        if d is None:
            errs.append(f'{f.name} · 읽지 못했습니다.')
            continue
        frames.append(d)
        f.seek(0)
        # 같은 채널 파일이 여러 개여도 파일 단위로 그대로 둔다
        raws.append({'name': f.name,
                     'raw': pd.read_excel(f, header=ch['헤더행'] - 1),
                     'cfg': ch})
        st.write(f"**{f.name}** → {ch['채널']} · {len(d)}행")
    for e in dict.fromkeys(errs):
        st.error(e)
    if not frames:
        return

    df = pd.concat(frames, ignore_index=True)

    unknown = check_unknown(df)
    if not unknown.empty:
        st.error('해석하지 못한 옵션이 있습니다. 설정 시트를 확인한 뒤 다시 올려주세요.')
        st.dataframe(unknown, use_container_width=True, hide_index=True)
        return

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
    section_header(3, '결과', '', '#8A6D3B', '#FAF5EC')
    if stock is None:
        ok, held = set(df['_키']), []
    else:
        ok, held, _remain = allocate(df, stock)
    conf = df[df['_키'].isin(ok)]
    pri = top_priority(held, 3)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('주문 묶음', df['_묶음'].nunique())
    c2.metric('출고 확정', conf['_묶음'].nunique())
    c3.metric('보류', len(held))
    c4.metric('확정 물량', f"{int(conf['_kg'].sum()):,}kg")

    need = df.groupby('_sku')['_kg'].sum()
    rows = []
    for gname, mode, items in STOCK_GROUPS:
        for label, sku in items:
            if stock is None:
                continue
            nd = float(need.get(sku, 0))
            if nd == 0 and stock[sku] == 0:
                continue
            rows.append({'구분': gname, '품목': label,
                         '포대': stock[sku] // BAG_KG if mode == 'bag' else '',
                         '잔여kg': stock[sku] % BAG_KG if mode == 'bag' else '',
                         '총 재고': stock[sku], '소요': int(nd),
                         '과부족': int(stock[sku] - nd)})
    if stock is not None:
        st.markdown('**재고 현황**')
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

    st.markdown('<div style="height:18px"></div>', unsafe_allow_html=True)
    section_header(4, '내려받기', '', '#6B5B95', '#F3F0F7')
    if conf.empty:
        st.warning('출고 확정 건이 없습니다. 재고를 확인해 주세요.')
        return

    counts, outs = {}, []
    for item in raws:
        chan = item['cfg']['채널']
        keys = set(conf[conf['_채널'] == chan]['_키'])
        sheet = '발송처리' if chan == '스마트스토어' else None
        data, n = channel_file(item['raw'], item['cfg']['고유키'], keys, sheet)
        counts[chan] = counts.get(chan, 0) + n
        stem = item['name'].rsplit('.', 1)[0]
        outs.append({'chan': chan, 'stem': stem, 'data': data, 'n': n})

    okall, msgs = verify(conf, counts)
    if okall:
        st.success(' · '.join(msgs))
    else:
        st.error('검증 실패 — 아래 내용을 확인한 뒤 내려받으세요.')
        for m in msgs:
            st.markdown(f'- {m}')

    pk_bytes, pk = packing_list(conf)
    integ = integrated_sheet(conf)
    stamp = datetime.now().strftime('%Y%m%d')

    # 전체를 zip 하나로
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'통합시트_{stamp}.xlsx', integ)
        z.writestr(f'패킹리스트_{stamp}.xlsx', pk_bytes)
        for o in outs:
            z.writestr(f"발송처리/{o['stem']}_발송처리.xlsx", o['data'])
    st.download_button(f'전체 내려받기 (zip · 파일 {2 + len(outs)}개)',
                       zbuf.getvalue(), f'주문처리_{stamp}.zip',
                       type='primary', use_container_width=True)

    with st.expander('파일 하나씩 받기'):
        d1, d2 = st.columns(2)
        d1.download_button('통합시트', integ, '통합시트.xlsx',
                           use_container_width=True)
        d2.download_button('패킹리스트', pk_bytes, '패킹리스트.xlsx',
                           use_container_width=True)
        for i in range(0, len(outs), 2):
            cols = st.columns(2)
            for j, o in enumerate(outs[i:i + 2]):
                label = o['stem'] if len(o['stem']) <= 28 else o['stem'][:26] + '…'
                cols[j].download_button(f"{label} · {o['n']}행", o['data'],
                                        f"{o['stem']}_발송처리.xlsx",
                                        use_container_width=True,
                                        key=f"dl_{i}_{j}")

    with st.expander('패킹리스트 미리보기'):
        st.dataframe(pk, use_container_width=True, hide_index=True)

    if sheets.enabled():
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        today = datetime.now()
        day = today.strftime('%Y-%m-%d')
        wd = ['월', '화', '수', '목', '금', '토', '일'][today.weekday()]

        done, r_err = sheets.read_rounds(day)
        auto = (max(done) + 1) if done else 1
        opts = sorted(set(done) | {auto})

        c1, c2 = st.columns([1, 3])
        rd = c1.selectbox('차수', opts, index=opts.index(auto),
                          format_func=lambda x: f'{x}차')
        note = (f"오늘 저장된 차수 · {', '.join(f'{d}차' for d in done)}"
                if done else '오늘 저장된 기록이 없습니다')
        if rd in done:
            note += f' · {rd}차를 덮어씁니다'
        c2.markdown(f"<div style='padding-top:30px;font-size:13.5px;color:#808495'>"
                    f"{note}</div>", unsafe_allow_html=True)
        if r_err:
            st.warning(r_err)

        if st.button(f'{rd}차로 기록 저장', use_container_width=True):
            st.session_state['confirm_save'] = rd

        if st.session_state.get('confirm_save') == rd:
            msg = (f'{day} ({wd}) {rd}차로 저장합니다.'
                   + (' 기존 기록을 덮어씁니다.' if rd in done else ''))
            st.info(msg)
            cc1, cc2 = st.columns(2)
            if cc1.button('저장', type='primary', use_container_width=True):
                out_rows = [{'sku': s, 'kg': int(v)}
                            for s, v in conf.groupby('_sku')['_kg'].sum().items()]
                agg = {}
                for o in held:
                    for s, v in o['부족'].items():
                        x = agg.setdefault(s, [0, 0.0])
                        x[0] += 1
                        x[1] += v
                hold_rows = [{'sku': s, 'cnt': c, 'kg': int(k)}
                             for s, (c, k) in agg.items()]
                e = sheets.save_log(day, wd, rd, out_rows, hold_rows)
                st.session_state['confirm_save'] = None
                if e:
                    st.error(e)
                else:
                    st.success(f'{day} ({wd}) {rd}차 · 출고 {len(out_rows)}행 · '
                               f'보류 {len(hold_rows)}행 저장했습니다.')
            if cc2.button('취소', use_container_width=True):
                st.session_state['confirm_save'] = None
                st.rerun()


daily_tab()

# ---------------- 설정 (접이식) ----------------
with st.expander('설정 보기'):
    st.markdown('**채널 설정**')
    st.caption('구글 시트에서 읽어옵니다. 채널을 추가하거나 컬럼명이 바뀌면 시트를 고치세요.')
    st.dataframe(pd.DataFrame(CHANNELS), use_container_width=True, hide_index=True)

    st.markdown('**재고 SKU**')
    st.dataframe(pd.DataFrame([
        {'구분': g, '입력': '포대·잔여kg' if m == 'bag' else '개수',
         '품목': lb, '재고 SKU': sku}
        for g, m, items in STOCK_GROUPS for lb, sku in items]),
        use_container_width=True, hide_index=True)

    st.markdown('**배송팀 재고 화면**')
    st.caption('현재 주소 뒤에 ?view=stock 을 붙이면 재고 입력 전용 화면이 열립니다.')


