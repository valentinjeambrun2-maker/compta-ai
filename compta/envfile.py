"""Chargement d'un fichier `.env` à la racine du projet (bibliothèque standard uniquement).

- Les variables déjà définies dans l'environnement ne sont jamais écrasées.
- Seuls les noms des variables chargées sont mémorisés (`LOADED`) : aucune valeur n'est affichée ni journalisée.
- Désactivé si COMPTA_NO_DOTENV=1 (utilisé par les tests pour rester hors IA).
- Le fichier `.env` est ignoré par Git (voir .gitignore).
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOADED = []

def parse(text):
    """Lit des lignes KEY=VALUE ; ignore les commentaires, accepte `export` et les valeurs entre guillemets."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, val = line.partition("=")
        key = key.strip()
        if not sep or not key or not all(ch.isalnum() or ch == "_" for ch in key):
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        elif " #" in val:  # commentaire en fin de ligne (valeur non quotée)
            val = val.split(" #", 1)[0].rstrip()
        out[key] = val
    return out

def load(path=None):
    """Charge `path` (par défaut `<racine>/.env`) et renvoie les noms des variables ajoutées."""
    if os.environ.get("COMPTA_NO_DOTENV") == "1":
        return []
    try:
        with open(path or os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            values = parse(f.read())
    except (FileNotFoundError, UnicodeDecodeError):
        return []
    added = []
    for key, val in values.items():
        if key not in os.environ:
            os.environ[key] = val
            added.append(key)
    LOADED.extend(added)
    return added
