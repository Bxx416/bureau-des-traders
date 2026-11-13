# Désinstalle le Bureau des Traders : raccourcis + dossier d'installation (réglages et clés Alpaca compris).
Add-Type -AssemblyName System.Windows.Forms
$titre = "Bureau des Traders - Désinstallation"
$dest = Split-Path $PSScriptRoot -Parent
# Seul un dossier créé par l'installateur peut être effacé (jamais le dossier de développement).
if (-not (Test-Path "$PSScriptRoot\.installe")) {
    [System.Windows.Forms.MessageBox]::Show("Ce dossier n'a pas été créé par l'installateur : rien n'est supprimé.", $titre, "OK", "Warning") | Out-Null
    exit 1
}

$ok = [System.Windows.Forms.MessageBox]::Show("Supprimer le Bureau des Traders et tout son dossier ?`n$dest`n`nTes réglages et tes clés Alpaca enregistrées sur ce PC seront effacés. Ton compte Alpaca, lui, n'est pas touché.", $titre, "YesNo", "Warning")
if ($ok -ne "Yes") { exit 0 }

# L'application doit être fermée, sinon ses fichiers sont verrouillés.
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like "*$dest*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

foreach ($dossier in [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs")) {
    Remove-Item (Join-Path $dossier "Bureau des Traders.lnk") -ErrorAction SilentlyContinue
}
Set-Location $env:TEMP
Remove-Item $dest -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $dest) {
    [System.Windows.Forms.MessageBox]::Show("Certains fichiers n'ont pas pu être supprimés. Ferme l'application puis supprime ce dossier à la main :`n$dest", $titre, "OK", "Warning") | Out-Null
} else {
    [System.Windows.Forms.MessageBox]::Show("Le Bureau des Traders est désinstallé.", $titre) | Out-Null
}
