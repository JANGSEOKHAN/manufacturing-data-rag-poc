# md_image.py
# -*- coding: utf-8 -*-
"""
마크다운과 이미지 처리 유틸리티 (간소화 버전)
- 이미지 처리: 파일을 data URI로 변환 (간단한 버전)
- 마크다운 변환: HTML 변환
"""

import base64
import re
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


def image_file_to_data_uri(img_path: Path, max_bytes: int = 20 * 1024 * 1024) -> str:
    """
    이미지 파일을 읽어서 data URI(base64) 문자열로 만든다.
    간단한 버전: 리사이즈 없이 원본 그대로 변환.
    """
    if not img_path.exists():
        return ""

    try:
        if img_path.stat().st_size > max_bytes:
            logger.warning(f"이미지 용량 초과: {img_path.name}")
            return ""
        
        ext = img_path.suffix.lower()
        if ext in [".jpg", ".jpeg"]:
            mime = "image/jpeg"
        elif ext == ".gif":
            mime = "image/gif"
        else:
            mime = "image/png"
        
        b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        logger.warning(f"이미지 처리 실패: {img_path.name}: {e}")
        return ""


# Alias for backward compatibility
convert_image_to_data_uri = image_file_to_data_uri


# ============================================================
# 마크다운 변환 유틸리티
# ============================================================

def markdown_to_html_inline_images(md_text: str, image_dir: Path) -> str:
    """
    MinerU가 뽑아준 md 안의 이미지 참조(![](images/...))를 실제 파일로 찾아서
    base64로 인라인화한 HTML 문자열을 만들어준다.
    결과적으로 md + 이미지가 한 HTML 문서로 미리보기 가능해짐.
    """
    img_md_pattern = re.compile(r"!\[\]\(([^)]+)\)")

    def to_data_uri(img_path: Path) -> str:
        return image_file_to_data_uri(img_path)

    html_lines: List[str] = []

    for line in md_text.splitlines():

        # md 이미지 → 인라인 img 로 교체
        def _repl(m):
            rel = m.group(1)
            img_name = Path(rel).name
            img_path = image_dir / img_name
            data_uri = to_data_uri(img_path)
            if not data_uri:
                return f'<img alt="{img_name}" />'
            return (
                f'<img src="{data_uri}" alt="{img_name}" '
                f'style="max-width:100%;height:auto;" />'
            )

        line = img_md_pattern.sub(_repl, line)

        # MinerU가 <table>을 그대로 넣어줄 때는 그대로 HTML에 싣는다
        if line.strip().startswith("<table"):
            html_lines.append(line)
        else:
            # 일반 텍스트는 <p>로 감싸서 HTML화
            if line.strip():
                html_lines.append(f"<p>{line}</p>")
            else:
                html_lines.append("<br/>")

    body_html = "\n".join(html_lines)

    # 아주 단순한 HTML 틀
    full_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <title>Document preview</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
      padding: 1.2rem;
    }}
    img {{
      display:block;
      margin: .4rem 0;
    }}
    table {{
      border-collapse: collapse;
      margin: .5rem 0;
      width: 100%;
    }}
    table td, table th {{
      border: 1px solid #ccc;
      padding: 4px 6px;
    }}
  </style>
</head>
<body>
{body_html}
</body>
</html>
"""
    return full_html

