import re
from pathlib import Path
import numpy as np
from rapidocr import RapidOCR

from app.config import WEIGHTS


def nik_match(line):
    # Normalize separators inside one OCR line, never merge digits across lines
    # or guess O/I as 0/1. Exact card equality is checked later.
    compact = re.sub(r'(?<=\d)[ \t-]+(?=\d)', '', line)
    return re.search(r'(?<!\d)\d{16}(?!\d)', compact)


def parse_identity(lines):
    text = '\n'.join(lines).upper()
    match = next((m for line in lines if (m := nik_match(line))), None)
    fields = {'nik': match.group() if match else '', 'name': '', 'birth': '', 'address': ''}
    for i, line in enumerate(lines):
        for label, key in [('NAMA', 'name'), ('ALAMAT', 'address')]:
            if re.match(r'^\s*'+label+r'\b', line, re.I):
                value = re.sub(r'^\s*'+label+r'\s*:?\s*', '', line, flags=re.I).strip()
                fields[key] = value or (lines[i+1].strip(': ') if i+1 < len(lines) else '')
    birthday = re.search(r'\b(\d{2})[-/](\d{2})[-/](\d{4})\b', text)
    if birthday:
        fields['birth'] = f'{birthday[3]}-{birthday[2]}-{birthday[1]}'
    return fields


class OCRService:
    def __init__(self):
        self.engine = None

    def load(self):
        if self.engine is None:
            self.engine = RapidOCR(params={'Global.model_root_dir': str(WEIGHTS / 'ocr'), 'Rec.lang_type': 'en', 'Global.text_score': .40})
        return self.engine

    def read(self, image):
        result = self.load()(image)
        lines = list(result.txts or [])
        scores = [float(v) for v in (result.scores or [])]
        return {'fields': parse_identity(lines), 'lines': lines,
                'confidence': float(np.mean(scores)) if scores else 0.0,
                'boxes': result.boxes.tolist() if result.boxes is not None else [],
                'engine': 'RapidOCR / PaddleOCR ONNX', 'mode': 'real'}
