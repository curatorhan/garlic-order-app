# -*- coding: utf-8 -*-
"""구글 시트 읽기·쓰기 (Apps Script 웹 앱 경유)

Streamlit secrets 에 아래 두 값을 넣어야 동작합니다.
    GS_URL   = "https://script.google.com/macros/s/..../exec"
    GS_TOKEN = "Apps Script 의 TOKEN 과 같은 값"
"""
import json
import requests
import streamlit as st

TIMEOUT = 20


def _conf():
    url = st.secrets.get('GS_URL', '')
    token = st.secrets.get('GS_TOKEN', '')
    return url, token


def enabled():
    url, token = _conf()
    return bool(url and token)


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_stock(url, token):
    r = requests.get(url, params={'token': token, 'action': 'stock'},
                     timeout=TIMEOUT)
    return r.json()


def clear_cache():
    _fetch_stock.clear()


def read_stock():
    """저장된 재고를 읽는다. (stock, saved_at, error) 반환"""
    url, token = _conf()
    if not (url and token):
        return {}, '', '저장 설정이 없습니다.'
    try:
        d = _fetch_stock(url, token)
    except Exception as e:
        return {}, '', f'시트를 읽지 못했습니다. {e}'
    if not d.get('ok'):
        return {}, '', d.get('error', '알 수 없는 오류')
    stock = {k: int(v.get('kg', 0)) for k, v in d.get('stock', {}).items()}
    raw = {k: (int(v.get('bag', 0)), int(v.get('rest', 0)))
           for k, v in d.get('stock', {}).items()}
    return {'kg': stock, 'raw': raw}, d.get('saved_at', ''), ''


def save_stock(items):
    """items: [{'sku','bag','rest','kg'}]  → (saved_at, error)"""
    url, token = _conf()
    if not (url and token):
        return '', '저장 설정이 없습니다.'
    try:
        r = requests.post(url, data=json.dumps(
            {'token': token, 'action': 'save_stock', 'items': items}),
            headers={'Content-Type': 'application/json'}, timeout=TIMEOUT)
        d = r.json()
    except Exception as e:
        return '', f'저장하지 못했습니다. {e}'
    if not d.get('ok'):
        return '', d.get('error', '알 수 없는 오류')
    return d.get('saved_at', ''), ''


def save_log(date, weekday, out_rows, hold_rows):
    """출고·보류 기록 저장. 같은 날짜는 덮어쓴다. error 문자열 반환"""
    url, token = _conf()
    if not (url and token):
        return '저장 설정이 없습니다.'
    try:
        r = requests.post(url, data=json.dumps({
            'token': token, 'action': 'save_log', 'date': date,
            'weekday': weekday, 'out': out_rows, 'hold': hold_rows}),
            headers={'Content-Type': 'application/json'}, timeout=TIMEOUT)
        d = r.json()
    except Exception as e:
        return f'저장하지 못했습니다. {e}'
    if not d.get('ok'):
        return d.get('error', '알 수 없는 오류')
    return ''
