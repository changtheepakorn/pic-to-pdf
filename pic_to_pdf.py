"""
Pic to PDF - Core Engine & CLI
Fetch images from URLs and generate professional PDF documents with customizable paper sizes.
"""

import io
import os
import sys
import base64
import argparse
from typing import List, Dict, Any, Tuple, Optional, Union
import requests
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib import pagesizes
from reportlab.lib.utils import ImageReader

# 1 mm = 72 / 25.4 points ≈ 2.834645669 points
MM_TO_PT = 72.0 / 25.4
INCH_TO_PT = 72.0

# Standard paper sizes defined in millimeters (width, height) in portrait
PAPER_SIZES_MM = {
    # ISO A Series
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    # ISO B Series
    "B4": (250.0, 353.0),
    "B5": (176.0, 250.0),
    # US Standards
    "LETTER": (215.9, 279.4),
    "LEGAL": (215.9, 355.6),
    "TABLOID": (279.4, 431.8),
    # Photo Sizes
    "4X6": (101.6, 152.4),
    "5X7": (127.0, 177.8),
    "8X10": (203.2, 254.0),
    # Square
    "SQUARE": (210.0, 210.0),
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def parse_paper_dimensions(
    size_name: str,
    orientation: str = "portrait",
    custom_width_mm: Optional[float] = None,
    custom_height_mm: Optional[float] = None,
) -> Tuple[float, float]:
    """
    Get (width_pt, height_pt) for a given paper size and orientation.
    """
    size_upper = size_name.upper().strip()
    if size_upper == "CUSTOM":
        if not custom_width_mm or not custom_height_mm:
            raise ValueError("For CUSTOM size, custom_width_mm and custom_height_mm must be provided.")
        w_mm = float(custom_width_mm)
        h_mm = float(custom_height_mm)
    elif size_upper in PAPER_SIZES_MM:
        w_mm, h_mm = PAPER_SIZES_MM[size_upper]
    else:
        # Fallback check reportlab pagesizes
        if hasattr(pagesizes, size_upper):
            w_pt, h_pt = getattr(pagesizes, size_upper)
            w_mm, h_mm = w_pt / MM_TO_PT, h_pt / MM_TO_PT
        else:
            raise ValueError(f"Unknown paper size: {size_name}. Available: {list(PAPER_SIZES_MM.keys())} or CUSTOM")

    # Apply orientation
    orient_lower = orientation.lower().strip()
    if orient_lower in ("landscape", "land", "l"):
        width_mm, height_mm = max(w_mm, h_mm), min(w_mm, h_mm)
    else:  # portrait
        width_mm, height_mm = min(w_mm, h_mm), max(w_mm, h_mm)

    return width_mm * MM_TO_PT, height_mm * MM_TO_PT


def fetch_image(source: str, timeout: int = 20) -> Image.Image:
    """
    Fetch an image from a URL, local file path, or base64 data URI.
    Returns a Pillow Image object in RGB mode.
    """
    source = source.strip()
    
    # Base64 Data URI
    if source.startswith("data:image/"):
        header, encoded = source.split(",", 1)
        image_bytes = base64.b64decode(encoded)
        img = Image.open(io.BytesIO(image_bytes))
    # HTTP/HTTPS URL
    elif source.startswith("http://") or source.startswith("https://"):
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        try:
            resp = requests.get(source, headers=headers, timeout=timeout)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
        except requests.exceptions.SSLError:
            # Fallback for self-signed or tricky SSL certs
            resp = requests.get(source, headers=headers, timeout=timeout, verify=False)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
    # Local File Path
    elif os.path.exists(source):
        img = Image.open(source)
    else:
        raise ValueError(f"Source not found or invalid URL/file path: {source}")

    # Normalize image mode to RGB (handles RGBA, P, LA transparency on white background)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba_img = img.convert("RGBA")
        background = Image.new("RGB", rgba_img.size, (255, 255, 255))
        background.paste(rgba_img, mask=rgba_img.split()[3])
        return background
    elif img.mode != "RGB":
        return img.convert("RGB")
    return img


def calculate_image_placement(
    img_width_px: int,
    img_height_px: int,
    page_w_pt: float,
    page_h_pt: float,
    margin_left_pt: float,
    margin_right_pt: float,
    margin_top_pt: float,
    margin_bottom_pt: float,
    fit_mode: str = "fit",
) -> Tuple[float, float, float, float, Optional[Tuple[int, int, int, int]]]:
    """
    Calculate drawing coordinates (x, y, w, h) in PDF points (bottom-left origin)
    and optional crop box (left, upper, right, lower) on the original image for 'fill' mode.
    """
    box_w = max(1.0, page_w_pt - margin_left_pt - margin_right_pt)
    box_h = max(1.0, page_h_pt - margin_top_pt - margin_bottom_pt)

    img_aspect = img_width_px / img_height_px
    box_aspect = box_w / box_h

    crop_box = None
    fit_mode = fit_mode.lower().strip()

    if fit_mode == "stretch":
        draw_w = box_w
        draw_h = box_h
        draw_x = margin_left_pt
        draw_y = margin_bottom_pt

    elif fit_mode in ("fill", "cover"):
        # Scale to cover the entire box and crop excess
        draw_w = box_w
        draw_h = box_h
        draw_x = margin_left_pt
        draw_y = margin_bottom_pt

        # Calculate crop coordinates in source image pixels
        if img_aspect > box_aspect:
            # Source image is wider than target box: crop left and right
            target_px_w = int(img_height_px * box_aspect)
            crop_left = max(0, (img_width_px - target_px_w) // 2)
            crop_right = crop_left + target_px_w
            crop_box = (crop_left, 0, crop_right, img_height_px)
        else:
            # Source image is taller than target box: crop top and bottom
            target_px_h = int(img_width_px / box_aspect)
            crop_top = max(0, (img_height_px - target_px_h) // 2)
            crop_bottom = crop_top + target_px_h
            crop_box = (0, crop_top, img_width_px, crop_bottom)

    elif fit_mode == "center":
        # Native DPI scale (assuming 72 DPI for 1:1 pt mapping, capped to box)
        scale = min(1.0, min(box_w / img_width_px, box_h / img_height_px))
        draw_w = img_width_px * scale
        draw_h = img_height_px * scale
        draw_x = margin_left_pt + (box_w - draw_w) / 2.0
        draw_y = margin_bottom_pt + (box_h - draw_h) / 2.0

    else:  # Default: "fit" (contain within margins keeping aspect ratio)
        if img_aspect > box_aspect:
            draw_w = box_w
            draw_h = box_w / img_aspect
        else:
            draw_h = box_h
            draw_w = box_h * img_aspect

        draw_x = margin_left_pt + (box_w - draw_w) / 2.0
        draw_y = margin_bottom_pt + (box_h - draw_h) / 2.0

    return draw_x, draw_y, draw_w, draw_h, crop_box


def calculate_grid_cells(
    page_w_pt: float,
    page_h_pt: float,
    margin_left_pt: float,
    margin_right_pt: float,
    margin_top_pt: float,
    margin_bottom_pt: float,
    cols: int = 1,
    rows: int = 1,
    gap_pt: float = 0.0,
) -> List[Tuple[float, float, float, float]]:
    """
    Calculate (x, y, w, h) for each cell in a grid (row by row, top to bottom).
    Coordinates are in PDF points with (0,0) at bottom-left.
    """
    avail_w = max(1.0, page_w_pt - margin_left_pt - margin_right_pt)
    avail_h = max(1.0, page_h_pt - margin_top_pt - margin_bottom_pt)

    cols = max(1, int(cols))
    rows = max(1, int(rows))

    total_gap_w = (cols - 1) * gap_pt
    total_gap_h = (rows - 1) * gap_pt

    cell_w = max(1.0, (avail_w - total_gap_w) / cols)
    cell_h = max(1.0, (avail_h - total_gap_h) / rows)

    cells = []
    for r in range(rows):
        # r = 0 is top row, so in PDF coords y starts from top
        cell_y = margin_bottom_pt + (rows - 1 - r) * (cell_h + gap_pt)
        for c in range(cols):
            cell_x = margin_left_pt + c * (cell_w + gap_pt)
            cells.append((cell_x, cell_y, cell_w, cell_h))

    return cells


def create_pdf(
    pages: List[Dict[str, Any]],
    output_dest: Union[str, io.BytesIO],
    title: str = "Image to PDF",
) -> None:
    """
    Generate a PDF from a list of page specifications with grid support.
    """
    if not pages:
        raise ValueError("At least one page is required.")

    if isinstance(output_dest, str):
        parent_dir = os.path.dirname(os.path.abspath(output_dest))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    # Determine first page dimension
    first_p = pages[0]
    p_w, p_h = parse_paper_dimensions(
        first_p.get("size", "A4"),
        first_p.get("orientation", "portrait"),
        first_p.get("custom_width_mm"),
        first_p.get("custom_height_mm"),
    )

    c = canvas.Canvas(output_dest, pagesize=(p_w, p_h))
    c.setTitle(title)
    c.setCreator("ไม่รกจอ Pic to PDF by Chang")

    for idx, p in enumerate(pages):
        page_w, page_h = parse_paper_dimensions(
            p.get("size", "A4"),
            p.get("orientation", "portrait"),
            p.get("custom_width_mm"),
            p.get("custom_height_mm"),
        )
        c.setPageSize((page_w, page_h))

        margin = p.get("margin_mm", 0.0)
        if isinstance(margin, (int, float)):
            m_left = m_right = m_top = m_bottom = float(margin) * MM_TO_PT
        elif isinstance(margin, dict):
            m_left = float(margin.get("left", 0.0)) * MM_TO_PT
            m_right = float(margin.get("right", 0.0)) * MM_TO_PT
            m_top = float(margin.get("top", 0.0)) * MM_TO_PT
            m_bottom = float(margin.get("bottom", 0.0)) * MM_TO_PT
        else:
            m_left = m_right = m_top = m_bottom = 0.0

        cols = int(p.get("grid_cols", 1))
        rows = int(p.get("grid_rows", 1))
        gap_mm = float(p.get("gap_mm", 0.0))
        gap_pt = gap_mm * MM_TO_PT

        # Collect images for this page
        raw_images = p.get("images")
        if not raw_images:
            single = p.get("image") or p.get("source")
            raw_images = [single] if single else []

        cells = calculate_grid_cells(
            page_w, page_h,
            m_left, m_right, m_top, m_bottom,
            cols=cols, rows=rows, gap_pt=gap_pt
        )

        fit_mode = p.get("fit_mode", "fit")

        for img_idx, img_source in enumerate(raw_images):
            if img_idx >= len(cells):
                break
            if not img_source:
                continue

            if isinstance(img_source, Image.Image):
                img = img_source
            else:
                img = fetch_image(img_source)

            cell_x, cell_y, cell_w, cell_h = cells[img_idx]

            dx, dy, dw, dh, crop_box = calculate_image_placement(
                img.width,
                img.height,
                cell_w,
                cell_h,
                0.0, 0.0, 0.0, 0.0,
                fit_mode=fit_mode,
            )

            final_img = img
            if crop_box:
                final_img = img.crop(crop_box)

            c.drawImage(
                ImageReader(final_img),
                cell_x + dx,
                cell_y + dy,
                width=dw,
                height=dh,
                preserveAspectRatio=False,
                mask="auto",
            )

        c.showPage()

    c.save()


def cli_main():
    parser = argparse.ArgumentParser(
        description="Convert images from internet URLs into PDF files with custom paper sizes and grid layouts."
    )
    parser.add_argument("-u", "--url", action="append", help="Image URL (can be specified multiple times)")
    parser.add_argument("-s", "--size", default="A4", help=f"Paper size: {list(PAPER_SIZES_MM.keys())} or CUSTOM")
    parser.add_argument("-o", "--orientation", default="portrait", choices=["portrait", "landscape"])
    parser.add_argument("-m", "--margin", type=float, default=0.0, help="Margin in millimeters (e.g. 10)")
    parser.add_argument("--cols", type=int, default=1, help="Grid columns per page (default: 1)")
    parser.add_argument("--rows", type=int, default=1, help="Grid rows per page (default: 1)")
    parser.add_argument("--gap", type=float, default=2.0, help="Gap between images in mm (default: 2.0)")
    parser.add_argument("--fit", default="fit", choices=["fit", "fill", "stretch", "center"])
    parser.add_argument("--custom-width", type=float, help="Custom width in mm")
    parser.add_argument("--custom-height", type=float, help="Custom height in mm")
    parser.add_argument("-out", "--output", default="output.pdf", help="Output PDF file path")

    args = parser.parse_args()

    urls = args.url
    if not urls:
        print("=== ไม่รกจอ Pic to PDF by Chang CLI ===")
        input_url = input("Enter image URL: ").strip()
        if not input_url:
            print("No URL entered. Exiting.")
            sys.exit(1)
        urls = [input_url]

    pics_per_page = args.cols * args.rows
    pages = []
    # Chunk URLs into pages according to cols * rows
    for i in range(0, len(urls), pics_per_page):
        chunk = urls[i:i + pics_per_page]
        pages.append({
            "images": chunk,
            "grid_cols": args.cols,
            "grid_rows": args.rows,
            "gap_mm": args.gap,
            "size": args.size,
            "orientation": args.orientation,
            "margin_mm": args.margin,
            "fit_mode": args.fit,
            "custom_width_mm": args.custom_width,
            "custom_height_mm": args.custom_height,
        })

    print(f"Fetching {len(urls)} image(s) across {len(pages)} page(s) (Grid: {args.cols}x{args.rows}, {args.size}, {args.orientation})...")
    create_pdf(pages, args.output)
    print(f"Successfully created PDF: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    cli_main()
