"""Draw PDF-point citation rectangles over a rendered page for visual debugging."""
import argparse,json
from pathlib import Path

def render(pdf_path,page_number,bboxes,output,dpi=144):
    import fitz
    with fitz.open(pdf_path) as pdf:
        if not 1<=page_number<=len(pdf): raise ValueError('Page outside PDF')
        page=pdf[page_number-1]
        for coords in bboxes:
            rect=fitz.Rect(coords)
            if not rect.is_valid or rect.is_empty: raise ValueError('Invalid bounding box')
            page.draw_rect(rect,color=(1,0,0),fill=(1,0,0),fill_opacity=.2,overlay=True,width=1)
        pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
        pix.save(output)
    return output

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf');parser.add_argument('citation_json',help='JSON file containing one Citation object')
    parser.add_argument('--output',default='highlight_debug.png');parser.add_argument('--dpi',type=int,default=144)
    args=parser.parse_args(); citation=json.loads(Path(args.citation_json).read_text())
    if not citation.get('page') or not citation.get('bboxes'):parser.error('Citation must contain page and bboxes')
    print(render(args.pdf,citation['page'],citation['bboxes'],args.output,args.dpi))
if __name__=='__main__':main()
