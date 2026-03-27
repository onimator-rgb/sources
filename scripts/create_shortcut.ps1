$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("C:\Users\Admin\Desktop\OH.lnk")
$sc.TargetPath = "C:\Users\Admin\Desktop\OH\dist\OH.exe"
$sc.WorkingDirectory = "C:\Users\Admin\Desktop\OH\dist"
$sc.IconLocation = "C:\Users\Admin\Desktop\OH\dist\OH.exe,0"
$sc.Description = "OH - Operational Hub"
$sc.Save()
Write-Host "Shortcut created at Desktop\OH.lnk"
