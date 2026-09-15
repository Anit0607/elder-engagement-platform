"""Generate non-client MP4, MP3 and PDF files for upload acceptance tests."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

WORKSPACE = Path(__file__).resolve().parents[1]


def output_directory(value: str) -> Path:
    target = Path(value).resolve()
    allowed = (WORKSPACE / "output").resolve()
    try:
        target.relative_to(allowed)
    except ValueError:
        raise argparse.ArgumentTypeError("output must stay inside the workspace output folder") from None
    return target


def make_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=A4, pageCompression=1)
    width, height = A4
    page.setTitle("Synthetic Test Content")
    page.setAuthor("Amiko development test generator")
    page.setFillColor(HexColor("#F4F7FB"))
    page.rect(0, 0, width, height, fill=1, stroke=0)
    page.setFillColor(HexColor("#12345B"))
    page.setFont("Helvetica-Bold", 24)
    page.drawString(56, height - 92, "Synthetic Test Content")
    page.setFillColor(HexColor("#1F5F8B"))
    page.setFont("Helvetica-Bold", 15)
    page.drawString(56, height - 132, "Amiko secure upload verification")
    page.setFillColor(HexColor("#243B53"))
    page.setFont("Helvetica", 12)
    lines = [
        "This file contains no client information or personal data.",
        "It exists only to test private PDF upload, validation and review.",
        "Language: English | Rights: generated for development testing",
    ]
    for index, line in enumerate(lines):
        page.drawString(56, height - 190 - index * 25, line)
    page.setFillColor(HexColor("#DDEAF5"))
    page.roundRect(56, height - 340, width - 112, 78, 10, fill=1, stroke=0)
    page.setFillColor(HexColor("#12345B"))
    page.setFont("Helvetica-Bold", 13)
    page.drawString(74, height - 294, "NOT FOR PUBLICATION")
    page.setFont("Helvetica", 11)
    page.drawString(74, height - 320, "Expected result: private quarantine, then Administrator review.")
    page.setFillColor(HexColor("#607D94"))
    page.setFont("Helvetica", 9)
    page.drawString(56, 42, "Generated synthetic sample - no client or personal data")
    page.showPage()
    page.save()


def run_ffmpeg(executable: str, arguments: list[str], environment: dict[str, str]) -> None:
    result = subprocess.run(  # noqa: S603 -- executable is resolved, arguments are fixed
        [executable, "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=False,
        env=environment,
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError("Synthetic media generation failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=output_directory,
        default=WORKSPACE / "output" / "synthetic-media",
    )
    args = parser.parse_args()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg is required")
    args.output.mkdir(parents=True, exist_ok=True)
    temporary = WORKSPACE / "tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "TMP": str(temporary), "TEMP": str(temporary)}
    pdf = args.output / "amiko-synthetic-upload-sample.pdf"
    video = args.output / "amiko-synthetic-upload-sample.mp4"
    audio = args.output / "amiko-synthetic-upload-sample.mp3"
    make_pdf(pdf)
    run_ffmpeg(
        ffmpeg,
        [
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-metadata", "title=Synthetic Test Content",
            "-metadata", "comment=No client or personal data", "-shortest", str(video),
        ],
        environment,
    )
    run_ffmpeg(
        ffmpeg,
        [
            "-f", "lavfi", "-i", "sine=frequency=523.25:sample_rate=44100:duration=4",
            "-c:a", "libmp3lame", "-b:a", "96k",
            "-metadata", "title=Synthetic Test Tone",
            "-metadata", "comment=No client or personal data", str(audio),
        ],
        environment,
    )
    print(
        json.dumps(
            {
                "status": "generated",
                "files": [
                    {"name": path.name, "bytes": path.stat().st_size}
                    for path in (video, audio, pdf)
                ],
                "contains_client_data": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
