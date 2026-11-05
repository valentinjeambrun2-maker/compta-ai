"""Exports PDF et Excel (.xlsx) sans dépendance externe.

PDF : générateur minimal (Helvetica, encodage WinAnsi, pagination, tableaux).
XLSX : classeur Office Open XML (feuilles multiples, montants numériques au format « € »).
"""
import io, json, zipfile, datetime as dt
from xml.sax.saxutils import escape as xesc
from . import ledger, tax, liasse

E = ledger.euros
ACCENT = (0.294, 0.247, 0.839)
INK, MUTED, HAIR = (0.114, 0.114, 0.122), (0.43, 0.43, 0.45), (0.85, 0.85, 0.87)

# ======================= PDF =======================
_W = [278,278,355,556,556,889,667,191,333,333,389,584,278,333,278,278] + [556]*10 + [278,278,584,584,584,556,1015,
      667,667,722,722,667,611,778,722,278,500,667,556,833,722,778,667,778,722,667,611,722,667,944,667,667,611,
      278,278,278,469,556,333,556,556,500,556,556,278,556,556,222,222,500,222,833,556,556,556,556,333,500,278,
      556,500,722,500,500,500,334,260,334,584]

def _clean(s):
    return str(s if s is not None else "").replace(" ", " ").replace(" ", " ").replace("’", "'").replace("—", "-").replace("→", "->").replace("≈", "~").replace("≥", ">=").replace("≤", "<=").replace("✓", "")

def text_width(s, size, bold=False):
    w = 0
    for ch in _clean(s):
        o = ord(ch)
        w += _W[o - 32] if 32 <= o <= 126 else (556 if ch != "€" else 556)
    return w * size / 1000 * (1.06 if bold else 1)

def pct(v):
    return f"{v:g} %".replace(".", ",") if v else ""

def frdate(d):
    try:
        return dt.date.fromisoformat(d).strftime("%d/%m/%Y")
    except Exception:
        return d or "-"

def money(v):
    return f"{float(v or 0):,.2f}".replace(",", " ").replace(".", ",") + " €"

class PDF:
    W, H, M = 595.28, 841.89, 48

    def __init__(self, title="", subtitle="", company=""):
        self.pages, self.cur, self.title, self.subtitle, self.company = [], None, title, subtitle, company
        self.new_page()

    def new_page(self):
        self.cur = []
        self.pages.append(self.cur)
        self.y = self.H - self.M
        if self.company:
            self.text(self.M, self.H - 30, self.company, 8, color=MUTED)
            self.text(self.W - self.M, self.H - 30, dt.date.today().strftime("%d/%m/%Y"), 8, color=MUTED, align="right")
            self.y = self.H - 60

    def _esc(self, s):
        b = _clean(s).encode("cp1252", "replace")
        return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    def text(self, x, y, s, size=10, bold=False, color=INK, align="left"):
        if align == "right":
            x -= text_width(s, size, bold)
        elif align == "center":
            x -= text_width(s, size, bold) / 2
        self.cur.append(b"BT %.3f %.3f %.3f rg /F%d %.1f Tf %.2f %.2f Td (" % (*color, 2 if bold else 1, size, x, y) + self._esc(s) + b") Tj ET")

    def line(self, x1, y1, x2, y2, w=0.5, color=HAIR):
        self.cur.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (*color, w, x1, y1, x2, y2))

    def rect(self, x, y, w, h, color):
        self.cur.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (*color, x, y, w, h))

    def need(self, h):
        if self.y - h < self.M + 20:
            self.new_page()

    def heading(self, s, size=20):
        self.need(size + 16)
        self.text(self.M, self.y - size, s, size, bold=True)
        self.y -= size + 10

    def para(self, s, size=9.5, color=MUTED, width=None):
        width = width or self.W - 2 * self.M
        for raw in _clean(s).split("\n"):
            words, line = raw.split(" "), ""
            for w in words:
                t = (line + " " + w).strip()
                if text_width(t, size) > width and line:
                    self.need(size + 4); self.text(self.M, self.y - size, line, size, color=color); self.y -= size + 4; line = w
                else:
                    line = t
            self.need(size + 4); self.text(self.M, self.y - size, line, size, color=color); self.y -= size + 4
        self.y -= 4

    def table(self, cols, rows, bold_rows=(), size=9):
        """cols : [(titre, largeur relative, 'l'|'r')], rows : listes de cellules (str ou nombre → montant)."""
        total = sum(c[1] for c in cols); avail = self.W - 2 * self.M
        widths = [c[1] / total * avail for c in cols]
        rh = size + 9

        def header():
            self.need(rh * 2)
            x = self.M
            for (t, _, al), w in zip(cols, widths):
                self.text(x + (w - 4 if al == "r" else 0), self.y - size, t, size - 1, color=MUTED, align="right" if al == "r" else "left")
                x += w
            self.y -= rh - 2
            self.line(self.M, self.y, self.W - self.M, self.y, 0.8, INK)
        header()
        for i, r in enumerate(rows):
            if self.y - rh < self.M + 20:
                self.new_page(); header()
            x, b = self.M, i in bold_rows
            for (t, _, al), w, cell in zip(cols, widths, r):
                s = money(cell) if isinstance(cell, (int, float)) and not isinstance(cell, bool) else _clean(cell)
                while text_width(s, size, b) > w - 6 and len(s) > 3:
                    s = s[:-2]
                self.text(x + (w - 4 if al == "r" else 0), self.y - size - 3, s, size, bold=b, align="right" if al == "r" else "left")
                x += w
            self.y -= rh
            self.line(self.M, self.y, self.W - self.M, self.y)
        self.y -= 12

    def kv(self, pairs, size=10):
        for k, v in pairs:
            self.need(size + 6)
            self.text(self.M, self.y - size, k, size, color=MUTED)
            self.text(self.W - self.M, self.y - size, money(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v, size, bold=True, align="right")
            self.y -= size + 7

    def output(self):
        n = len(self.pages)
        objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
                4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"}
        kids = []
        for i, content in enumerate(self.pages):
            pid, cid = 5 + 2 * i, 6 + 2 * i
            foot = b"BT %.3f %.3f %.3f rg /F1 7.5 Tf %.2f 24 Td (" % (*MUTED, self.W - self.M - 40) + self._esc(f"Page {i + 1} / {n}") + b") Tj ET"
            foot2 = b"BT %.3f %.3f %.3f rg /F1 7.5 Tf %.2f 24 Td (" % (*MUTED, self.M) + self._esc("Généré par ComptaIA") + b") Tj ET"
            stream = b"\n".join(content + [foot, foot2])
            import zlib
            z = zlib.compress(stream)
            objs[cid] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(z) + z + b"\nendstream"
            objs[pid] = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % (self.W, self.H, cid)
            kids.append(b"%d 0 R" % pid)
        objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % n
        title = self._esc(self.title)
        objs[len(objs) + 1] = b"<< /Title (" + title + b") /Producer (ComptaIA) >>"
        info = len(objs)
        out, offs = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), {}
        for k in sorted(objs):
            offs[k] = len(out)
            out += b"%d 0 obj\n" % k + objs[k] + b"\nendobj\n"
        x = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (info + 1) + b"".join(b"%010d 00000 n \n" % offs[k] for k in range(1, info + 1))
        out += b"trailer << /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (info + 1, info, x)
        return bytes(out)

# ======================= XLSX =======================
def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s

def xlsx(sheets):
    """sheets : [(nom, [lignes]) ] ; cellule = str | nombre | ('b', valeur) pour gras | ('m', montant)."""
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    names = []
    for i, (name, _) in enumerate(sheets):
        n = "".join(c for c in name if c not in '[]:*?/\\')[:31] or f"Feuille{i + 1}"
        while n in names:
            n = n[:28] + f"_{i}"
        names.append(n)
    z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
               + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(sheets)))
               + "</Types>")
    z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
               + "".join(f'<sheet name="{xesc(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + "</sheets></workbook>")
    z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
               + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    z.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00\\ &quot;€&quot;"/></numFmts>'
               '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="14"/><name val="Calibri"/></font></fonts>'
               '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
               '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
               '<cellXfs count="5"><xf/><xf fontId="1" applyFont="1"/><xf numFmtId="164" applyNumberFormat="1"/><xf numFmtId="164" fontId="1" applyNumberFormat="1" applyFont="1"/><xf fontId="2" applyFont="1"/></cellXfs>'
               '</styleSheet>')
    for i, (_, rows) in enumerate(sheets):
        widths = {}
        xml = []
        for r, row in enumerate(rows):
            cells = []
            for c, v in enumerate(row):
                style, kind = 0, None
                if isinstance(v, tuple):
                    kind, v = v
                ref = f"{_col(c)}{r + 1}"
                if v is None or v == "":
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    style = 3 if kind == "b" else (2 if kind in ("m", None) and isinstance(v, float) else (1 if kind == "b" else 0))
                    if kind == "m":
                        style = 2
                    cells.append(f'<c r="{ref}" s="{style}"><v>{v}</v></c>')
                    widths[c] = max(widths.get(c, 8), 14)
                else:
                    style = {"b": 1, "h": 4}.get(kind, 0)
                    s = xesc(str(v))
                    cells.append(f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{s}</t></is></c>')
                    widths[c] = max(widths.get(c, 8), min(60, len(str(v)) + 2))
            xml.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
        cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>' for c, w in sorted(widths.items()))
        z.writestr(f"xl/worksheets/sheet{i + 1}.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   + (f"<cols>{cols}</cols>" if cols else "") + f'<sheetData>{"".join(xml)}</sheetData></worksheet>')
    z.close()
    return buf.getvalue()

# ======================= Contenus =======================
def _doc_pdf(con, eid, kind, row, lines, title):
    ent = ledger.entity(con, eid)
    p = PDF(f"{title} {row['number']}", company=ent["name"])
    p.text(p.M, p.y - 26, title, 26, bold=True); p.y -= 36
    p.text(p.M, p.y - 11, row["number"], 11, color=ACCENT, bold=True); p.y -= 28
    top = p.y
    p.text(p.M, p.y - 9, "ÉMETTEUR", 7.5, color=MUTED, bold=True); p.y -= 22
    for s in [ent["name"], ent.get("address") or "", f"SIRET : {ent.get('siret') or '-'}"]:
        p.text(p.M, p.y - 10, s, 10, bold=(s == ent["name"])); p.y -= 14
    y2 = top
    x2 = p.W / 2 + 20
    p.text(x2, y2 - 9, "CLIENT" if kind != "purchase" else "FOURNISSEUR", 7.5, color=MUTED, bold=True); y2 -= 22
    p.text(x2, y2 - 10, row["party"], 10, bold=True); y2 -= 14
    dates = [("Date", row["date"])] + ([("Échéance", row["due"])] if row.get("due") else []) + ([("Valable jusqu'au", row["valid_until"])] if row.get("valid_until") else [])
    for k, v in dates:
        p.text(x2, y2 - 10, f"{k} : {dt.date.fromisoformat(v).strftime('%d/%m/%Y') if v else '-'}", 10); y2 -= 14
    p.y = min(p.y, y2) - 20
    p.table([("Désignation", 46, "l"), ("Qté", 8, "r"), ("PU HT", 15, "r"), ("TVA", 9, "r"), ("Total HT", 18, "r")],
            [[l["label"], f"{l['qty']:g}".replace(".", ","), float(l["unit_price"]), pct(l["tva_rate"]) or "0 %", l["ht"] / 100] for l in lines])
    x = p.W / 2 + 40
    for k, v, b in (("Total HT", row["ht"], False), ("TVA", row["tva"], False), ("Total TTC", row["ttc"], True)):
        p.need(20)
        if b:
            p.rect(x - 10, p.y - 22, p.W - p.M - x + 10, 24, (0.937, 0.929, 0.992))
        p.text(x, p.y - 15, k, 11 if b else 10, bold=b)
        p.text(p.W - p.M - 4, p.y - 15, money(v / 100), 11 if b else 10, bold=True, align="right", color=ACCENT if b else INK)
        p.y -= 24
    p.y -= 20
    if ent["tva_regime"] == "franchise":
        p.para("TVA non applicable, art. 293 B du CGI.", color=INK)
    if kind == "sale":
        p.para("Paiement à l'échéance indiquée. En cas de retard : pénalités au taux de 3 fois le taux d'intérêt légal et indemnité forfaitaire "
               "pour frais de recouvrement de 40 € (art. L441-10 et D441-5 du Code de commerce). Pas d'escompte pour paiement anticipé.", 8)
    elif kind == "quote":
        p.para("Devis valable jusqu'à la date indiquée. Bon pour accord (date, signature et cachet) :", 9, color=INK)
        p.y -= 50; p.line(p.M, p.y, p.M + 220, p.y, 0.6, INK)
    return p.output()

def invoice_pdf(con, eid, inv_id):
    r = con.execute("SELECT * FROM invoices WHERE id=? AND entity_id=?", (inv_id, eid)).fetchone()
    if not r:
        raise ledger.LedgerError("Facture introuvable")
    return _doc_pdf(con, eid, r["kind"], dict(r), json.loads(r["lines"]), "Facture")

def quote_pdf(con, eid, qid):
    r = con.execute("SELECT * FROM quotes WHERE id=? AND entity_id=?", (qid, eid)).fetchone()
    if not r:
        raise ledger.LedgerError("Devis introuvable")
    return _doc_pdf(con, eid, "quote", dict(r), json.loads(r["lines"]), "Devis")

def payslip_pdf(con, eid, sid):
    r = con.execute("SELECT * FROM payslips WHERE id=? AND entity_id=?", (sid, eid)).fetchone()
    if not r:
        raise ledger.LedgerError("Bulletin introuvable")
    b, ent = json.loads(r["data"]), ledger.entity(con, eid)
    s = b["salarie"]
    p = PDF(f"Bulletin {r['period']}", company=ent["name"])
    p.heading("Bulletin de paie", 22)
    p.para(f"Période du {frdate(b['debut'])} au {frdate(b['fin'])}  ·  {ent['name']} — SIRET {ent.get('siret') or '-'}", 9.5)
    p.para(f"Salarié : {s['prenom']} {s['nom']}  ·  {s.get('emploi') or ''}  ·  {s['statut']}  ·  {s['contrat']}  ·  entré le {frdate(s.get('date_entree'))}  ·  "
           f"N° SS : {s.get('nir') or '-'}", 9.5, color=INK)
    p.kv([("Salaire de base", b["brut"]), ("Heures", f"{b['heures']:.2f} h".replace(".", ","))])
    rows = [[l["libelle"], l["base"], pct(l["taux_sal"]), l["sal"] or "", pct(l["taux_pat"]), l["pat"] or ""] for l in b["lignes"]]
    rows.append(["Total des cotisations", "", "", b["total_salarial"], "", b["total_patronal"]])
    p.table([("Cotisation", 40, "l"), ("Base", 14, "r"), ("Taux sal.", 10, "r"), ("Part salariale", 13, "r"), ("Taux pat.", 10, "r"), ("Part patronale", 13, "r")],
            rows, bold_rows={len(rows) - 1}, size=8)
    p.kv([("Net social", b["net_social"]), ("Net imposable", b["net_imposable"]),
          (f"Impôt sur le revenu prélevé à la source (taux {b['type_taux_pas']} {pct(b['taux_pas']) or '0 %'})", b["pas"])])
    p.need(30); p.rect(p.M, p.y - 26, p.W - 2 * p.M, 28, (0.937, 0.929, 0.992))
    p.text(p.M + 10, p.y - 17, "NET À PAYER", 12, bold=True); p.text(p.W - p.M - 10, p.y - 17, money(b["net_a_payer"]), 12, bold=True, color=ACCENT, align="right")
    p.y -= 40
    p.kv([("Coût total employeur", b["cout_employeur"])])
    p.para("Dans votre intérêt et pour vous aider à faire valoir vos droits, conservez ce bulletin de paie sans limitation de durée.", 8)
    return p.output()

def report_data(con, eid, kind, year):
    """Renvoie (titre, [(sous-titre, colonnes, lignes, lignes_en_gras)])."""
    s, e = f"{year}-01-01", f"{year}-12-31"
    A = [("Compte", 12, "l"), ("Libellé", 58, "l"), ("Montant", 30, "r")]
    if kind == "resultat":
        r = ledger.income_statement(con, eid, s, e)
        ch = [[x["account"], x["label"], E(x["montant"])] for x in r["charges"]] + [["", "Total des charges", E(r["total_charges"])]]
        pr = [[x["account"], x["label"], E(x["montant"])] for x in r["produits"]] + [["", "Total des produits", E(r["total_produits"])]]
        return f"Compte de résultat {year}", [("Produits", A, pr, {len(pr) - 1}), ("Charges", A, ch, {len(ch) - 1}),
                                              ("Résultat", A, [["", "Résultat de l'exercice", E(r["resultat"])]], {0})]
    if kind == "bilan":
        b = ledger.balance_sheet(con, eid, e)
        a = [[x["account"], x["label"], E(x["montant"])] for x in b["actif"]] + [["", "Total actif", E(b["total_actif"])]]
        pa = [[x["account"], x["label"], E(x["montant"])] for x in b["passif"]] + [["", "Total passif", E(b["total_passif"])]]
        return f"Bilan au 31/12/{year}", [("Actif", A, a, {len(a) - 1}), ("Passif", A, pa, {len(pa) - 1})]
    if kind == "balance":
        t = ledger.trial_balance(con, eid, s, e)
        cols = [("Compte", 10, "l"), ("Libellé", 42, "l"), ("Débit", 16, "r"), ("Crédit", 16, "r"), ("Solde", 16, "r")]
        rows = [[x["account"], x["label"], E(x["debit"]), E(x["credit"]), E(x["solde"])] for x in t["rows"]]
        rows.append(["", "Totaux", E(t["total_debit"]), E(t["total_credit"]), E(t["total_debit"] - t["total_credit"])])
        return f"Balance générale {year}", [("", cols, rows, {len(rows) - 1})]
    if kind == "journal":
        cols = [("Date", 12, "l"), ("Jnl", 6, "l"), ("Libellé", 40, "l"), ("Compte", 10, "l"), ("Débit", 16, "r"), ("Crédit", 16, "r")]
        rows = []
        for en in reversed(ledger.journal(con, eid, s, e, 100000)):
            for i, l in enumerate(en["lines"]):
                rows.append([en["date"] if not i else "", en["journal"] if not i else "", en["label"] if not i else "", l["account"],
                             E(l["debit"]) if l["debit"] else "", E(l["credit"]) if l["credit"] else ""])
        return f"Journal général {year}", [("", cols, rows, set())]
    if kind == "factures":
        cols = [("N°", 16, "l"), ("Date", 12, "l"), ("Tiers", 26, "l"), ("HT", 14, "r"), ("TVA", 12, "r"), ("TTC", 14, "r"), ("Statut", 10, "l")]
        rows = [[r["number"], r["date"], r["party"], E(r["ht"]), E(r["tva"]), E(r["ttc"]), "réglée" if r["status"] == "paid" else "ouverte"]
                for r in con.execute("SELECT * FROM invoices WHERE entity_id=? AND substr(date,1,4)=? ORDER BY kind DESC, date", (eid, str(year)))]
        return f"Registre des factures {year}", [("", cols, rows, set())]
    if kind == "liasse":
        L = liasse.compute(con, eid, int(year))
        c = [("Ligne", 10, "l"), ("Libellé", 60, "l"), ("Montant", 30, "r")]
        f = lambda xs: [[x["ligne"], x["libelle"], x["montant"]] for x in xs]
        rf = L["resultat_fiscal"]
        fisc = [["", "Résultat comptable", rf["resultat_comptable"]]] + [["", f"Réintégration : {k}", v] for k, v in rf["reintegrations"].items()] + \
               [["", f"Déduction : {k}", v] for k, v in rf["deductions"].items()] + [["370", "Résultat fiscal — bénéfice", rf["370 Résultat fiscal — bénéfice"]],
                                                                                      ["372", "Résultat fiscal — déficit", rf["372 Résultat fiscal — déficit"]]]
        return f"Liasse fiscale 2033 — exercice {year}", [("2033-A — Actif", c, f(L["2033A_actif"]), {len(L["2033A_actif"]) - 1}),
                ("2033-A — Passif", c, f(L["2033A_passif"]), {len(L["2033A_passif"]) - 1}), ("2033-B — Compte de résultat", c, f(L["2033B"]), set()),
                ("2033-B — Résultat fiscal", c, fisc, {len(fisc) - 2}),
                ("2065 — Impôt sur les sociétés", [("Rubrique", 60, "l"), ("Valeur", 40, "r")], [[k, v] for k, v in L["2065"].items()], set())]
    if kind == "paie":
        cols = [("Période", 12, "l"), ("Salarié", 30, "l"), ("Brut", 15, "r"), ("Net à payer", 15, "r"), ("PAS", 13, "r"), ("Coût employeur", 15, "r")]
        rows = []
        for r in con.execute("SELECT p.period, p.data FROM payslips p WHERE p.entity_id=? AND substr(p.period,1,4)=? ORDER BY p.period", (eid, str(year))):
            b = json.loads(r["data"])
            rows.append([r["period"], f"{b['salarie']['prenom']} {b['salarie']['nom']}", b["brut"], b["net_a_payer"], b["pas"], b["cout_employeur"]])
        return f"Livre de paie {year}", [("", cols, rows, set())]
    raise ledger.LedgerError(f"Export inconnu : {kind}")

def report_pdf(con, eid, kind, year):
    title, sections = report_data(con, eid, kind, year)
    ent = ledger.entity(con, eid)
    p = PDF(title, company=ent["name"])
    p.heading(title, 22)
    p.para(f"{ent['name']}  ·  SIRET {ent.get('siret') or '-'}  ·  édité le {dt.date.today().strftime('%d/%m/%Y')}")
    for sub, cols, rows, bold in sections:
        if sub:
            p.y -= 6; p.heading(sub, 13)
        p.table(cols, rows, bold, size=8.5 if len(cols) > 4 else 9.5)
    return p.output()

def report_xlsx(con, eid, kind, year):
    title, sections = report_data(con, eid, kind, year)
    ent = ledger.entity(con, eid)
    sheets = []
    for sub, cols, rows, bold in sections:
        data = [[("h", title)], [ent["name"]], [], [("b", c[0]) for c in cols]]
        for i, r in enumerate(rows):
            data.append([(("b" if i in bold else "m"), v) if isinstance(v, (int, float)) and not isinstance(v, bool) else (("b", v) if i in bold else v) for v in r])
        sheets.append((sub or title[:31], data))
    return xlsx(sheets)
