# Fabrique dist\Bureau-des-Traders.zip à envoyer à un testeur : seulement les fichiers du projet,
# jamais tes données (dossier trader : budget, ordres, clés Alpaca) ni ton environnement.
$ErrorActionPreference = "Stop"
$racine = Split-Path $PSScriptRoot -Parent
Set-Location $racine

$fichiers = git -c core.quotepath=off ls-files -co --exclude-standard |
    Where-Object { $_ -notmatch '^(trader|dist|etat-du-travail|graphify-out)/' -and $_ -notmatch '^\.graphify' -and (Test-Path $_) }
if ($fichiers -match '^trader/|config\.json$') { throw "Un fichier de données personnelles allait partir dans le paquet : arrêt." }

$tmp = Join-Path $env:TEMP "paquet-bdt"
$etage = Join-Path $tmp "Bureau des Traders"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
foreach ($f in $fichiers) {
    $cible = Join-Path $etage $f
    New-Item -ItemType Directory -Force (Split-Path $cible) | Out-Null
    Copy-Item $f $cible
}
New-Item -ItemType Directory -Force dist | Out-Null
$zip = Join-Path $racine "dist\Bureau-des-Traders.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $etage -DestinationPath $zip
Remove-Item $tmp -Recurse -Force
Write-Host "Paquet prêt : $zip ($($fichiers.Count) fichiers)"
