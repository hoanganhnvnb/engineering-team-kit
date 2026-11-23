#!/usr/bin/env bash
# Static page with obvious UX problems. The eval runs without any browser tool.
set -euo pipefail
cat > index.html <<'EOF'
<!doctype html><html><head><meta charset="utf-8"><title>Signup</title><link rel="stylesheet" href="styles.css"></head>
<body><div class="hero"><div class="title">Trailnotes</div>
<form><input type="text" placeholder="Email"><div class="btn" onclick="go()">Go</div></form><p id="msg"></p></div>
<script>function go(){document.getElementById('msg').textContent='Thanks!'}</script></body></html>
EOF
cat > styles.css <<'EOF'
:root { --accent: #15803d; --text: #1f2937; }
.hero { width: 720px; margin: 80px auto; } .lead { color: #c4c4c4; }
.btn { background: var(--accent); color: #fff; padding: 6px 10px; cursor: pointer; }
EOF
git init -q -b main && git add -A && git -c user.email=e@x -c user.name=e commit -qm baseline
