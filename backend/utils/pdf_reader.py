import pdfplumber


def extract_pdf_text(pdf_path: str) -> str:
    """从 PDF 文件中提取所有文字内容"""
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()
