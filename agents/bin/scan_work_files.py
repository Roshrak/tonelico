#!/usr/bin/env python3
"""
Scan Work Files - OCR & Company Sorting Tool
Scans all documents in ~/work files using local PaddleOCR / PaddleX,
extracts text, detects company / organization names, moves original files
into ~/original file/<YYYY-MM-DD>/ and writes OCR results into
~/scanned result/<YYYY-MM-DD>/<Company Name>/ with complete text transcripts.
"""

import os
import sys
import re
import shutil
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

# --- Self-bootstrap environment for NixOS & PaddleOCR ---
OCR_VENV_PYTHON = Path("/home/aesc/.local/share/hermes-ocr/venv/bin/python")
REQUIRED_LIBS = [
    "/run/current-system/sw/share/nix-ld/lib",
    "/home/aesc/.local/share/nix-roots/hermes-ocr-libgl/lib",
    "/home/aesc/.local/share/nix-roots/hermes-ocr-glib/lib",
]

current_ld = os.environ.get("LD_LIBRARY_PATH", "")
missing_libs = [p for p in REQUIRED_LIBS if p not in current_ld and os.path.exists(p)]
needs_reexec = False
new_env = os.environ.copy()

if missing_libs:
    new_ld = ":".join(missing_libs) + (":" + current_ld if current_ld else "")
    new_env["LD_LIBRARY_PATH"] = new_ld
    needs_reexec = True

if os.environ.get("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT") != "False":
    new_env["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "False"
    needs_reexec = True

if os.environ.get("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK") != "True":
    new_env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    needs_reexec = True

if sys.executable != str(OCR_VENV_PYTHON) and OCR_VENV_PYTHON.exists():
    needs_reexec = True

if needs_reexec and (not sys.argv or sys.argv[-1] != "--reexeced"):
    os.execve(str(OCR_VENV_PYTHON), [str(OCR_VENV_PYTHON), __file__, *sys.argv[1:], "--reexeced"], new_env)

if sys.argv and sys.argv[-1] == "--reexeced":
    sys.argv.pop()

# --- OCR & Document Processing Imports ---
try:
    import numpy as np
    from paddlex import create_pipeline
    PADDLEX_AVAILABLE = True
except Exception as e:
    PADDLEX_AVAILABLE = False
    paddlex_error = str(e)

try:
    import pypdfium2 as pdfium
    PDFIUM_AVAILABLE = True
except Exception:
    PDFIUM_AVAILABLE = False

DEFAULT_INPUT_DIR = Path("/home/aesc/work files")
DEFAULT_OUTPUT_DIR = Path("/home/aesc/scanned result")
DEFAULT_ORIGINAL_DIR = Path("/home/aesc/original file")

_pipeline_cache = None

def get_ocr_pipeline():
    global _pipeline_cache
    if _pipeline_cache is None:
        if not PADDLEX_AVAILABLE:
            raise RuntimeError(f"PaddleX not available: {globals().get('paddlex_error', 'unknown error')}")
        _pipeline_cache = create_pipeline(pipeline="OCR")
    return _pipeline_cache


def extract_text_from_image(image_path: Path) -> list[str]:
    pipeline = get_ocr_pipeline()
    output = pipeline.predict(str(image_path))
    lines = []
    for res in output:
        texts = res.get("rec_texts", [])
        lines.extend(texts)
    return lines


def extract_text_from_pdf(pdf_path: Path) -> list[str]:
    lines = []
    if not PDFIUM_AVAILABLE:
        raise RuntimeError("pypdfium2 not available for PDF processing")
    
    pipeline = get_ocr_pipeline()
    pdf = pdfium.PdfDocument(str(pdf_path))
    for page_idx in range(len(pdf)):
        page = pdf[page_idx]
        pil_image = page.render(scale=2).to_pil()
        img_array = np.array(pil_image)
        output = pipeline.predict(img_array)
        for res in output:
            texts = res.get("rec_texts", [])
            lines.extend(texts)
    return lines


def extract_text_from_docx(docx_path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(docx_path) as z:
            tree = ET.fromstring(z.read("word/document.xml"))
            lines = []
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [node.text for node in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t") if node.text]
                if texts:
                    line = "".join(texts).strip()
                    if line:
                        lines.append(line)
            return lines
    except Exception as e:
        return [f"[DOCX read error: {e}]"]


def extract_text_from_odt(odt_path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(odt_path) as z:
            tree = ET.fromstring(z.read("content.xml"))
            lines = []
            for p in tree.iter("{urn:oasis:names:tc:opendocument:xmlns:text:1.0}p"):
                p_text = "".join(p.itertext()).strip()
                if p_text:
                    lines.append(p_text)
            return lines
    except Exception as e:
        return [f"[ODT read error: {e}]"]


def sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', '', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip(" .-_,")
    if len(cleaned) > 80:
        cleaned = cleaned[:80].strip(" .-_,")
    return cleaned or "Unsorted"


def detect_company(lines: list[str], filename: str) -> str:
    full_text = "\n".join(lines)
    candidates = []

    # Priority 1: Known domain entities frequently used by user
    known_entities = [
        ("BACH GIA FOOD", "Bách Gia Food"),
        ("BÁCH GIA FOOD", "Bách Gia Food"),
        ("VINACONTROL", "Vinacontrol"),
        ("QUATEST", "Quatest"),
        ("CỤC QUẢN LÝ CHẤT LƯỢNG", "Cục Quản lý Chất lượng"),
        ("BỘ GIÁO DỤC", "Bộ Giáo dục và Đào tạo"),
        ("NORMANDIE", "Normandie"),
        ("ĐẠI HỌC GIAO THÔNG VẬN TẢI", "Đại học Giao thông vận tải"),
    ]
    for pattern, clean_name in known_entities:
        if pattern.lower() in full_text.lower() or pattern.lower() in filename.lower():
            candidates.append((clean_name, 120))

    # Priority 2: Key field labels
    field_patterns = [
        r"(?:Đơn vị yêu cầu(?:\s+và\s+gửi\s+mẫu)?|Khách hàng|Đơn vị gửi mẫu|Tên đơn vị|Thương nhân chịu trách nhiệm|Cơ sở sản xuất|Nhà sản xuất)\s*:\s*([^\n\r;]+)",
    ]
    for pat in field_patterns:
        m = re.search(pat, full_text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.split(r"(?:Địa chỉ|\d+\s*/\s*\d+|MST|Điện thoại|Tel|Email|Fax)", val, flags=re.IGNORECASE)[0]
            val = val.strip(" :,-.")
            if len(val) >= 4:
                candidates.append((val, 110))

    # Priority 3: Exact company prefix in document lines
    for line in lines:
        line_clean = line.strip()
        m = re.search(r"^(CÔNG TY\s+(?:TNHH|CỔ PHẦN|CP|TNHH\s+MTV|TNHH\s+MỘT\s+THÀNH\s+VIÊN)?\s+[^\d,;]{4,})", line_clean, re.IGNORECASE)
        if m:
            val = m.group(1).strip(" :,-.")
            val = re.split(r"(?:Địa chỉ|\d+\s*/\s*\d+|MST|Điện thoại|Tel)", val, flags=re.IGNORECASE)[0].strip(" :,-.")
            if len(val) >= 5:
                candidates.append((val, 100))

        # English company suffixes
        m_eng = re.search(r"([A-Z0-9\s\.\-]{3,}(?:CO\.,\s*LTD|COMPANY\s+LIMITED|CORPORATION|CORP|INC|LLC|JSC))", line_clean, re.IGNORECASE)
        if m_eng:
            val = m_eng.group(1).strip(" :,-.")
            candidates.append((val, 95))

        # Other organization types
        m_org = re.search(r"^((?:TẬP ĐOÀN|TRUNG TÂM|VIỆN|DOANH NGHIỆP TƯ NHÂN|CHI NHÁNH)\s+[^\d,;]{4,})", line_clean, re.IGNORECASE)
        if m_org:
            val = m_org.group(1).strip(" :,-.")
            candidates.append((val, 85))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return sanitize_folder_name(candidates[0][0])

    return "Unsorted"


def process_work_files(
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    original_dir: Path = DEFAULT_ORIGINAL_DIR,
    copy_mode: bool = False
):
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)

    supported_exts = {
        ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff",
        ".docx", ".odt", ".txt"
    }

    files = [p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in supported_exts]

    if not files:
        print(f"📁 Thư mục [~/work files] hiện chưa có tài liệu nào cần quét.")
        print(f"👉 Hãy chép hoặc chuyển các tài liệu (ảnh, PDF, DOCX) vào: {input_dir}")
        print(f"👉 Sau đó nói 'scan my file' để tiến hành quét OCR.")
        return []

    today_str = datetime.now().strftime("%Y-%m-%d")
    orig_day_dir = original_dir / today_str
    orig_day_dir.mkdir(parents=True, exist_ok=True)

    result_day_dir = output_dir / today_str
    result_day_dir.mkdir(parents=True, exist_ok=True)

    print(f"🚀 Bắt đầu quét OCR {len(files)} tài liệu trong [{input_dir}]...")
    results = []

    for file_path in files:
        ext = file_path.suffix.lower()
        print(f"\n🔍 Đang xử lý: {file_path.name}")
        lines = []

        try:
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
                lines = extract_text_from_image(file_path)
            elif ext == ".pdf":
                lines = extract_text_from_pdf(file_path)
            elif ext == ".docx":
                lines = extract_text_from_docx(file_path)
            elif ext == ".odt":
                lines = extract_text_from_odt(file_path)
            elif ext == ".txt":
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()

            detected_company = detect_company(lines, file_path.name)
            company_result_dir = result_day_dir / detected_company
            company_result_dir.mkdir(parents=True, exist_ok=True)

            # Move or copy original file to ~/original file/<YYYY-MM-DD>/
            dest_orig_file = orig_day_dir / file_path.name
            if dest_orig_file.exists() and not copy_mode:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest_orig_file = orig_day_dir / f"{file_path.stem}_{ts}{file_path.suffix}"

            # Save OCR transcript in ~/scanned result/<YYYY-MM-DD>/<Company>/
            ocr_text_file = company_result_dir / f"{file_path.stem}_ocr.txt"
            ocr_content = f"--- OCR TRANSCRIPT ---\n"
            ocr_content += f"Original File: {file_path.name}\n"
            ocr_content += f"Detected Company: {detected_company}\n"
            ocr_content += f"Scan Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            ocr_content += f"Total Lines: {len(lines)}\n"
            ocr_content += f"Original Archived At: {dest_orig_file}\n"
            ocr_content += f"----------------------\n\n"
            ocr_content += "\n".join(lines)
            ocr_text_file.write_text(ocr_content, encoding="utf-8")

            if copy_mode:
                shutil.copy2(file_path, dest_orig_file)
                action_verb = "Copied original to"
            else:
                shutil.move(file_path, dest_orig_file)
                action_verb = "Moved original to"

            print(f"  ✓ Nhận diện công ty: {detected_company}")
            print(f"  ✓ {action_verb}: {dest_orig_file}")
            print(f"  ✓ Kết quả OCR lưu tại: {ocr_text_file} ({len(lines)} dòng)")

            results.append({
                "file": file_path.name,
                "company": detected_company,
                "original_dest": str(dest_orig_file),
                "ocr_txt": str(ocr_text_file),
                "lines_count": len(lines),
                "status": "success"
            })

        except Exception as e:
            print(f"  ✗ Lỗi khi xử lý {file_path.name}: {e}")
            results.append({
                "file": file_path.name,
                "error": str(e),
                "status": "failed"
            })

    print(f"\n🎉 Hoàn thành quét! Đã xử lý {len(results)} file.")
    print(f"📂 File gốc lưu tại: {orig_day_dir}")
    print(f"📂 Kết quả scan lưu tại: {result_day_dir}")

    # Explicit memory cleanup so no RAM is retained
    global _pipeline_cache
    _pipeline_cache = None
    import gc
    gc.collect()

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scan work files and sort by company using OCR.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR), help="Input folder to scan")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output sorted results folder")
    parser.add_argument("--original-dir", default=str(DEFAULT_ORIGINAL_DIR), help="Original files archive folder")
    parser.add_argument("--copy", action="store_true", help="Copy files instead of moving")
    args = parser.parse_args()

    process_work_files(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        original_dir=Path(args.original_dir),
        copy_mode=args.copy
    )


if __name__ == "__main__":
    main()
