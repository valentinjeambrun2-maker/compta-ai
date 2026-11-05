"""Lecture de justificatifs (factures fournisseurs, tickets) en PDF ou en photo.

Chaîne de repli, de la plus précise à la plus simple :
 1. Claude (vision) : lit directement le PDF ou la photo et renvoie les champs structurés ;
 2. texte du PDF : `pdftotext` (poppler) s'il est installé, sinon extracteur PDF intégré (stdlib) ;
 3. photo sans clé API : OCR `tesseract` s'il est installé.
Le texte obtenu est ensuite analysé par `ai.extract_invoice`.
"""
import base64, re, shutil, subprocess, tempfile, zlib, os
from . import ai

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_BYTES = 15 * 1024 * 1024

class DocumentError(ValueError):
    pass

PROMPT = ("Voici une facture ou un justificatif de dépense français. Extrais les données. Réponds UNIQUEMENT en JSON : "
          '{"party":"fournisseur","number":"","date":"AAAA-MM-JJ","due":"AAAA-MM-JJ ou null",'
          '"lines":[{"label":"","qty":1,"unit_price":0.0,"tva_rate":20}],"total_ttc":0.0,"total_tva":0.0,'
          '"categorie":"carburant|restaurant|transport|hebergement|fournitures|logiciel|telecom|autre"}'
          " (unit_price HT en euros ; si seul le TTC est lisible, déduis le HT avec le taux de TVA indiqué).")

def _sniff(data, mime):
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return mime or "application/octet-stream"

# ---------- Extraction de texte PDF sans dépendance ----------
def _unescape(s):
    out, i = bytearray(), 0
    while i < len(s):
        c = s[i]
        if c == 0x5C and i + 1 < len(s):  # backslash
            n = s[i + 1]
            m = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
            if n in m:
                out.append(m[n]); i += 2; continue
            if 0x30 <= n <= 0x37:
                j = i + 1; oct_ = b""
                while j < len(s) and len(oct_) < 3 and 0x30 <= s[j] <= 0x37:
                    oct_ += bytes([s[j]]); j += 1
                out.append(int(oct_, 8) & 0xFF); i = j; continue
            if n in (10, 13):
                i += 2; continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return out.decode("cp1252", errors="replace")

TOKEN = re.compile(rb"\((?:\\.|[^\\)])*\)\s*Tj|\[(?:\((?:\\.|[^\\)])*\)|[^\]])*\]\s*TJ|\((?:\\.|[^\\)])*\)\s*'|"
                   rb"-?[\d.]+\s+-?[\d.]+\s+T[dD]|T\*|ET|<[0-9A-Fa-f\s]+>\s*Tj", re.S)
STR = re.compile(rb"\(((?:\\.|[^\\)])*)\)", re.S)

def pdf_text_builtin(data):
    """Extrait le texte des PDF « classiques » (polices standard). Ne gère pas les PDF scannés."""
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = m.group(1)
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        if b"BT" not in raw:
            continue
        line = []
        for t in TOKEN.finditer(raw):
            tok = t.group(0)
            if tok.endswith(b"TJ"):
                parts = STR.findall(tok)
                line.append("".join(_unescape(p) for p in parts))
            elif tok.endswith(b"Tj") and tok.startswith(b"("):
                line.append(_unescape(STR.search(tok).group(1)))
            elif tok.endswith(b"'"):
                chunks.append("".join(line)); line = [_unescape(STR.search(tok).group(1))]
            else:  # déplacement / fin de bloc => nouvelle ligne
                if line:
                    chunks.append("".join(line)); line = []
        if line:
            chunks.append("".join(line))
    return "\n".join(c.strip() for c in chunks if c.strip())

def pdf_text(data):
    if shutil.which("pdftotext"):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "in.pdf")
            open(f, "wb").write(data)
            try:
                out = subprocess.run(["pdftotext", "-layout", f, "-"], capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
                if out.strip():
                    return out
            except Exception:
                pass
    return pdf_text_builtin(data)

def ocr_image(data):
    if not shutil.which("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "in.img")
        open(f, "wb").write(data)
        try:
            return subprocess.run(["tesseract", f, "-", "-l", "fra+eng"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
        except Exception:
            return ""

def read_document(data, mime=None, filename=""):
    """Renvoie les champs extraits d'une facture (dict), avec 'source' et 'texte'."""
    if not data:
        raise DocumentError("Fichier vide")
    if len(data) > MAX_BYTES:
        raise DocumentError("Fichier trop volumineux (15 Mo maximum)")
    mime = _sniff(data, mime)
    if mime != "application/pdf" and mime not in IMAGE_TYPES:
        raise DocumentError("Format non pris en charge : PDF, JPEG, PNG, WebP ou GIF uniquement")
    # 1. Claude lit le document directement
    if ai.enabled():
        b64 = base64.b64encode(data).decode()
        block = ({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
                 if mime == "application/pdf" else {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
        res = ai._json(ai.llm("Tu es un assistant comptable français qui lit des justificatifs.", [block, {"type": "text", "text": PROMPT}], 1500))
        if isinstance(res, dict) and res.get("lines"):
            res["source"] = "ia-vision"
            return res
    # 2. Texte local puis analyse
    text = pdf_text(data) if mime == "application/pdf" else ocr_image(data)
    if not text.strip():
        hint = ("PDF scanné (image) : configurez ANTHROPIC_API_KEY ou installez tesseract pour l'OCR."
                if mime == "application/pdf" else "Photo : configurez ANTHROPIC_API_KEY (lecture par Claude) ou installez tesseract.")
        raise DocumentError("Aucun texte lisible. " + hint)
    res = ai.extract_invoice(text)
    res["source"] = ("pdf-texte" if mime == "application/pdf" else "ocr") + "+" + res.get("source", "")
    res["texte"] = text[:4000]
    return res
