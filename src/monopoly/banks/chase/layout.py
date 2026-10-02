from pymupdf import TEXTFLAGS_TEXT

from monopoly.pdf import PdfPage

ROW_TOLERANCE = 2.0
CHARACTER_WIDTH = 3.0


def checking_pages(document) -> list[PdfPage]:
    """Recover physical rows despite small baseline differences between fonts."""
    pages = []
    for page in document:
        rows: list[tuple[float, list[tuple]]] = []
        horizontal = {
            (block["number"], idx)
            for block in page.get_text("dict", flags=TEXTFLAGS_TEXT)["blocks"]
            for idx, line in enumerate(block.get("lines", []))
            if line["dir"] == (1, 0)
        }
        words = [word for word in page.get_text("words") if (word[5], word[6]) in horizontal]
        markers: dict[tuple[int, int], list[tuple]] = {}
        for word in words:
            if word[3] - word[1] < ROW_TOLERANCE:
                markers.setdefault((word[5], word[6]), []).append(word)
        for word in sorted(
            (word for word in words if word[3] - word[1] >= ROW_TOLERANCE), key=lambda word: (word[1], word[0])
        ):
            if not rows or abs(rows[-1][0] - word[1]) > ROW_TOLERANCE:
                rows.append((word[1], [word]))
            else:
                rows[-1][1].append(word)
        rows.extend((min(word[1] for word in group), group) for group in markers.values())
        rows.sort(key=lambda row: row[0])
        lines = []
        for _, words in rows:
            line = ""
            for word in sorted(words, key=lambda word: word[0]):
                position = round(word[0] / CHARACTER_WIDTH)
                line += " " * max(1 if line else 0, position - len(line)) + word[4]
            lines.append(line)
        pages.append(PdfPage("\n".join(lines)))
    return pages
