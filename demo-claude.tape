# Wendy MCP demo — Claude Code invoking the wendy git_blame tool.
Output wendy-claude.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1500
Set Height 800
Set Padding 40
Set Theme "TokyoNight"
Set CursorBlink false
Set TypingSpeed 50ms

Type "cd ~/projects/wendy_agent && clear"
Enter
Sleep 500ms

# Load the API key from .env without ever printing its value.
Type "set -a && source .env && set +a"
Enter
Sleep 300ms

Type "/home/julia_lap/.local/bin/claude"
Enter
Sleep 5s

Type "Use the wendy git_blame tool on tools.py"
Enter
Sleep 20s
