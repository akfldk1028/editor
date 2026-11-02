def needs_refresh(row, now, max_age=3600):
    return row.get('state')!='checked' or 'checkedAt' not in row or now-row['checkedAt']>=max_age

def undiscovered(rows, available):
    return [row for row in rows if row['num'] not in available]


def area_query_form(a, b, c, d):
    return dict(minx=str(a), miny=str(b), maxx=str(c), maxy=str(d),
                wkt=f'POLYGON(({a} {b},{c} {b},{c} {d},{a} {d},{a} {b}))')
