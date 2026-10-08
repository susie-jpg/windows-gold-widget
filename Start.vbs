Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
scriptArg = " """ & folder & "\gold_widget.py"""
On Error Resume Next
shell.Run "pyw -3" & scriptArg, 0, False
If Err.Number = 0 Then WScript.Quit
Err.Clear
shell.Run "pythonw.exe" & scriptArg, 0, False
If Err.Number = 0 Then WScript.Quit
Err.Clear
pythonFolder = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python"
If fs.FolderExists(pythonFolder) Then
    For Each item In fs.GetFolder(pythonFolder).SubFolders
        executable = item.Path & "\pythonw.exe"
        If fs.FileExists(executable) Then
            shell.Run """" & executable & """" & scriptArg, 0, False
            If Err.Number = 0 Then WScript.Quit
            Err.Clear
        End If
    Next
End If
MsgBox "Python 3 was not found. Install Python from python.org, or run: python gold_widget.py", 48, "Gold Widget"
