"""Dessine app/icone.ico (pixel art 32x32 agrandi) sans dépendance : python app/icone.py"""
import struct, zlib
from pathlib import Path

N = 32
FOND, BORD, OR, VERT, ROUGE, GRIS = (0x1c, 0x19, 0x30), (0xff, 0xcc, 0x4d), (0xff, 0xcc, 0x4d), (0x5b, 0xe3, 0x7d), (0xff, 0x5d, 0x6c), (0x3b, 0x35, 0x60)

def dessin():
    px = [[None] * N for _ in range(N)]
    for y in range(N):
        for x in range(N):
            coin = min(x, N - 1 - x) + min(y, N - 1 - y) < 3  # coins arrondis
            if coin:
                continue
            bord = x in (0, N - 1) or y in (0, N - 1) or (min(x, N - 1 - x) + min(y, N - 1 - y) == 3)
            px[y][x] = BORD if bord else FOND
    for y in (10, 17, 24):  # lignes de grille
        for x in range(3, N - 3):
            px[y][x] = GRIS
    # bougies : (x, haut mèche, haut corps, bas corps, bas mèche, couleur)
    for x, hm, hc, bc, bm, c in ((6, 18, 20, 25, 27, VERT), (11, 20, 21, 24, 26, ROUGE),
                                 (16, 13, 15, 21, 23, VERT), (21, 9, 11, 16, 19, VERT), (26, 5, 6, 12, 14, VERT)):
        for y in range(hm, bm + 1):
            px[y][x + 1] = c
        for y in range(hc, bc + 1):
            for dx in range(3):
                px[y][x + dx] = c
    return px

def png(px, s):
    rows = b"".join(b"\0" + b"".join(bytes((*px[y // s][x // s], 255)) if px[y // s][x // s] else b"\0\0\0\0"
                                     for x in range(N * s)) for y in range(N * s))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N * s, N * s, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))

def ico(px, chemin):
    images = [png(px, s) for s in (1, 2, 8)]  # 32, 64, 256 px
    tete = struct.pack("<HHH", 0, 1, len(images))
    off, table = 6 + 16 * len(images), b""
    for s, im in zip((1, 2, 8), images):
        cote = N * s
        table += struct.pack("<BBBBHHII", cote % 256, cote % 256, 0, 0, 1, 32, len(im), off)
        off += len(im)
    Path(chemin).write_bytes(tete + table + b"".join(images))

if __name__ == "__main__":
    px = dessin()
    sortie = Path(__file__).with_name("icone.ico")
    ico(px, sortie)
    Path(__file__).with_name("icone.png").write_bytes(png(px, 8))
    assert sortie.read_bytes()[:4] == b"\0\0\1\0"
    print("écrit", sortie)
