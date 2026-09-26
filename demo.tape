# Wendy demo — records a GIF of the agent running.
Output wendy.gif

Set Shell "zsh"
Set FontSize 14
Set Width 1500
Set Height 800
Set Padding 40
Set Theme "TokyoNight"

# Go to the project and clear the screen for a clean start.
Type "cd ~/projects/wendy_agent && clear"
Enter
Sleep 500ms

# Run the agent: this chains search -> read_file -> answer.
Type ".venv/bin/python agent.py 'what does run_agent do?'"
Enter

# Let it finish — the Claude API calls take a few seconds each.
Sleep 20s
