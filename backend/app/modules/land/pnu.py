import re


def normalize_pnu(value: str) -> str:
    value = value.strip().replace('-', '')
    if not re.fullmatch(r'[0-9]{19}', value):
        raise ValueError('PNU requires 19 digits')
    return value


def parse_pnu(value: str) -> dict:
    pnu = normalize_pnu(value)
    return {
        'pnu': pnu, 'sido': pnu[:2], 'sigungu': pnu[2:5],
        'eupmyeondong': pnu[5:8], 'ri': pnu[8:10],
        'land_type': pnu[10:11], 'main_number': pnu[11:15],
        'sub_number': pnu[15:19],
        'land_type_name': {'1':'대', '2':'임야'}.get(pnu[10], '기타'),
    }
