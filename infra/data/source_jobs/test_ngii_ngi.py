import unittest
from ngii_ngi import parse_elevation

def layer(name,data,fields=''):
    return f'<LAYER_START>\n$LAYER_ID\n16\n$END\n$LAYER_NAME\n"{name}"\n$END\n<HEADER>\n{fields}\n<END>\n<DATA>\n{data}\n<END>\n<LAYER_END>'

class NGITests(unittest.TestCase):
    def test_height_join_uses_record_id_and_named_column(self):
        ngi=layer('F0010000','$RECORD 7\nLINESTRING\n2\n1 2\n3 4\nLINEGATTR(1)\n$RECORD 8\nLINESTRING\n2\n5 6\n7 8')
        nda=layer('F0010000','$RECORD 8\n88,8\n$RECORD 7\n77,7','ATTRIB("등고수치",NUMERIC,9,2,TRUE)\nATTRIB("ID",NUMERIC,9,0,TRUE)')
        chunks,c,s=parse_elevation(ngi,nda)
        self.assertEqual(chunks[0],[(1.,2.,77.),(3.,4.,77.)])
        self.assertEqual((c,s),(2,0))

    def test_missing_attribute_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_elevation(layer('F0020000','$RECORD 9\nPOINT\n1 2'),layer('F0020000','$RECORD 8\n3','ATTRIB("수치",NUMERIC,9,2,TRUE)'))

    def test_spot_height_not_zero_from_2d_coordinates(self):
        chunks,c,s=parse_elevation(layer('F0020000','$RECORD 9\nPOINT\n1 2'),layer('F0020000','$RECORD 9\n123.45','ATTRIB("수치",NUMERIC,9,2,TRUE)'))
        self.assertEqual(chunks,[[(1.,2.,123.45)]])
        self.assertEqual((c,s),(0,1))

if __name__=='__main__':unittest.main()
