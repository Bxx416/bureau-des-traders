# Installe le Bureau des Traders dans le dossier choisi : fichiers, Python 3.12 (via uv), fenêtre, raccourcis.
param([string]$Test)   # -Test <dossier> : installe là sans fenêtres ni raccourcis (vérification)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
$titre = "Bureau des Traders - Installation"
$source = Split-Path $PSScriptRoot -Parent

function Boite($texte, $boutons = "OK", $icone = "Information") {
    [System.Windows.Forms.MessageBox]::Show($texte, $titre, $boutons, $icone)
}
function Verifie($quoi) { if ($LASTEXITCODE -ne 0) { throw "$quoi a échoué (code $LASTEXITCODE)." } }

try {
    if ($Test) { $parent = $Test } else {
        $choix = New-Object System.Windows.Forms.FolderBrowserDialog
        $choix.Description = "Où installer le Bureau des Traders ? Un dossier « Bureau des Traders » sera créé dedans."
        $choix.SelectedPath = [Environment]::GetFolderPath("MyDocuments")
        if ($choix.ShowDialog() -ne "OK") { Write-Host "Installation annulée."; exit 0 }
        $parent = $choix.SelectedPath
    }
    $dest = Join-Path $parent "Bureau des Traders"
    if ((Resolve-Path $source).Path -eq $dest) { throw "Choisis un autre dossier que celui de l'installateur." }

    Write-Host "1/5  Copie des fichiers dans $dest ..."
    # Réinstallation : rien n'est effacé, tes réglages (dossier trader) sont gardés.
    robocopy $source $dest /E /XD .git .venv .fenetre __pycache__ trader dist graphify-out etat-du-travail /XF Installer.bat *.log /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "La copie des fichiers a échoué (robocopy $LASTEXITCODE)." }

    Write-Host "2/5  Recherche de uv (gestionnaire de Python) ..."
    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) { $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe" }
    if (-not (Test-Path $uv)) {
        Write-Host "     uv absent : installation depuis astral.sh (site officiel) ..."
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        if (-not (Test-Path $uv)) { throw "uv n'a pas pu être installé. Vérifie ta connexion internet." }
    }

    Write-Host "3/5  Python 3.12 et la fenêtre de l'application (quelques minutes la 1re fois) ..."
    & $uv venv "$dest\app\.venv" --python 3.12 --clear --quiet; Verifie "La création de Python"
    & $uv pip install --python "$dest\app\.venv\Scripts\python.exe" pywebview ib_async --quiet; Verifie "L'installation de pywebview"

    Write-Host "4/5  Création de Bureau des Traders.exe ..."
    cmd /c "`"$dest\app\compiler-exe.bat`"" | Out-Null; Verifie "La création de l'exe"

    Set-Content "$dest\installer\.installe" "Installé le $(Get-Date -Format 'yyyy-MM-dd')"  # autorise le désinstalleur

    if ($Test) { Write-Host "Test OK : $dest"; exit 0 }
    Write-Host "5/5  Raccourcis (Bureau et menu Démarrer) ..."
    $ws = New-Object -ComObject WScript.Shell
    foreach ($dossier in [Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs")) {
        $lien = $ws.CreateShortcut((Join-Path $dossier "Bureau des Traders.lnk"))
        $lien.TargetPath = "$dest\Bureau des Traders.exe"
        $lien.WorkingDirectory = $dest
        $lien.IconLocation = "$dest\app\icone.ico"
        $lien.Save()
    }

    $go = Boite "Installation terminée dans :`n$dest`n`nAvant de trader : crée ton compte PAPIER Alpaca (argent fictif) et mets tes clés dans ⚙ Réglages. Tout est expliqué dans README.md.`n`nLancer le Bureau des Traders maintenant ?" "YesNo"
    if ($go -eq "Yes") { Start-Process "$dest\Bureau des Traders.exe" -WorkingDirectory $dest }
    exit 0
}
catch {
    if ($Test) { Write-Host "ECHEC : $($_.Exception.Message)"; exit 1 }
    Boite "L'installation n'a pas abouti :`n`n$($_.Exception.Message)" "OK" "Error" | Out-Null
    exit 1
}
