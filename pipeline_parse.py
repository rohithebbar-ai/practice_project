"""
pipeline_parse.py  (v2)
────────────────────────
Reads from:  data/raw/<indent_id>/files
Writes to:   pipeline_outputs/01_parsed/<indent_id>/file.txt
             pipeline_outputs/01_parsed_metadata/<indent_id>/file.metadata.json
"""

from pathlib import Path

from src.document_parser import parse_file, SUPPORTED_EXTENSIONS
from src.storage import ensure_dir, save_json, save_error, safe_name
from src.pipeline_paths import PATHS

RAW_DIR = Path("data/raw")


def parse_raw_documents() -> None:
    PATHS.ensure_all()

    files = [
        path for path in RAW_DIR.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    print(f"Found {len(files)} supported files under {RAW_DIR}")

    for file_path in files:
        indent_id      = file_path.parent.name
        safe_indent_id = safe_name(indent_id)

        try:
            print(f"Parsing: {file_path}")
            text, metadata = parse_file(file_path)

            # Save parsed text
            output_dir = PATHS.parsed / safe_indent_id
            ensure_dir(output_dir)
            output_text_path = output_dir / f"{file_path.name}.txt"
            output_text_path.write_text(text, encoding="utf-8")

            # Save metadata
            meta_dir = PATHS.parsed_metadata / safe_indent_id
            ensure_dir(meta_dir)
            metadata["source_file"]       = str(file_path)
            metadata["indent_id"]         = indent_id
            metadata["output_text_file"]  = str(output_text_path)
            save_json(
                metadata,
                meta_dir / f"{safe_name(file_path.name)}.metadata.json",
            )

            print(f"Saved parsed text: {output_text_path}")

        except Exception as exc:
            print(f"Failed parsing {file_path}: {exc}")
            save_error(
                error=exc,
                output_dir=PATHS.logs,
                file_stem=f"parse_{safe_indent_id}_{file_path.name}",
                extra={"file_path": str(file_path)},
            )


if __name__ == "__main__":
    parse_raw_documents()