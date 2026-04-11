"""Poker Table Visual Renderer.

Composites poker_table_bg.png with individual card PNGs to produce
a full game-state snapshot at every turn.

Assets expected in  <project_root>/poker_cards/:
  poker_table_bg.png   (1536 × 1024)
  card_back.png        (256 × 360)
  Ah.png, Td.png …     (256 × 360) — one per card
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False
    logger.warning("[PokerRenderer] Pillow not available — visual rendering disabled")

# ── Asset paths ───────────────────────────────────────────────────────────────
# File is at:  src/luna/systems/mini_games/poker/poker_renderer.py
# Root is 5 levels up.
_ROOT   = Path(__file__).resolve().parents[5]
_ASSETS = _ROOT / "poker_cards"
if not _ASSETS.exists():
    _ASSETS = Path("poker_cards")   # fallback: cwd

_BG_PATH   = _ASSETS / "poker_table_bg.png"
_BACK_PATH = _ASSETS / "card_back.png"
_OUT_DIR   = _ROOT / "storage" / "images"   # reuse existing images dir

# ── Canvas & layout constants ─────────────────────────────────────────────────
_W, _H = 1536, 1024

# Card render sizes (w, h)
_CARD_NPC    = (118, 166)   # NPC hole cards at top
_CARD_BOARD  = (138, 194)   # community cards in centre
_CARD_PLAYER = (152, 213)   # player's hole cards at bottom

# Y baselines
_Y_NPC_CARD   = 55
_Y_BOARD      = 400
_Y_PLAYER_CARD = 745

# Gap between consecutive cards
_GAP = 14

# Semi-transparent dark overlay for text backgrounds
_OVERLAY_FILL = (0, 0, 0, 140)

# Colour palette
_COL_WHITE   = (255, 255, 255, 255)
_COL_YELLOW  = (255, 215,   0, 255)
_COL_GREEN   = (120, 255, 120, 255)
_COL_RED     = (255,  80,  80, 255)
_COL_GREY    = (180, 180, 180, 255)
_COL_GOLD    = (255, 200,  50, 255)
_COL_CYAN    = (100, 220, 255, 255)
_BLACK_STROKE = (0, 0, 0)


# ── Font loader ────────────────────────────────────────────────────────────────
def _load_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    candidates = []
    if bold:
        candidates += [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/Arial Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    candidates += [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _text_w(draw: "ImageDraw.ImageDraw", text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_text_centered(
    draw: "ImageDraw.ImageDraw",
    text: str,
    cx: int,
    y: int,
    font,
    fill=_COL_WHITE,
) -> None:
    w = _text_w(draw, text, font)
    draw.text(
        (cx - w // 2, y), text, font=font, fill=fill,
        stroke_width=2, stroke_fill=_BLACK_STROKE,
    )


def _draw_text(
    draw: "ImageDraw.ImageDraw",
    text: str,
    x: int,
    y: int,
    font,
    fill=_COL_WHITE,
) -> None:
    draw.text(
        (x, y), text, font=font, fill=fill,
        stroke_width=2, stroke_fill=_BLACK_STROKE,
    )


# ── Renderer ───────────────────────────────────────────────────────────────────
class PokerRenderer:
    """Renders the poker table as a PNG from a public_state dict."""

    def __init__(self, assets_dir: Optional[Path] = None) -> None:
        self._assets = Path(assets_dir) if assets_dir else _ASSETS
        self._cache: Dict[str, "Image.Image"] = {}

        # Fonts — loaded lazily
        self._font_lg: Optional["ImageFont.FreeTypeFont"] = None
        self._font_md: Optional["ImageFont.FreeTypeFont"] = None
        self._font_sm: Optional["ImageFont.FreeTypeFont"] = None
        self._font_xs: Optional["ImageFont.FreeTypeFont"] = None

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _fonts(self):
        if self._font_lg is None:
            self._font_lg = _load_font(34, bold=True)
            self._font_md = _load_font(24, bold=True)
            self._font_sm = _load_font(19)
            self._font_xs = _load_font(16)
        return self._font_lg, self._font_md, self._font_sm, self._font_xs

    def _load_card_img(self, code: str) -> Optional["Image.Image"]:
        if not _PIL_OK:
            return None
        if code in self._cache:
            return self._cache[code].copy()
        path = self._assets / (f"{code}.png" if code != "back" else "card_back.png")
        if not path.exists():
            logger.debug("[PokerRenderer] Card asset missing: %s", path)
            return None
        try:
            img = Image.open(path).convert("RGBA")
            self._cache[code] = img
            return img.copy()
        except Exception as exc:
            logger.warning("[PokerRenderer] Cannot load %s: %s", path, exc)
            return None

    def _paste_card(
        self,
        canvas: "Image.Image",
        code: str,
        x: int,
        y: int,
        size: Tuple[int, int],
        alpha: float = 1.0,
    ) -> None:
        img = self._load_card_img(code)
        if img is None:
            return
        img = img.resize(size, Image.LANCZOS)
        if alpha < 1.0:
            r, g, b, a = img.split()
            a = a.point(lambda v: int(v * alpha))
            img = Image.merge("RGBA", (r, g, b, a))
        canvas.paste(img, (x, y), img)

    def _highlight_rect(
        self,
        canvas: "Image.Image",
        x1: int, y1: int, x2: int, y2: int,
        color: Tuple[int, int, int, int],
        width: int = 4,
    ) -> None:
        """Draw a rounded highlight rectangle (alpha overlay)."""
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        for i in range(width):
            d.rectangle([x1 - i, y1 - i, x2 + i, y2 + i], outline=color)
        canvas.alpha_composite(overlay)

    # ── NPC section ────────────────────────────────────────────────────────────

    def _draw_npcs(
        self,
        canvas: "Image.Image",
        draw: "ImageDraw.ImageDraw",
        players: List[Dict],
        to_act: Optional[int],
        dealer_pos: Optional[int],
        reveal: bool,
        font_md, font_sm, font_xs,
    ) -> None:
        npcs = players[1:]
        if not npcs:
            return

        n = len(npcs)
        card_w, card_h = _CARD_NPC
        section_w = card_w * 2 + _GAP          # width for 2 NPC cards
        spacing   = 80                          # horizontal gap between NPC blocks
        total_w   = n * section_w + (n - 1) * spacing
        start_x   = (_W - total_w) // 2

        for ni, npc in enumerate(npcs):
            idx = ni + 1                       # index in players list
            cx  = start_x + ni * (section_w + spacing)
            cy  = _Y_NPC_CARD

            is_acting  = (to_act == idx)
            is_folded  = npc.get("folded", False)
            is_allin   = npc.get("all_in", False)
            is_dealer  = (dealer_pos == idx)
            name       = npc.get("name", f"NPC {ni+1}")
            stack      = npc.get("stack", 0)
            hole       = npc.get("hole", [])

            # Highlight if acting
            if is_acting:
                self._highlight_rect(
                    canvas, cx - 10, cy - 10,
                    cx + section_w + 10, cy + card_h + 10,
                    (255, 215, 0, 200), width=4,
                )

            # Cards
            for ci in range(2):
                card_x = cx + ci * (card_w + _GAP)
                if is_folded:
                    pass                        # no card shown when folded
                elif reveal and len(hole) > ci:
                    self._paste_card(canvas, hole[ci], card_x, cy, _CARD_NPC)
                else:
                    self._paste_card(canvas, "back", card_x, cy, _CARD_NPC)

            # Name badge
            badges = []
            if is_dealer:  badges.append("D")
            if is_allin:   badges.append("ALL-IN")
            if is_folded:  badges.append("FOLD")

            badge_txt = f"  [{' '.join(badges)}]" if badges else ""
            label = f"{name}{badge_txt}"
            col   = _COL_RED if is_folded else (_COL_YELLOW if is_acting else _COL_WHITE)

            lbl_y = cy + card_h + 6
            _draw_text(draw, label,        cx, lbl_y,      font_md, fill=col)
            _draw_text(draw, f"{stack:,}", cx, lbl_y + 28, font_sm, fill=_COL_GOLD)

    # ── Board section ──────────────────────────────────────────────────────────

    def _draw_board(
        self,
        canvas: "Image.Image",
        draw: "ImageDraw.ImageDraw",
        board: List[str],
        street: str,
        pot: int,
        font_lg, font_md,
    ) -> None:
        cw, ch = _CARD_BOARD

        # Draw pot + street header
        header = f"{street}   —   POT: {pot:,} chips"
        _draw_text_centered(draw, header, _W // 2, _Y_BOARD - 52, font_lg, fill=_COL_YELLOW)

        if not board:
            if street not in ("preflop", "init"):
                _draw_text_centered(
                    draw, "(nessuna carta comune)", _W // 2,
                    _Y_BOARD + ch // 2, font_md, fill=_COL_GREY,
                )
            return

        n = len(board)
        total_w = n * cw + (n - 1) * _GAP
        bx = (_W - total_w) // 2

        for i, code in enumerate(board):
            self._paste_card(canvas, code, bx + i * (cw + _GAP), _Y_BOARD, _CARD_BOARD)

    # ── Player section ─────────────────────────────────────────────────────────

    def _draw_player(
        self,
        canvas: "Image.Image",
        draw: "ImageDraw.ImageDraw",
        player: Dict,
        to_act: Optional[int],
        dealer_pos: Optional[int],
        font_md, font_sm,
    ) -> None:
        cw, ch = _CARD_PLAYER
        hole  = player.get("hole", [])
        stack = player.get("stack", 0)
        is_acting = (to_act == 0)
        is_allin  = player.get("all_in", False)
        is_dealer = (dealer_pos == 0)
        is_folded = player.get("folded", False)

        n = max(len(hole), 2)
        total_w = n * cw + (n - 1) * _GAP
        px = (_W - total_w) // 2
        py = _Y_PLAYER_CARD

        # Highlight border
        if is_acting:
            self._highlight_rect(
                canvas, px - 12, py - 12,
                px + total_w + 12, py + ch + 12,
                (0, 255, 80, 220), width=5,
            )

        # Hole cards
        for i, code in enumerate(hole[:n]):
            alpha = 0.4 if is_folded else 1.0
            self._paste_card(canvas, code, px + i * (cw + _GAP), py, _CARD_PLAYER, alpha=alpha)

        # Label
        badges = []
        if is_dealer: badges.append("D")
        if is_allin:  badges.append("ALL-IN")
        if is_folded: badges.append("FOLD")
        badge_txt = f"  [{' '.join(badges)}]" if badges else ""
        col = _COL_GREEN if is_acting else _COL_WHITE

        lbl_y = py + ch + 6
        _draw_text_centered(draw, f"TU{badge_txt}",    _W // 2, lbl_y,      font_md, fill=col)
        _draw_text_centered(draw, f"Stack: {stack:,}", _W // 2, lbl_y + 30, font_sm, fill=_COL_GOLD)

    # ── Hand number badge ──────────────────────────────────────────────────────

    def _draw_hand_badge(
        self,
        draw: "ImageDraw.ImageDraw",
        hand_number: int,
        font_sm,
    ) -> None:
        txt = f"Mano #{hand_number}"
        draw.text((20, 20), txt, font=font_sm, fill=_COL_CYAN,
                  stroke_width=1, stroke_fill=_BLACK_STROKE)

    # ── Public render entry point ──────────────────────────────────────────────

    def render(
        self,
        public_state: Dict,
        hand_number: int = 0,
        reveal_npc_cards: bool = False,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Render a full table snapshot.

        Args:
            public_state:     From engine_v2.GameState.public_state()
            hand_number:      Current hand count (for badge)
            reveal_npc_cards: True at showdown
            output_path:      If None, writes to storage/images/poker_table.png

        Returns:
            Absolute path to the rendered PNG, or None on failure.
        """
        if not _PIL_OK:
            return None

        # Load or create background
        try:
            if _BG_PATH.exists():
                canvas = Image.open(_BG_PATH).convert("RGBA")
                if canvas.size != (_W, _H):
                    canvas = canvas.resize((_W, _H), Image.LANCZOS)
            else:
                canvas = Image.new("RGBA", (_W, _H), (18, 78, 28, 255))
        except Exception as exc:
            logger.error("[PokerRenderer] Cannot load background: %s", exc)
            canvas = Image.new("RGBA", (_W, _H), (18, 78, 28, 255))

        draw = ImageDraw.Draw(canvas)
        font_lg, font_md, font_sm, font_xs = self._fonts()

        players   = public_state.get("players", [])
        board     = public_state.get("board", [])
        street    = public_state.get("street", "?").upper()
        pot       = public_state.get("pot_total", 0)
        to_act    = public_state.get("to_act")
        dealer    = public_state.get("dealer_pos")

        # Draw layers
        if players:
            self._draw_npcs(
                canvas, draw, players, to_act, dealer,
                reveal=reveal_npc_cards,
                font_md=font_md, font_sm=font_sm, font_xs=font_xs,
            )

        self._draw_board(canvas, draw, board, street, pot, font_lg, font_md)

        if players:
            self._draw_player(canvas, draw, players[0], to_act, dealer, font_md, font_sm)

        if hand_number:
            self._draw_hand_badge(draw, hand_number, font_sm)

        # Save
        if output_path is None:
            _OUT_DIR.mkdir(parents=True, exist_ok=True)
            output_path = str(_OUT_DIR / "poker_table.png")

        try:
            canvas.convert("RGB").save(output_path, "PNG")
            return output_path
        except Exception as exc:
            logger.error("[PokerRenderer] Save failed: %s", exc)
            return None
