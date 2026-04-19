import os
from pathlib import Path

print('WINDIR:', os.environ.get('WINDIR', 'C:/Windows'))
fonts = ['arialuni.ttf', 'ARIALUNI.TTF', 'SegoeUI.ttf', 'calibri.ttf', 'arial.ttf', 'times.ttf', 'DejaVuSans.ttf']
for f in fonts:
    p = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / f
    print(f, p.exists(), p)

try:
    from app import get_pdf_font_name
    print('get_pdf_font_name =>', get_pdf_font_name())
except Exception as e:
    print('error importing app/get_pdf_font_name:', e)
