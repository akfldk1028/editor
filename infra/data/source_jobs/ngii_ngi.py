"""Read measured contour/spot attributes joined to NGI geometry by record ID."""
import csv,math,re

def layers(text):
    result={}
    for block in text.split('<LAYER_START>')[1:]:
        name=re.search(r'\$LAYER_NAME\s+"([^"]+)"',block)
        if name and name[1] in ('F0010000','F0020000'):
            if name[1] in result:raise ValueError('Duplicate elevation layer')
            result[name[1]]=block
    return result

def records(block):
    if '<DATA>' not in block:raise ValueError('Missing data section')
    result={}
    for match in re.finditer(r'\$RECORD\s+(\d+)\s*\n([\s\S]*?)(?=\$RECORD|<END>|$)',block.split('<DATA>',1)[1]):
        if match[1] in result:raise ValueError('Duplicate record')
        result[match[1]]=[line.strip() for line in match[2].splitlines() if line.strip()]
    return result

def parse_elevation(geometry,attributes):
    chunks=[];contours=spots=0;nda=layers(attributes)
    for name,block in layers(geometry).items():
        if name not in nda:raise ValueError('Missing attribute layer')
        fields=re.findall(r'ATTRIB\("([^"]+)"',nda[name].split('<DATA>',1)[0])
        column='등고수치' if name=='F0010000' else '수치'
        if column not in fields:raise ValueError('Missing measured height field')
        values=records(nda[name])
        for key,lines in records(block).items():
            if key not in values:raise ValueError('Missing measured height record')
            row=next(csv.reader([values[key][0]],skipinitialspace=True))
            z=float(row[fields.index(column)])
            if not math.isfinite(z) or not -500<=z<=9000:raise ValueError('Invalid elevation')
            kind=lines[0]
            if kind=='LINESTRING' and name=='F0010000':
                count=int(lines[1]);coordinates=lines[2:2+count]
                if len(coordinates)!=count or count<2:raise ValueError('Truncated line')
                contours+=1
            elif kind=='POINT' and name=='F0020000':coordinates=lines[1:2];spots+=1
            else:raise ValueError('Unsupported elevation geometry')
            points=[]
            for line in coordinates:
                xy=[float(v) for v in line.split()]
                if len(xy) not in (2,3) or not all(math.isfinite(v) for v in xy):raise ValueError('Invalid coordinates')
                points.append((xy[0],xy[1],z))
            chunks.append(points)
    return chunks,contours,spots
