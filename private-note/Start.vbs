Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
arg = " """ & folder & "\private_note.py"""
On Error Resume Next
shell.Run "pyw -3" & arg, 0, False
If Err.Number = 0 Then WScript.Quit
Err.Clear
shell.Run "pythonw.exe" & arg, 0, False
If Err.Number = 0 Then WScript.Quit
MsgBox "Python 3 was not found.", 48, "隐私便签"
