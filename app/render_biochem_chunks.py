from __future__ import annotations

import argparse
import json
from pathlib import Path

from .biochem_review import BIOCHEM_SOURCE_PDF, build_review_chunks, chunk_template_payload, render_chunk_pages
from .config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render review chunks for the biochemistry PDF.")
    parser.add_argument("--pdf", default=BIOCHEM_SOURCE_PDF, help="PDF path relative to repo root or absolute.")
    parser.add_argument("--start-page", type=int, default=28, help="First page to review.")
    parser.add_argument("--end-page", type=int, default=266, help="Last page to review.")
    parser.add_argument("--chunk-size", type=int, default=10, help="Pages per review chunk.")
    parser.add_argument(
        "--output-dir",
        default="data/review/biochem_chunks",
        help="Directory where chunk images and JSON templates are stored.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = settings.base_dir / pdf_path
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = settings.base_dir / output_root
    output_root.mkdir(parents=True, exist_ok=True)

    chunks = build_review_chunks(
        start_page=args.start_page,
        end_page=args.end_page,
        chunk_size=args.chunk_size,
    )

    manifest = {
        "source_pdf": str(pdf_path.relative_to(settings.base_dir)) if pdf_path.is_relative_to(settings.base_dir) else str(pdf_path),
        "chunk_size": args.chunk_size,
        "start_page": args.start_page,
        "end_page": args.end_page,
        "chunks": [],
    }

    for chunk in chunks:
        chunk_dir = output_root / chunk.slug
        images_dir = chunk_dir / "images"
        images = render_chunk_pages(pdf_path, chunk, images_dir)

        review_json_path = chunk_dir / "review.json"
        if not review_json_path.exists():
            review_json_path.write_text(
                json.dumps(
                    chunk_template_payload(
                        chunk,
                        source_pdf=str(pdf_path.relative_to(settings.base_dir))
                        if pdf_path.is_relative_to(settings.base_dir)
                        else str(pdf_path),
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        manifest["chunks"].append(
            {
                "slug": chunk.slug,
                "page_range": {"start": chunk.start_page, "end": chunk.end_page},
                "review_json": str(review_json_path.relative_to(settings.base_dir))
                if review_json_path.is_relative_to(settings.base_dir)
                else str(review_json_path),
                "image_count": len(images),
                "images_dir": str(images_dir.relative_to(settings.base_dir))
                if images_dir.is_relative_to(settings.base_dir)
                else str(images_dir),
            }
        )

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(manifest_path)


if __name__ == "__main__":
    main()
