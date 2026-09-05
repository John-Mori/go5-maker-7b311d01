# アイコン生成：カーソル(内部だけ白・輪郭黒・外部透過)、動画/Blueskyアイコン、favicon各サイズ。
from PIL import Image
from collections import deque
import os

UP = 'C:/Users/chami/.claude/uploads/97e0c627-c104-46db-b3e7-a7ae8ad81375/'
OUT = os.path.join(os.path.dirname(__file__), '..', 'assets', 'icons')
OUT = os.path.abspath(OUT)
os.makedirs(OUT, exist_ok=True)

SRC_LINK  = UP + '0c723090-IMG_0486.png'   # カーソル
SRC_MOVIE = UP + 'e8932963-IMG_0410.jpeg'  # 5sec 動画
SRC_BSKY  = UP + '492974ed-IMG_0446.jpeg'  # Bluesky蝶

def fill_interior_white(src, dst, pad=10):
    im = Image.open(src).convert('RGBA')
    w, h = im.size
    px = im.load()
    TH = 128  # これ未満のalpha=透過扱い
    def transp(x, y): return px[x, y][3] < TH
    visited = bytearray(w * h)
    dq = deque()
    def seed(x, y):
        i = y * w + x
        if not visited[i] and transp(x, y):
            visited[i] = 1; dq.append((x, y))
    for x in range(w): seed(x, 0); seed(x, h - 1)
    for y in range(h): seed(0, y); seed(w - 1, y)
    while dq:
        x, y = dq.popleft()
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                i = ny * w + nx
                if not visited[i] and transp(nx, ny):
                    visited[i] = 1; dq.append((nx, ny))
    # 外部から到達できない透過画素＝内部 → 白で不透明に
    for y in range(h):
        for x in range(w):
            if transp(x, y) and not visited[y * w + x]:
                px[x, y] = (255, 255, 255, 255)
    bbox = im.getbbox()
    if bbox:
        l, t, r, b = bbox
        l = max(0, l - pad); t = max(0, t - pad); r = min(w, r + pad); b = min(h, b + pad)
        im = im.crop((l, t, r, b))
    im.save(dst)
    print('link icon:', dst, im.size)

def square_png(src, dst, size, bg=(255,255,255,255)):
    im = Image.open(src).convert('RGBA')
    w, h = im.size
    s = max(w, h)
    canvas = Image.new('RGBA', (s, s), bg)
    canvas.paste(im, ((s - w) // 2, (s - h) // 2), im)
    canvas = canvas.resize((size, size), Image.LANCZOS)
    canvas.save(dst)
    print('icon:', dst, canvas.size)

fill_interior_white(SRC_LINK, os.path.join(OUT, 'ic-link.png'))
square_png(SRC_MOVIE, os.path.join(OUT, 'ic-movie.png'), 256)
square_png(SRC_BSKY,  os.path.join(OUT, 'ic-bsky.png'),  256)
# favicon / ホーム画面用（動画アイコン）
for sz in (180, 192, 512):
    square_png(SRC_MOVIE, os.path.join(OUT, 'app-%d.png' % sz), sz)
print('done')
