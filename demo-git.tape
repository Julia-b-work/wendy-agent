# Wendy MCP server demo — the git-history differentiators.
Output wendy-git.gif

Set Shell "zsh"
Set FontSize 16
Set Width 1200
Set Height 720
Set Padding 40
Set Theme "TokyoNight"

Type "cd ~/projects/wendy_agent && clear"
Enter
Sleep 500ms

# History: recent commits.
Type ".venv/bin/python -c 'from tools import git_log; print(git_log(6))'"
Enter
Sleep 2s

# Structure: the project map.
Type ".venv/bin/python -c 'from tools import repo_map; print(repo_map())'"
Enter
Sleep 3s
