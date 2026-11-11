# notify - push "logging done" to a phone via ntfy.sh (free, no account).
# FIRST RUN: creates its own conf (notify.conf next to this script) with a
# short hash topic derived from this machine (deterministic - a wiped conf
# regenerates the SAME topic, the phone subscription survives) and shows
# the topic in a message box: install the free ntfy app on your phone and
# subscribe to it. After that: silent pings on every logging end.
# Nothing secret is sent - the hash only makes each machine's topic unique.
param([string]$Message = "logging done")

$Conf = Join-Path $PSScriptRoot "notify.conf"
if (-not (Test-Path $Conf))
{
    $seed = "$env:USERDOMAIN\$env:COMPUTERNAME|$env:USERNAME"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hex = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($seed))) -replace '-','').ToLower()
    $topic = $hex.Substring(0, 12)
    Set-Content -Path $Conf -Value $topic -Encoding ASCII
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $f = New-Object System.Windows.Forms.Form
    $f.Text = "notify - first run"
    $f.StartPosition = "CenterScreen"
    $f.ClientSize = New-Object System.Drawing.Size(560, 260)
    $f.FormBorderStyle = "FixedDialog"
    $f.MaximizeBox = $false
    $f.MinimizeBox = $false
    $l1 = New-Object System.Windows.Forms.Label
    $l1.Text = "Phone notifications topic (ntfy.sh):"
    $l1.Font = New-Object System.Drawing.Font("Segoe UI", 11, [System.Drawing.FontStyle]::Bold)
    $l1.ForeColor = [System.Drawing.Color]::FromArgb(17, 17, 17)
    $l1.Dock = "Top"
    $l1.Height = 48
    $l1.TextAlign = "MiddleCenter"
    $tb = New-Object System.Windows.Forms.TextBox
    $tb.Text = $topic
    $tb.Font = New-Object System.Drawing.Font("Consolas", 24, [System.Drawing.FontStyle]::Bold)
    $tb.ReadOnly = $true
    $tb.BorderStyle = "None"
    $tb.TextAlign = "Center"
    $tb.ForeColor = [System.Drawing.Color]::FromArgb(46, 164, 79)
    $tb.Dock = "Top"
    $tb.Height = 62
    $l2 = New-Object System.Windows.Forms.Label
    $l2.Text = "Install the free ntfy app on your phone and subscribe to this topic."
    $l2.Font = New-Object System.Drawing.Font("Segoe UI", 10)
    $l2.ForeColor = [System.Drawing.Color]::FromArgb(102, 102, 102)
    $l2.Dock = "Top"
    $l2.Height = 48
    $l2.TextAlign = "MiddleCenter"
    $bp = New-Object System.Windows.Forms.Panel
    $bp.Dock = "Bottom"
    $bp.Height = 58
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = "OK"
    $ok.Size = New-Object System.Drawing.Size(110, 32)
    $ok.Location = New-Object System.Drawing.Point(225, 13)
    $bp.Controls.Add($ok)
    $f.Controls.Add($bp)
    $f.Controls.Add($l2)
    $f.Controls.Add($tb)
    $f.Controls.Add($l1)
    [void]$f.ShowDialog()
}
$Topic = (Get-Content $Conf -First 1).Trim()
try
{
    Invoke-RestMethod -Uri ("https://ntfy.sh/" + $Topic) -Method Post -Body $Message -TimeoutSec 10 | Out-Null
}
catch
{
}
