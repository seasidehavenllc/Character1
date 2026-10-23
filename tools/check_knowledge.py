"""Compile and run every runnable example in the knowledge library.

    python tools/check_knowledge.py            # all languages whose toolchain is installed
    python tools/check_knowledge.py rust go    # only these

A runnable example is a fenced code block whose info string ends in " run",
e.g. ```rust run. It must be a complete program that exits with status 0.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "knowledge"
BLOCK = re.compile(r"^```([\w+#-]+) run\s*\n(.*?)^```", re.S | re.M)


def run_sql(code: str, _: Path) -> tuple[bool, str]:
    db = sqlite3.connect(":memory:")
    out = []
    for stmt in [s.strip() for s in code.split(";") if s.strip()]:
        rows = db.execute(stmt).fetchall()
        out += [" | ".join(map(str, r)) for r in rows]
    return True, "\n".join(out)


# A tiny fake Arduino so sketches can be compiled and run on a PC: pins are simulated,
# analogRead returns fixed values, and loop() runs a few times.
ARDUINO_STUB = r"""
#include <cstdio>
#include <cstdint>
#include <cmath>
typedef uint8_t byte;
const int HIGH = 1, LOW = 0, INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2;
const int A0 = 14, A1 = 15, A2 = 16, A3 = 17, LED_BUILTIN = 13;
static unsigned long fake_ms = 0;
static int pin_values[64];
void pinMode(int, int) {}
void digitalWrite(int pin, int v) { pin_values[pin] = v; }
int digitalRead(int pin) { return pin == 2 ? LOW : pin_values[pin]; }
void analogWrite(int pin, int v) { pin_values[pin] = v; }
int analogRead(int pin) { return pin == A0 ? 600 : 300; }
unsigned long millis() { return fake_ms += 7; }
unsigned long micros() { return fake_ms * 1000; }
void delay(unsigned long ms) { fake_ms += ms; }
void delayMicroseconds(unsigned int) {}
unsigned long pulseIn(int, int, unsigned long = 1000000) { return 1166; }  // ~20 cm echo
long map(long x, long a, long b, long c, long d) { return (x - a) * (d - c) / (b - a) + c; }
template <typename T> T constrain(T x, T lo, T hi) { return x < lo ? lo : (x > hi ? hi : x); }
struct SerialPort {
  void begin(long) {}
  void print(const char *s) { std::printf("%s", s); }
  void print(int v) { std::printf("%d", v); }
  void print(long v) { std::printf("%ld", v); }
  void print(unsigned long v) { std::printf("%lu", v); }
  void print(double v) { std::printf("%.2f", v); }
  template <typename T> void println(T v) { print(v); std::printf("\n"); }
  void println() { std::printf("\n"); }
} Serial;
"""
ARDUINO_MAIN = "\nint main() { setup(); for (int i = 0; i < 3; i++) loop(); return 0; }\n"

# language -> (file name, [commands], required tools)
RUNNERS: dict[str, tuple[str, list[list[str]], list[str]]] = {
    "python": ("main.py", [[sys.executable, "main.py"]], []),
    "javascript": ("main.js", [["node", "main.js"]], ["node"]),
    "typescript": ("main.ts", [["tsc", "--strict", "--target", "es2022", "--module", "commonjs", "main.ts"],
                               ["node", "main.js"]], ["tsc", "node"]),
    "c": ("main.c", [["gcc", "-Wall", "-Wextra", "-Werror", "-std=c11", "main.c", "-o", "main", "-lm"],
                     ["./main"]], ["gcc"]),
    "cpp": ("main.cpp", [["g++", "-Wall", "-Wextra", "-Werror", "-std=c++17", "main.cpp", "-o", "main"],
                         ["./main"]], ["g++"]),
    "arduino": ("main.cpp", [["g++", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-std=c++17",
                              "main.cpp", "-o", "main"], ["./main"]], ["g++"]),
    "go": ("main.go", [["go", "run", "main.go"]], ["go"]),
    "rust": ("main.rs", [["rustc", "--edition", "2021", "-D", "warnings", "main.rs", "-o", "main"], ["./main"]],
             ["rustc"]),
    "java": ("Main.java", [["java", "Main.java"]], ["java"]),
    "csharp": ("Program.cs", [["dotnet", "run"]], ["dotnet"]),
    "kotlin": ("main.kt", [["kotlinc", "main.kt", "-include-runtime", "-d", "main.jar"],
                           ["java", "-jar", "main.jar"]], ["kotlinc"]),
    "swift": ("main.swift", [["swift", "main.swift"]], ["swift"]),
    "php": ("main.php", [["php", "main.php"]], ["php"]),
    "ruby": ("main.rb", [["ruby", "main.rb"]], ["ruby"]),
    "bash": ("main.sh", [["bash", "main.sh"]], ["bash"]),
    "lua": ("main.lua", [["lua", "main.lua"]], ["lua"]),
    "dart": ("main.dart", [["dart", "run", "main.dart"]], ["dart"]),
    "r": ("main.R", [["Rscript", "main.R"]], ["Rscript"]),
}


def run_block(lang: str, code: str) -> tuple[str, str]:
    """Returns (status, detail) where status is 'ok', 'fail' or 'skip'."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        if lang == "sql":
            ok, out = run_sql(code, work)
            return ("ok" if ok else "fail"), out
        if lang not in RUNNERS:
            return "skip", f"no runner for {lang}"
        fname, cmds, tools = RUNNERS[lang]
        missing = [t for t in tools if not shutil.which(t)]
        if missing:
            return "skip", f"{', '.join(missing)} not installed"
        if lang == "arduino":
            code = ARDUINO_STUB + code + ARDUINO_MAIN
        if lang == "csharp":
            subprocess.run(["dotnet", "new", "console", "--force", "-o", "."], cwd=work, capture_output=True)
        (work / fname).write_text(code, encoding="utf-8")
        out = ""
        for cmd in cmds:
            p = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=180)
            out = p.stdout + p.stderr
            if p.returncode != 0:
                return "fail", out
        return "ok", out


def main(only: list[str]) -> int:
    failures = 0
    for path in sorted(ROOT.rglob("*.md")):
        for m in BLOCK.finditer(path.read_text(encoding="utf-8")):
            lang = m.group(1).lower()
            if only and lang not in only:
                continue
            status, detail = run_block(lang, m.group(2))
            name = path.relative_to(ROOT)
            print(f"{status.upper():4} {name} [{lang}]" + (f" — {detail}" if status == "skip" else ""))
            if status == "fail":
                failures += 1
                print("     " + detail.strip().replace("\n", "\n     "))
    print("All runnable examples passed." if not failures else f"{failures} example(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main([a.lower() for a in sys.argv[1:]]))
