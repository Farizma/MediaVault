"""QML cannot run without Qt, so this catches the mistakes that would only show up at runtime:
unbalanced braces, QML calling a Python slot that does not exist or with the wrong number of
arguments, QML reacting to a signal that does not exist, unknown Theme keys, unregistered
context properties. Runs anywhere (no PySide6 needed):  python -m unittest discover -s tests"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QML_FILES = sorted((ROOT / "ui").glob("*.qml")) + [ROOT / "player" / "Hud.qml"]
BRIDGES = {  # context property -> (python file, class)
    "Backend": ("ui/dashboard.py", "Dashboard"),
    "Player": ("player/player_engine.py", "PlayerEngine"),
    "Onboarding": ("ui/wizard.py", "WizardController"),
}


def strip(src: str) -> str:
    """Remove comments, blank out string contents (so '//' in image://... and quotes in comments are safe)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            i = src.find("*/", i + 2)
            i = n if i < 0 else i + 2
        elif c in "\"'":
            q, i = c, i + 1
            while i < n and src[i] != q:
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append('""')
        else:
            out.append(c)
            i += 1
    return "".join(out)


def members(pyfile: str, cls: str) -> dict:
    """name -> number of arguments (None for properties, signals, constants)."""
    tree = ast.parse((ROOT / pyfile).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            found = {}
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    decorators = {ast.unparse(d).split("(")[0] for d in item.decorator_list}
                    is_prop = any(d == "Property" or d.endswith(".setter") for d in decorators)
                    found.setdefault(item.name, None if is_prop else len(item.args.args) - 1)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            found[t.id] = None
            return found
    raise AssertionError(f"{cls} not found in {pyfile}")


def call_args(code: str, open_paren: int) -> int:
    depth, commas, i, seen = 0, 0, open_paren, False
    while i < len(code):
        c = code[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return commas + 1 if seen else 0
        elif c == "," and depth == 1:
            commas += 1
        elif depth == 1 and not c.isspace():
            seen = True
        i += 1
    raise AssertionError("unterminated call")


class QmlStaticTests(unittest.TestCase):
    def test_braces_balanced(self):
        for f in QML_FILES:
            code = strip(f.read_text(encoding="utf-8"))
            for a, b in ("{}", "()", "[]"):
                self.assertEqual(code.count(a), code.count(b), f"{f.name}: unbalanced {a}{b}")

    def test_bridge_calls_exist_with_right_arity(self):
        for name, (py, cls) in BRIDGES.items():
            known = members(py, cls)
            for f in QML_FILES:
                code = strip(f.read_text(encoding="utf-8"))
                for m in re.finditer(rf"\b{name}\.(\w+)(\s*\()?", code):
                    attr = m.group(1)
                    self.assertIn(attr, known, f"{f.name}: {name}.{attr} does not exist in {cls}")
                    if m.group(2) and known[attr] is not None:
                        self.assertEqual(call_args(code, m.end() - 1), known[attr],
                                         f"{f.name}: {name}.{attr}() called with the wrong number of arguments")

    def test_signal_handlers_match_python_signals(self):
        for f in QML_FILES:
            code = strip(f.read_text(encoding="utf-8"))
            for m in re.finditer(r"Connections\s*\{", code):
                depth, i = 1, m.end()
                while depth:
                    depth += {"{": 1, "}": -1}.get(code[i], 0)
                    i += 1
                body = code[m.end():i]
                target = re.search(r"target:\s*(\w+)", body)
                if target and target.group(1) in BRIDGES:
                    known = members(*BRIDGES[target.group(1)])
                    for h in re.finditer(r"function\s+on([A-Z]\w*)\s*\(", body):
                        sig = h.group(1)[0].lower() + h.group(1)[1:]
                        self.assertIn(sig, known, f"{f.name}: no signal {sig} on {target.group(1)}")

    def test_theme_keys_exist(self):
        tree = ast.parse((ROOT / "ui" / "__init__.py").read_text(encoding="utf-8"))
        keys = next(set(ast.literal_eval(n.value)) for n in ast.walk(tree)
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "THEME")
        for f in QML_FILES:
            for key in re.findall(r"\bTheme\.(\w+)", strip(f.read_text(encoding="utf-8"))):
                self.assertIn(key, keys, f"{f.name}: Theme.{key} is not defined")

    def test_context_properties_are_registered(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        registered = set(re.findall(r'\("(\w+)", [\w.]+\)', main))
        used = set()
        for f in QML_FILES:
            used |= set(re.findall(r"\b(Theme|Backend|Library|Tabs|Onboarding|Player)\b", strip(f.read_text(encoding="utf-8"))))
        self.assertLessEqual(used, registered)

    def test_model_roles_used_by_the_grid_exist(self):
        roles = set(re.findall(r'b"(\w+)"', (ROOT / "ui" / "dashboard.py").read_text(encoding="utf-8")))
        code = strip((ROOT / "ui" / "Dashboard.qml").read_text(encoding="utf-8"))
        for role in ("key", "title", "meta", "poster", "progress", "done", "badge", "videoUrl", "durationMs", "tabId", "name"):
            self.assertIn(role, roles)
            self.assertRegex(code, rf"\b{role}\b")


class ContextNames(unittest.TestCase):
    def test_context_properties_do_not_shadow_qml_types(self):
        """A QML file named Wizard.qml is a type `Wizard`; a context property of the same name is hidden by it
        (the call then fails with "Property ... of object Unknown Type is not a function")."""
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        names = set(re.findall(r'\("(\w+)", (?:ui\.THEME|app\.\w+)', main))
        self.assertTrue(names)
        stems = {f.stem for f in QML_FILES}
        self.assertEqual(names & stems, set())


if __name__ == "__main__":
    unittest.main()
