"""Draw generated graph fixtures; Pillow is provided by python-pptx."""

from math import atan2, cos, sin
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def build(output, middle_weight):
    canvas = Image.new("RGB", (800, 440), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=28)
    draw.text((35, 20), "Directed graph: edge labels are weights", fill="black", font=font)
    nodes = {"s": (80, 220), "a": (320, 110), "b": (480, 330), "t": (720, 220)}
    edges = [("s", "a", "2", (190, 130)), ("s", "b", "5", (260, 280)),
             ("a", "b", middle_weight, (400, 200)), ("a", "t", "7", (530, 125)),
             ("b", "t", "2", (600, 280))]
    for start, end, weight, label in edges:
        x, y = nodes[start]; xx, yy = nodes[end]
        angle = atan2(yy-y, xx-x)
        p = (x+30*cos(angle), y+30*sin(angle))
        q = (xx-30*cos(angle), yy-30*sin(angle))
        draw.line([p, q], fill="#284b63", width=4)
        draw.polygon([q, (q[0]-18*cos(angle-.4), q[1]-18*sin(angle-.4)),
                      (q[0]-18*cos(angle+.4), q[1]-18*sin(angle+.4))], fill="#284b63")
        draw.rectangle((label[0]-5, label[1]-5, label[0]+30, label[1]+34), fill="white")
        draw.text(label, weight, fill="black", font=font)
    for name, (x, y) in nodes.items():
        draw.ellipse((x-28, y-28, x+28, y+28), fill="#ecf4fc", outline="#284b63", width=3)
        draw.text((x-8, y-17), name, fill="black", font=font)
    draw.text((35, 390), "Generated educational fixture", fill="#555555", font=font)
    canvas.save(output)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    build(root / "graph.png", "1")
    build(root / "graph-unknown.png", "?")
