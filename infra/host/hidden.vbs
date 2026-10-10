' Runs the given command with no console window and returns its exit code.
' A Task Scheduler task that runs "only when the user is logged on" opens a terminal window for every
' console program it starts; the task `ace-host` (task.ps1) therefore runs
'   wscript.exe //B //Nologo hidden.vbs <node.exe> <cli.mjs> revive
Dim parts, i
ReDim parts(WScript.Arguments.Count - 1)
For i = 0 To WScript.Arguments.Count - 1
  parts(i) = """" & WScript.Arguments(i) & """"
Next
WScript.Quit CreateObject("WScript.Shell").Run(Join(parts, " "), 0, True)
