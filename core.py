# -*- coding: utf-8 -*-
"""옵션 파싱 · 파일 적재 · 재고 배정"""
import re
import pandas as pd
from collections import defaultdict
from config import STOCK_SKUS, KNOWN_SKUS, BAG_KG

GRADES = ['특대', '대', '중', '소']

# ---------- 옵션 파싱 ----------

def _strip_prefix(s):
    return s.rsplit(':', 1)[-1].strip() if ':' in s else s.strip()

def _clean(s):
    s = re.sub(r'[（(][^）)]*[）)]', ' ', str(s))
    s = s.replace('&#91;', ' ').replace('&#93;', ' ').replace('[', ' ').replace(']', ' ')
    return re.sub(r'\s+', ' ', s).strip()

def _body(raw, sep):
    """채널별 구분자 규칙에 따라 옵션 본문만 남긴다"""
    s = str(raw).strip()
    if sep == '슬래시_뒤':      # 스마트스토어: 슬래시=옵션 단계
        part = s.split('/')[-1]
    elif sep == '슬래시_앞':    # ESM: 슬래시=옵션명/추가금/개수
        part = s.split('/')[0]
    elif sep == '하이픈_앞':    # 11번가: 하이픈=개수
        part = s.split('-')[0]
    else:
        part = s
    return _clean(_strip_prefix(part))

def parse_option(raw, sep, aux='', def_variety='', def_trim=''):
    """옵션(없으면 상품명)에서 SKU 요소를 뽑는다"""
    raw = '' if raw is None or str(raw).lower() == 'nan' else str(raw)
    aux = '' if aux is None or str(aux).lower() == 'nan' else str(aux)
    src = raw if raw.strip() else aux          # 옵션이 비면 상품명 사용
    body = _body(src, sep)
    whole = _clean(src + ' ' + aux)            # 형태·품종은 전체에서 탐색

    m = re.search(r'(\d+(?:\.\d+)?)\s*[kK][gG]', body) or \
        re.search(r'(\d+(?:\.\d+)?)\s*[kK][gG]', whole)
    weight = float(m.group(1)) if m else None
    if weight and weight == int(weight):
        weight = int(weight)
    nokg = re.sub(r'\d+(?:\.\d+)?\s*[kK][gG]', ' ', body)

    if '마늘쫑' in whole or '마늘종' in whole:
        form = '마늘쫑'
    elif '다진' in whole:
        form = '다진마늘'
    elif '통마늘' in whole:
        form = '통마늘'
    elif '깐마늘' in whole:
        form = '깐마늘'
    else:
        form = None

    if '육쪽' in whole or '토종' in whole:
        variety = '토종'
    elif '대서' in whole:
        variety = '대서'
    else:
        variety = def_variety or None

    if '꼭지제거' in whole.replace(' ', ''):
        trim = '꼭지제거'
    elif '통째로' in whole:
        trim = '통째로'
    else:
        trim = (def_trim or None) if form == '다진마늘' else None

    grade = None
    if form in ('깐마늘', '통마늘'):
        tmp = nokg.replace('대서', '').replace('육쪽', '').replace('토종', '').replace('꼭지제거', '')
        for g in GRADES:
            if re.search(rf'(?<![가-힣]){g}(?![가-힣])', tmp):
                grade = g; break
        if grade is None:   # 상품명 뒤 괄호에 등급이 오는 경우 (우체국쇼핑)
            tmp2 = _clean(re.sub(r'\d+(?:\.\d+)?\s*[kK][gG]', ' ', whole))
            for g in GRADES:
                if re.search(rf'(?<![가-힣]){g}(?![가-힣])', tmp2):
                    grade = g; break

    business = (form == '깐마늘' and weight in (5, 10))

    def build(with_weight):
        p = []
        if variety and form in ('깐마늘', '다진마늘'): p.append(variety)
        if form != '깐마늘': p.append(form)
        if grade: p.append(grade)
        if trim: p.append(trim)
        if with_weight and weight: p.append(f'{weight}kg')
        return ' '.join(p)

    return dict(form=form, variety=variety, grade=grade, trim=trim, weight=weight,
                sku=build(False), label=build(True), business=business)

# ---------- 파일 적재 ----------

def detect_channel(df_cols, channels):
    for ch in channels:
        key = ch['판별컬럼']
        if key and key in df_cols:
            return ch
    return None

def read_orders(file, channels):
    """업로드 파일 하나를 읽어 표준 형태로 변환. (df, 채널, 경고) 반환"""
    warns = []
    raw = None
    for ch in channels:
        try:
            t = pd.read_excel(file, header=ch['헤더행'] - 1)
        except Exception:
            continue
        if ch['판별컬럼'] and ch['판별컬럼'] in t.columns:
            raw, chan = t, ch
            break
    if raw is None:
        return None, None, ['어느 채널인지 판별하지 못했습니다. 설정 시트의 판별컬럼을 확인하세요.']

    need = ['고유키', '합배송키', '옵션', '수량', '수취인', '연락처', '우편번호', '주소', '주문일시']
    for k in need:
        col = chan[k]
        if col and col not in raw.columns:
            return None, chan, [f"[{chan['채널']}] '{col}' 컬럼이 파일에 없습니다. 양식이 바뀌었는지 확인하세요."]

    d = pd.DataFrame()
    d['_원본행'] = raw.index
    d['_채널'] = chan['채널']
    d['_순위'] = chan['배정순위']
    d['_키'] = raw[chan['고유키']].astype(str).str.strip()
    d['_묶음'] = chan['채널'] + '_' + raw[chan['합배송키']].astype(str).str.strip()
    d['_수량'] = pd.to_numeric(raw[chan['수량']], errors='coerce').fillna(1).astype(int)
    d['_수취인'] = raw[chan['수취인']].astype(str).str.strip()
    d['_연락처'] = raw[chan['연락처']].astype(str).str.strip()
    d['_우편'] = raw[chan['우편번호']].astype(str).str.strip()
    addr = raw[chan['주소']].fillna('').astype(str)
    if chan.get('주소2') and chan['주소2'] in raw.columns:
        addr = addr + ' ' + raw[chan['주소2']].fillna('').astype(str)
    d['_주소'] = addr.str.strip()
    msg = chan.get('배송메시지', '')
    d['_메시지'] = raw[msg].fillna('').astype(str) if msg and msg in raw.columns else ''
    d['_일시'] = pd.to_datetime(raw[chan['주문일시']], errors='coerce')

    aux_col = chan.get('옵션보조', '')
    aux = raw[aux_col] if aux_col and aux_col in raw.columns else pd.Series([''] * len(raw))
    recs = [parse_option(o, chan['옵션구분자'], a,
                         chan.get('기본품종', ''), chan.get('기본꼭지', ''))
            for o, a in zip(raw[chan['옵션']], aux)]
    d['_sku'] = [r['sku'] for r in recs]
    d['_표기'] = [r['label'] for r in recs]
    d['_중량'] = [r['weight'] or 0 for r in recs]
    d['_업소용'] = [r['business'] for r in recs]
    d['_원본옵션'] = raw[chan['옵션']].astype(str).values
    d['_kg'] = d['_중량'] * d['_수량']
    return d, chan, warns

def check_unknown(df):
    """파싱 실패·미등록 SKU 목록"""
    bad = df[(df['_중량'] == 0) | (~df['_sku'].isin(KNOWN_SKUS))]
    if bad.empty:
        return pd.DataFrame()
    return (bad.groupby(['_채널', '_원본옵션', '_sku'])
              .size().reset_index(name='건수')
              .rename(columns={'_채널': '채널', '_원본옵션': '원본 옵션', '_sku': '해석 결과'}))

# ---------- 배정 ----------

def allocate(df, stock):
    """묶음 단위 배정. 부족하면 묶음 전체 보류."""
    groups = {}
    for b, g in df.groupby('_묶음'):
        groups[b] = dict(묶음=b, 채널=g['_채널'].iloc[0], 순위=int(g['_순위'].iloc[0]),
                         업소용=bool(g['_업소용'].any()), 일시=g['_일시'].min(),
                         수취인=g['_수취인'].iloc[0], 키=set(g['_키']), rows=g)
    order = sorted(groups.values(), key=lambda o: (
        0 if o['업소용'] else 1,
        o['일시'].date() if pd.notna(o['일시']) else pd.Timestamp.max.date(),
        o['순위'],
        o['일시'] if pd.notna(o['일시']) else pd.Timestamp.max))

    remain = dict(stock)
    ok, held = set(), []
    for o in order:
        need = defaultdict(float)
        for _, r in o['rows'].iterrows():
            need[r['_sku']] += r['_kg']
        short = {s: v - remain.get(s, 0) for s, v in need.items() if remain.get(s, 0) < v}
        if short:
            held.append(dict(o, 부족=short)); continue
        for s, v in need.items():
            remain[s] -= v
        ok |= o['키']
    return ok, held, remain

def top_priority(held, top=3):
    """앞 순위를 채운 상태에서 다음 순위를 계산 → 건수 중복 없음"""
    rem = [dict(o['부족']) for o in held]
    filled, out = set(), []
    for _ in range(top):
        gain = defaultdict(int)
        for sh in rem:
            open_s = [s for s in sh if s not in filled]
            if len(open_s) == 1:
                gain[open_s[0]] += 1
        if not gain:
            break
        sku = max(gain, key=lambda s: gain[s])
        kg = sum(sh.get(sku, 0) for sh in rem if sku in sh)
        out.append(dict(순위=len(out) + 1, sku=sku, 필요kg=kg, 해소건수=gain[sku]))
        filled.add(sku)
        rem = [sh for sh in rem if not all(s in filled for s in sh)]
    return out
