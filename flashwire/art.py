from io import BytesIO
import os
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps


def illustration_path(story):
    folder = os.getenv("FLASHWIRE_ILLUSTRATIONS")
    key = story.get("id", "")
    if folder and re.fullmatch(r"[0-9a-f]{16}", key):
        return Path(folder) / (key + ".jpg")


def create_jpeg(story):
    canvas = Image.new("RGB", (1080, 1350), "white")
    draw = ImageDraw.Draw(canvas)
    ink = "#191919"
    draw.text((72, 68), "FLASHWIRE", font=ImageFont.load_default(52), fill=ink)
    draw.line((72, 152, 1008, 152), fill=ink, width=2)
    draw.text((72, 190), story["region"].upper(), font=ImageFont.load_default(30), fill="#555555")
    path = illustration_path(story)
    illustrated = path and path.is_file()
    top = 445
    if illustrated:
        with Image.open(path) as source:
            art = ImageOps.contain(source.convert("RGB"), (936, 440))
            canvas.paste(art, ((1080-art.width)//2, 244+(440-art.height)//2))
        draw.text((72, 700), "AI-GENERATED ILLUSTRATION", font=ImageFont.load_default(22), fill="#555555")
        top = 766
    for size in range(86, 28, -2):
        font = ImageFont.load_default(size)
        lines = [""]
        for word in story["headline"].split():
            candidate = (lines[-1] + " " + word).strip()
            if lines[-1] and draw.textlength(candidate, font=font) > 936:
                lines.append(word)
            else:
                lines[-1] = candidate
        if len(lines)*(size+12) <= 1190-top:
            break
    draw.multiline_text((72, top), "\n".join(lines), font=font, spacing=10, fill=ink)
    draw.line((72, 1220, 1008, 1220), fill="#cccccc", width=2)
    draw.text((72, 1250), "Sources in caption", font=ImageFont.load_default(28), fill="#555555")
    buffer = BytesIO()
    canvas.save(buffer, format="JPEG", quality=90, optimize=True)
    return buffer.getvalue()
