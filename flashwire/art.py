from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def create_jpeg(story):
    canvas = Image.new("RGB", (1080, 1350), "#111611")
    draw = ImageDraw.Draw(canvas)
    for coord in range(0, 1080, 72):
        draw.line((coord, 240, coord, 1120), fill="#202b20", width=2)
    for coord in range(240, 1121, 72):
        draw.line((0, coord, 1080, coord), fill="#202b20", width=2)
    for radius in (144, 200, 256, 312):
        draw.ellipse((815-radius, 460-radius, 815+radius, 460+radius), outline="#344b31", width=3)
    draw.line((538, 491, 661, 491, 717, 400, 789, 540, 843, 452, 1013, 452),
              fill="#c5fa6f", width=8, joint="curve")
    draw.rectangle((0, 0, 1080, 18), fill="#c5fa6f")
    draw.text((72, 82), "FLASHWIRE AI", font=ImageFont.load_default(56), fill="#e9f4e6")
    label = f'{story["region"]} / {story["type"]}'.upper()
    draw.text((76, 184), label, font=ImageFont.load_default(29), fill="#c5fa6f")
    draw.rectangle((46, 625, 1034, 1085), fill="#111611")
    for size in range(91, 31, -3):
        font = ImageFont.load_default(size)
        lines = [""]
        for word in story["headline"].split():
            line = f"{lines[-1]} {word}".strip()
            if lines[-1] and draw.textlength(line, font=font) > 920:
                lines.append(word)
            else:
                lines[-1] = line
        if len(lines) * (size + 11) <= 418 and all(draw.textlength(line, font=font) <= 920 for line in lines):
            break
    draw.multiline_text((75, 655), "\n".join(lines), font=font, spacing=11, fill="#f4f8f0")
    draw.rectangle((0, 1140, 1080, 1350), fill="#c5fa6f")
    draw.text((76, 1190), "READ THE SOURCES IN THE CAPTION", font=ImageFont.load_default(34), fill="#111611")
    draw.text((76, 1255), "ORIGINAL FLASHWIRE GRAPHIC", font=ImageFont.load_default(25), fill="#293921")
    buffer = BytesIO()
    canvas.save(buffer, format="JPEG", quality=90, optimize=True)
    return buffer.getvalue()
