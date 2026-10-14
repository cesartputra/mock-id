"""Local demo puzzle CAPTCHA. No external service or applicant image is used."""

import base64
import io
import secrets
import threading
import time

from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageEnhance

from app.model.verification_entry import PuzzleChallenge, PuzzleReceipt

WIDTH, HEIGHT, PIECE = 320, 180, 52
CHALLENGE_TTL, RECEIPT_TTL = 180, 120
CONSENT_VERSION = "local-capture-self-request-v2"


def png_url(image):
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def puzzle_images(x, y):
    rng = secrets.SystemRandom()
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for row in range(HEIGHT):
        draw.line((0, row, WIDTH, row), fill=(170 + row // 8, 206 - row // 6, 226 - row // 4))
    sun_x = rng.randrange(25, WIDTH - 25)
    draw.ellipse((sun_x - 15, 15, sun_x + 15, 45), fill=(255, 229, 153))
    for start, color in [(20, (132, 165, 164)), (75, (80, 132, 115)), (130, (48, 95, 82))]:
        points = [(-30, HEIGHT), (-30, start + 60)]
        points += [(col, start + rng.randrange(-20, 30)) for col in range(0, WIDTH + 40, 40)]
        points.append((WIDTH + 30, HEIGHT))
        draw.polygon(points, fill=color)
    # Vary the texture without collecting photographs or using remote assets.
    for _ in range(55):
        col, row = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        draw.ellipse((col, row, col + 3, row + 3), fill=rng.choice([(219, 225, 184), (85, 117, 90), (228, 201, 142)]))
    mask = Image.new("L", (PIECE, PIECE), 0)
    shape = ImageDraw.Draw(mask)
    shape.rectangle((8, 8, 43, 43), fill=255)
    shape.ellipse((19, 0, 33, 16), fill=255)
    shape.ellipse((35, 19, 51, 33), fill=255)
    shape.ellipse((0, 19, 16, 33), fill=0)
    shape.ellipse((19, 35, 33, 51), fill=0)
    piece = image.crop((x, y, x + PIECE, y + PIECE)).convert("RGBA")
    piece.putalpha(mask)
    dark = ImageEnhance.Brightness(image.crop((x, y, x + PIECE, y + PIECE))).enhance(.25)
    image.paste(dark, (x, y), mask)
    return png_url(image), png_url(piece)


class VerificationEntryService:
    def __init__(self):
        self.lock = threading.RLock()
        self.challenges = {}
        self.receipts = {}

    def purge(self):
        with self.lock:
            now = time.monotonic()
            for items in [self.challenges, self.receipts]:
                for key, item in list(items.items()):
                    if item.expires <= now:
                        del items[key]

    def issue(self, owner_id):
        with self.lock:
            self.purge()
            # One current puzzle/receipt per owner, plus a bound on total memory.
            for items in [self.challenges, self.receipts]:
                for key, item in list(items.items()):
                    if item.owner_id == owner_id:
                        del items[key]
            if len(self.challenges) + len(self.receipts) >= 512:
                raise HTTPException(503, "CAPTCHA sedang sibuk. Coba kembali sebentar lagi.")
            challenge = PuzzleChallenge(secrets.token_urlsafe(32), owner_id,
                                        secrets.randbelow(166) + 90,
                                        time.monotonic() + CHALLENGE_TTL)
            y = secrets.randbelow(76) + 24
            background, piece = puzzle_images(challenge.target_x, y)
            self.challenges[challenge.id] = challenge
            return {"challenge_id": challenge.id, "background": background, "piece": piece,
                    "width": WIDTH, "height": HEIGHT, "piece_size": PIECE, "piece_y": y,
                    "max_offset": WIDTH - PIECE, "expires_in": CHALLENGE_TTL}

    def solve(self, owner_id, challenge_id, offset):
        with self.lock:
            self.purge()
            challenge = self.challenges.get(challenge_id)
            if not challenge or challenge.owner_id != owner_id:
                raise HTTPException(409, "Puzzle tidak berlaku. Muat puzzle baru.")
            challenge.attempts += 1
            if abs(offset - challenge.target_x) > 5:
                exhausted = challenge.attempts >= 3
                if exhausted:
                    del self.challenges[challenge_id]
                raise HTTPException(409 if exhausted else 422,
                                    "Muat puzzle baru untuk mencoba lagi." if exhausted
                                    else "Posisi potongan belum sesuai. Geser dan periksa kembali.")
            del self.challenges[challenge_id]
            token = secrets.token_urlsafe(32)
            self.receipts[token] = PuzzleReceipt(owner_id, time.monotonic() + RECEIPT_TTL)
            return {"captcha_token": token, "expires_in": RECEIPT_TTL}

    def consume(self, owner_id, token):
        with self.lock:
            self.purge()
            receipt = self.receipts.get(token)
            if not receipt or receipt.owner_id != owner_id:
                raise HTTPException(403, "Selesaikan CAPTCHA sebelum melanjutkan verifikasi.")
            del self.receipts[token]
