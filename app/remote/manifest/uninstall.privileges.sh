if command -v sngrep >/dev/null 2>&1 && command -v setcap >/dev/null 2>&1; then
    setcap -r "$(command -v sngrep)" 2>/dev/null || true
fi
